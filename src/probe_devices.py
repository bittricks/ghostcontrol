"""
Non-interactive probe: sweeps the capture indices, reads one frame from
each and reports the resolution and whether the frame looks valid (not
fully black). Useful for confirming that the HDMI reader is being detected
before using the interactive tools (device_scan.py, capture_preview.py).
"""
import cv2
import numpy as np

MAX_INDEX_TO_TRY = 6


def main():
    found_any = False
    for index in range(MAX_INDEX_TO_TRY):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print(f"index {index}: did not open")
            cap.release()
            continue

        ret, frame = cap.read()
        if not ret:
            print(f"index {index}: opened but did not read a frame")
            cap.release()
            continue

        found_any = True
        h, w = frame.shape[:2]
        mean_val = float(np.mean(frame))
        status = "image with content" if mean_val > 2.0 else "frame almost fully black"
        print(f"index {index}: OK  resolution={w}x{h}  pixel_mean={mean_val:.1f}  ({status})")
        cap.release()

    if not found_any:
        print("\nNo capture device responded. Check that the HDMI reader is connected and recognized by Windows.")


if __name__ == "__main__":
    main()
