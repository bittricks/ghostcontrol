"""
Coordinate calibration: maps points of the captured frame (HDMI) to
coordinates of the controlled PC's real screen.

Usage:
  python calibration.py --target-w 1920 --target-h 1080

Step 1 (calibrate): click, in order, the 4 corners of the screen visible
inside the captured frame -> top-left, top-right, bottom-right, bottom-left.
This produces calibration.json with the transformation matrix.

Step 2 (test): after calibrating, move the mouse over the window and see
the corresponding coordinate on the real screen printed in real time. No
mouse movement is sent yet (no HID transmitter).

q -> quit
r -> redo calibration
"""
import argparse
import json
import logging
import os

import cv2
import numpy as np

from capture_utils import open_configured_capture
from config import load_config
from display_utils import fit_window_size
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

CALIBRATION_PATH = os.path.join(os.path.dirname(__file__), "calibration.json")

CORNER_LABELS = ["top-left", "top-right", "bottom-right", "bottom-left"]


def save_calibration(src_points, target_w, target_h, frame_w=None, frame_h=None):
    data = {
        "src_points": src_points,
        "target_w": target_w,
        "target_h": target_h,
        "frame_w": frame_w,
        "frame_h": frame_h,
    }
    tmp_path = CALIBRATION_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, CALIBRATION_PATH)


def load_calibration():
    if not os.path.exists(CALIBRATION_PATH):
        return None
    with open(CALIBRATION_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if len(data.get("src_points", [])) != 4 or not data.get("target_w") or not data.get("target_h"):
        return None
    return data


def build_homography(src_points, target_w, target_h):
    src = np.array(src_points, dtype=np.float32)
    dst = np.array(
        [[0, 0], [target_w, 0], [target_w, target_h], [0, target_h]],
        dtype=np.float32,
    )
    return cv2.getPerspectiveTransform(src, dst)


def map_point(homography, x, y):
    pt = np.array([[[x, y]]], dtype=np.float32)
    mapped = cv2.perspectiveTransform(pt, homography)
    return float(mapped[0][0][0]), float(mapped[0][0][1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-w", type=int, default=1920)
    parser.add_argument("--target-h", type=int, default=1080)
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    config = load_config()
    cap = open_configured_capture(config)
    if cap is None:
        logger.error("Could not open the capture device. Run device_scan.py first.")
        return

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    clicked_points = []
    homography = None

    existing = load_calibration()
    if (
        existing
        and existing["target_w"] == args.target_w
        and existing["target_h"] == args.target_h
        and existing.get("frame_w") == frame_w
        and existing.get("frame_h") == frame_h
    ):
        homography = build_homography(existing["src_points"], args.target_w, args.target_h)
        logger.info("Existing calibration loaded. Press r to recalibrate.")

    win_w, win_h = fit_window_size(frame_w, frame_h)
    scale_x = frame_w / win_w
    scale_y = frame_h / win_h

    window_name = "calibration"
    cv2.namedWindow(window_name)

    last_mouse_pos = (0, 0)

    def on_mouse(event, x, y, flags, param):
        nonlocal clicked_points, homography, last_mouse_pos
        ox, oy = x * scale_x, y * scale_y
        last_mouse_pos = (ox, oy)
        if event == cv2.EVENT_LBUTTONDOWN and homography is None:
            clicked_points.append([ox, oy])
            logger.info("%s = (%.0f, %.0f)", CORNER_LABELS[len(clicked_points) - 1], ox, oy)
            if len(clicked_points) == 4:
                homography = build_homography(clicked_points, args.target_w, args.target_h)
                save_calibration(clicked_points, args.target_w, args.target_h, frame_w, frame_h)
                logger.info("Calibration saved to %s", CALIBRATION_PATH)

    cv2.setMouseCallback(window_name, on_mouse)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.error("Failed to read a frame.")
                break

            if homography is None:
                for i, (px, py) in enumerate(clicked_points):
                    cv2.circle(frame, (int(px), int(py)), 6, (0, 0, 255), -1)
                    cv2.putText(frame, CORNER_LABELS[i], (int(px) + 10, int(py)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                remaining = 4 - len(clicked_points)
                if remaining > 0:
                    msg = f"click the corner: {CORNER_LABELS[len(clicked_points)]}"
                else:
                    msg = "calibrating..."
                cv2.putText(frame, msg, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            else:
                x, y = last_mouse_pos
                tx, ty = map_point(homography, x, y)
                cv2.putText(
                    frame,
                    f"frame=({x:.0f},{y:.0f}) -> screen=({tx:.0f},{ty:.0f})",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                )

            display_frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_AREA)
            cv2.imshow(window_name, display_frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("r"):
                clicked_points = []
                homography = None
                logger.info("Recalibrating, click the 4 corners again.")
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
