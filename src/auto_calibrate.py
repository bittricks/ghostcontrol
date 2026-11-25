"""
Automatic calibration by cursor sweep: instead of clicking the 4 corners
by hand, it sends the real cursor (via CH9329) to the screen corners using
large repeated relative movements (which get pinned at the OS screen edge),
and detects where the cursor appeared in the captured frame by image diff
(cursor_detect.py).

Since there is no rotation/perspective in a digital HDMI capture (it is
just a re-digitized video signal, not a photo at an angle), the top-left
and bottom-right corners suffice: the other two are derived assuming an
axis-aligned rectangle. The result is saved in the same calibration.json
format used by the manual calibration.

Real use (needs the CH9329 connected):
  python auto_calibrate.py --target-w 1920 --target-h 1080

Use to validate the logic without hardware:
  python auto_calibrate.py --simulate
"""
import argparse
import logging
import time

import cv2
import numpy as np

from calibration import save_calibration
from capture_utils import open_configured_capture
from config import load_config
from controller_utils import resolve_controller
from cursor_detect import detect_motion_blob
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

STEP = 127
SWEEP_STEPS = 30
SETTLE_TIME = 0.03
FINAL_SETTLE_TIME = 0.15


def sweep_to_corner(controller, capture_frame_fn, direction, steps=SWEEP_STEPS):
    frame_before = capture_frame_fn()
    dx, dy = direction
    for _ in range(steps):
        controller.move_relative(dx, dy)
        time.sleep(SETTLE_TIME)
    time.sleep(FINAL_SETTLE_TIME)
    frame_after = capture_frame_fn()
    return detect_motion_blob(frame_before, frame_after)


def corners_from_diagonal(top_left, bottom_right):
    tl_x, tl_y = top_left
    br_x, br_y = bottom_right
    top_right = (br_x, tl_y)
    bottom_left = (tl_x, br_y)
    return [list(top_left), list(top_right), list(bottom_right), list(bottom_left)]


def run_calibration_sweep(controller, capture_frame_fn):
    logger.info("Sweeping to the top-left corner...")
    top_left = sweep_to_corner(controller, capture_frame_fn, (-STEP, -STEP))
    if top_left is None:
        logger.error("Did not detect the cursor at the top-left corner. Aborting.")
        return None
    logger.info("  detected at %s", top_left)

    logger.info("Sweeping to the bottom-right corner...")
    bottom_right = sweep_to_corner(controller, capture_frame_fn, (STEP, STEP))
    if bottom_right is None:
        logger.error("Did not detect the cursor at the bottom-right corner. Aborting.")
        return None
    logger.info("  detected at %s", bottom_right)

    return corners_from_diagonal(top_left, bottom_right)


def real_capture_frame_fn(cap):
    def _capture():
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("failed to read a frame from the capture device")
        return frame
    return _capture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-w", type=int, default=1920)
    parser.add_argument("--target-h", type=int, default=1080)
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--simulate", action="store_true", help="validates the logic with a fake screen and cursor, without hardware")
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.simulate:
        run_simulation(args.target_w, args.target_h)
        return

    # no fallback to dry-run: auto-calibrating without hardware makes no sense
    controller = resolve_controller(port=args.port, baud=args.baud, fallback_dry_run=False)
    if controller is None:
        logger.error("Use --simulate to validate the logic without hardware.")
        return

    try:
        config = load_config()
        cap = open_configured_capture(config)
        if cap is None:
            logger.error("Could not open the capture device. Run device_scan.py first.")
            return

        try:
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            corners = run_calibration_sweep(controller, real_capture_frame_fn(cap))
        finally:
            cap.release()
    finally:
        controller.close()

    if corners is None:
        return

    save_calibration(corners, args.target_w, args.target_h, frame_w, frame_h)
    logger.info("Automatic calibration saved: %s", corners)


class FakeTargetScreen:
    """Simulates the target screen + cursor to test the sweep logic without hardware."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cursor_x = width // 2
        self.cursor_y = height // 2
        self.background = np.full((height, width, 3), 180, dtype=np.uint8)

    def move_relative(self, dx, dy, buttons=0, wheel=0):
        self.cursor_x = max(0, min(self.width - 1, self.cursor_x + dx))
        self.cursor_y = max(0, min(self.height - 1, self.cursor_y + dy))

    def close(self):
        pass

    def render(self):
        frame = self.background.copy()
        cv2.circle(frame, (self.cursor_x, self.cursor_y), 6, (0, 0, 0), -1)
        return frame


def run_simulation(target_w, target_h):
    logger.info("Simulated mode: no hardware, validating only the sweep + detection logic.")
    fake_screen = FakeTargetScreen(target_w, target_h)

    capture_calls = {"count": 0}

    def fake_capture_frame_fn():
        capture_calls["count"] += 1
        return fake_screen.render()

    corners = run_calibration_sweep(fake_screen, fake_capture_frame_fn)
    logger.info("frames 'captured' during the simulation: %s", capture_calls["count"])

    if corners is None:
        logger.error("SIMULATION FAILED: did not detect the corners.")
        return

    expected = corners_from_diagonal((0, 0), (target_w - 1, target_h - 1))
    logger.info("detected corners: %s", corners)
    logger.info("expected corners: %s", expected)

    # tolerance larger than 1px: the cursor glyph's centroid is offset from
    # the hotspot (arrow tip) by a small, constant amount, not a scale error
    # -- expected even on real hardware
    tolerance = 10
    ok = all(abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance for a, b in zip(corners, expected))
    logger.info("SIMULATION OK (within the expected tolerance)" if ok else "SIMULATION WITH DIVERGENCE")


if __name__ == "__main__":
    main()
