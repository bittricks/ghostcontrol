"""
HEADLESS capture of a single frame from the target screen, saved as PNG.

Unlike capture_preview.py / remote_control.py (which open a cv2.imshow
window for a human to watch), this module opens NO window at all: it opens
the HDMI capture device, reads one frame, writes the PNG to disk and
closes. It is the cheap way for the operator agent to "see" the target
machine's screen (just read the generated PNG -- no screenshot of the
local screen and no leftover windows for the user).

Standalone use:
  python capture_frame.py                      -> captures/last_frame.png
  python capture_frame.py --output foo.png     -> custom path

Imported use (how agent_daemon.py uses it, reusing a capture device
already open for several frames in the same batch):
  from capture_frame import capture_frame_to_file
  path = capture_frame_to_file("captures/screen.png")
"""
import argparse
import logging
import os

import cv2

from capture_utils import open_configured_capture
from config import load_config
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "captures", "last_frame.png")

# DirectShow capture devices tend to keep a small internal buffer of frames
# that keep getting queued even when nobody calls read(). If an already-open
# VideoCapture goes a few moments without being read (e.g. sleeping/clicking
# between two capture_frame calls in the same batch) the next read() may
# return an OLD frame, from before the action that just ran. We discard a
# few frames before the real one to make sure the saved PNG reflects the
# target screen's current state.
#
# Recalibrated on 2026-07-02: with FLUSH_FRAMES=3 we saw captures
# intermittently "stuck" on the PREVIOUS step's frame even after moving the
# mouse + waiting 1.0s (e.g. 2 of 5 moves in the same batch showed the
# cursor at the previous move's position, not the current one). It's not an
# insufficient-sleep problem (we already tried 0.5s and 1.0s with the same
# symptom) -- it looks like a variation in the driver/capture device itself
# in the effective size of the internal buffer. We raised the safety margin
# to FLUSH_FRAMES=8 to reduce the chance of grabbing a stale frame.
FLUSH_FRAMES = 8

# MEASURED on 2026-11-07, on the rig, and the result overturns the
# explanation above: the problem is NOT buffer size nor wait time.
#
# Experiment: put text on screen, drain the queue with 5 captures in a row,
# clear everything (Ctrl+A + Delete), wait I seconds and take ONE capture.
# Result with I = 0.5, 1, 2 and 4 seconds: 16 of 16 captures showed the text
# that had ALREADY BEEN DELETED. Waiting longer helps nothing -- not even 4
# seconds.
#
# And, in the same batch, the next capture -- taken without waiting AT ALL,
# ~25ms later -- came out correct in 6 of 6.
#
# In other words: the pipeline is exactly ONE capture behind. Each
# capture_frame effectively returns the screen state from when the PREVIOUS
# capture happened. The grab() calls don't fix it because they don't force
# the decode of a new frame; only a full read() advances it.
#
# That's why we discard a whole read() before the one that counts. It costs
# ~25ms -- versus the 1.0s sleep the old docs told you to take and which, we
# now know, fixed nothing.
DISCARD_READS = 1


def read_fresh_frame(cap):
    """Read ONE current frame from the already-open capture device and return
    the array.

    SINGLE read point for the capture device. It exists because there used
    to be two copies of this logic -- this one and `capture_array` in
    agent_daemon -- and on 2026-11-07 the stale-frame fix was applied to
    only one of them. The one left behind was precisely the VERIFICATION
    path (expect, ocr_region, find_image, wait_for_text), i.e. the ones that
    decide whether it is safe to type.

    Whoever needs a frame: call here. Don't reimplement grab/read.

    Raises RuntimeError if the read fails.
    """
    for _ in range(FLUSH_FRAMES):
        cap.grab()
    # a full read() is discarded: it's the only one that advances the
    # pipeline. See DISCARD_READS for the measurement that proved it.
    for _ in range(DISCARD_READS):
        cap.read()
    ret, frame = cap.read()
    if not ret or frame is None:
        raise RuntimeError("failed to read a frame from the capture device")
    return frame


def capture_frame_to_file(output_path, config=None, cap=None):
    """Read ONE frame and save it as a PNG at output_path (a relative path is
    resolved against the project folder). Opens no window.

    - cap=None   -> opens the capture device just for this frame and closes it.
    - cap=object -> reuses an already-open VideoCapture (the caller owns it:
      the caller closes it). Used by agent_daemon to take several frames in a
      batch without paying the warmup each time.

    Before reading the "real" frame it discards FLUSH_FRAMES frames to drain
    the driver buffer and avoid serving a stale frame (see FLUSH_FRAMES
    above).

    Returns the PNG's absolute path. Raises RuntimeError if the capture
    device doesn't open, the frame fails, or the PNG can't be saved.
    """
    own_cap = cap is None
    if own_cap:
        if config is None:
            config = load_config()
        cap = open_configured_capture(config)
        if cap is None:
            raise RuntimeError(
                f"could not open the capture device (index {config.get('capture_index')}). "
                "Run device_scan.py."
            )
    try:
        frame = read_fresh_frame(cap)

        if not os.path.isabs(output_path):
            output_path = os.path.join(BASE_DIR, output_path)
        output_path = os.path.abspath(output_path)
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        if not cv2.imwrite(output_path, frame):
            raise RuntimeError(f"failed to save PNG at {output_path}")
        logger.info("Frame saved to %s", output_path)
        return output_path
    finally:
        if own_cap:
            cap.release()


def main():
    parser = argparse.ArgumentParser(description="capture one frame of the target screen as a PNG, without opening a window")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="output PNG path (default: captures/last_frame.png)")
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    try:
        path = capture_frame_to_file(args.output)
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1)
    print(path)


if __name__ == "__main__":
    main()
