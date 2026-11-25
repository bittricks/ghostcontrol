"""Opening/configuring the HDMI capture device, shared between
calibration.py, capture_preview.py, auto_calibrate.py and
remote_control.py."""
import cv2

WARMUP_FRAMES = 10


def open_configured_capture(config):
    """Open the capture device at the config's index/resolution and
    discard the first few frames (they tend to come out corrupted right
    after the resolution switch). Returns None if the device does not
    open."""
    cap = cv2.VideoCapture(config["capture_index"], cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["requested_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["requested_height"])
    if "requested_fps" in config:
        cap.set(cv2.CAP_PROP_FPS, config["requested_fps"])

    for _ in range(WARMUP_FRAMES):
        cap.read()

    return cap
