"""
Opens the HDMI capture device at the configured resolution/fps and shows
the live feed, along with the measured real fps (to validate latency).

q -> quit
"""
import logging
import time

import cv2

from capture_utils import open_configured_capture
from config import load_config
from display_utils import fit_window_size
from logging_utils import setup_logging

logger = logging.getLogger(__name__)


def main():
    setup_logging()
    config = load_config()
    index = config["capture_index"]

    cap = open_configured_capture(config)
    if cap is None:
        logger.error("Could not open index %s. Run device_scan.py first.", index)
        return

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps_reported = cap.get(cv2.CAP_PROP_FPS)
    logger.info("Resolution obtained: %sx%s  fps reported by the driver: %s", actual_w, actual_h, actual_fps_reported)

    window_name = "capture_preview"
    cv2.namedWindow(window_name)
    win_w, win_h = fit_window_size(actual_w, actual_h)

    frame_count = 0
    fps_measured = 0.0
    last_tick = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.error("Failed to read a frame, exiting.")
                break

            frame_count += 1
            now = time.time()
            elapsed = now - last_tick
            if elapsed >= 1.0:
                fps_measured = frame_count / elapsed
                frame_count = 0
                last_tick = now

            cv2.putText(
                frame,
                f"{actual_w}x{actual_h}  fps measured: {fps_measured:.1f}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            display_frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_AREA)
            cv2.imshow(window_name, display_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
