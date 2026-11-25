"""
End-to-end remote control: captured HDMI video -> coordinate mapping ->
real mouse/keyboard on the target PC via CH9329 (connected through a CH340
adapter).

Two coordinate-mapping modes:

  default (homography): uses calibration.json (4 corners clicked in
    calibration.py or produced by auto_calibrate.py). Generic for any setup,
    but depends on a prior calibration.

  --mon2 (direct mapping): uses monitor2.py to convert the frame position
    straight into absolute coordinates of the target machine's monitor 2,
    without calibration.json. SPECIFIC to the current setup: the capture
    device is on monitor 2 and captures at its SAME resolution (1920x1080),
    so one frame pixel corresponds 1:1 to one monitor pixel (if the
    resolutions differ, a simple linear scale is applied, with no perspective
    correction). If the target machine's monitor geometry changes, update
    monitor2.MONITORS.

Prerequisites:
  1. config.json with the capture device index/resolution (device_scan.py)
  2. calibration.json produced (homography mode only)
  3. CH9329 module connected via CH340 (optional now; without it, it runs in
     dry-run and only prints the frames it would send)

Usage:
  python remote_control.py
  python remote_control.py --port COM5 --baud 9600
  python remote_control.py --mon2 --keyboard
  python remote_control.py --dry-run

In the window:
  move the mouse -> moves the real cursor on the target PC (if hardware connected)
  left button    -> left click on the target PC
  right button   -> right click on the target PC
  without --keyboard: q   -> quit (no keyboard is sent to the target)
  with --keyboard: ESC -> quit; ALL the other keys (letters, digits, symbols,
    Enter, Backspace, Tab, arrows, Home/End/PgUp/PgDn/Delete, including 'q')
    are forwarded to the target machine using the ABNT2 table in
    hid_keycodes.py.
"""
import argparse
import logging
import time
from dataclasses import dataclass

import cv2

import monitor2
from calibration import build_homography, load_calibration, map_point
from capture_utils import open_configured_capture
from ch9329 import BUTTON_LEFT, BUTTON_RIGHT
from config import load_config
from controller_utils import resolve_controller
from display_utils import fit_window_size
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

MIN_SEND_INTERVAL = 1.0 / 60.0

KEY_ESC = 27

# special key codes returned by cv2.waitKeyEx on Windows (virtual-key code
# shifted 16 bits) -> name in hid_keycodes.NAMED_KEYS
SPECIAL_KEYS = {
    0x210000: "pageup",
    0x220000: "pagedown",
    0x230000: "end",
    0x240000: "home",
    0x250000: "left",
    0x260000: "up",
    0x270000: "right",
    0x280000: "down",
    0x2D0000: "insert",
    0x2E0000: "delete",
}

# ASCII control codes that become named keys
NAMED_ASCII = {
    8: "backspace",
    9: "tab",
    10: "enter",
    13: "enter",
}


@dataclass
class _MouseState:
    """Mutable state of the mouse callback (last target shown in the overlay
    + send throttle)."""
    last_target: tuple = (0.0, 0.0)
    last_send: float = 0.0


def frame_point_to_target(fx, fy, homography, frame_w, frame_h, target_w, target_h):
    """Captured-frame point -> point in the target space, clamped to the
    edges. homography=None => --mon2 mode: direct linear scale (1:1 when the
    frame and the monitor have the same resolution); otherwise applies the
    calibration homography."""
    if homography is None:
        tx = fx * target_w / frame_w
        ty = fy * target_h / frame_h
    else:
        tx, ty = map_point(homography, fx, fy)
    tx = max(0, min(target_w - 1, tx))
    ty = max(0, min(target_h - 1, ty))
    return tx, ty


def key_to_hid(key_code):
    """Convert the code returned by cv2.waitKeyEx into a keyboard action:
    ("named", name), ("char", character) or None if the key has no defined
    forwarding."""
    if key_code is None or key_code < 0:
        return None
    name = SPECIAL_KEYS.get(key_code) or NAMED_ASCII.get(key_code)
    if name is not None:
        return ("named", name)
    if 32 <= key_code <= 126:
        return ("char", chr(key_code))
    return None


def forward_key(controller, key_code):
    """Forward a key from the local window to the target machine.
    Returns True if the key was sent."""
    action = key_to_hid(key_code)
    if action is None:
        return False
    kind, value = action
    try:
        if kind == "named":
            controller.press_named_key(value)
        else:
            controller.type_text(value, char_delay=0)
    except ValueError:
        logger.debug("key with no HID mapping: %r", value)
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="CH340 serial port (e.g. COM5). Auto-detects if omitted.")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--dry-run", action="store_true", help="forces simulated mode, sends nothing")
    parser.add_argument(
        "--mon2",
        action="store_true",
        help="direct frame->monitor 2 mapping via monitor2.py, without calibration.json "
        "(specific to a capture device at the same resolution as monitor 2)",
    )
    parser.add_argument(
        "--keyboard",
        action="store_true",
        help="forwards the keyboard to the target machine (the quit key becomes ESC instead of q)",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG-level logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.mon2:
        homography = None
        target_w, target_h = monitor2.MON2_W, monitor2.MON2_H
        logger.info("--mon2 mode: direct mapping to monitor 2 (%dx%d), no homography.", target_w, target_h)
    else:
        calib = load_calibration()
        if calib is None:
            logger.error("No calibration found. Run calibration.py first (or use --mon2).")
            return
        homography = build_homography(calib["src_points"], calib["target_w"], calib["target_h"])
        target_w, target_h = calib["target_w"], calib["target_h"]

    config = load_config()
    cap = open_configured_capture(config)
    if cap is None:
        logger.error("Could not open the capture device. Run device_scan.py first.")
        return

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if args.mon2 and (frame_w, frame_h) != (monitor2.MON2_W, monitor2.MON2_H):
        logger.warning(
            "Captured frame (%dx%d) differs from monitor 2 (%dx%d); using a linear scale "
            "(exact 1:1 only holds with equal resolutions).",
            frame_w, frame_h, monitor2.MON2_W, monitor2.MON2_H,
        )

    win_w, win_h = fit_window_size(frame_w, frame_h)
    scale_x = frame_w / win_w
    scale_y = frame_h / win_h

    controller = resolve_controller(port=args.port, baud=args.baud, dry_run=args.dry_run)

    state = _MouseState()

    def window_point_to_target(x, y):
        """Window (reduced) point -> point in the target space (monitor 2
        local in --mon2 mode, calibrated screen in homography mode)."""
        return frame_point_to_target(
            x * scale_x, y * scale_y, homography, frame_w, frame_h, target_w, target_h
        )

    def send_move(tx, ty):
        if args.mon2:
            monitor2.move_absolute_mon2(controller, tx, ty)
        else:
            controller.move_absolute(tx, ty, target_w, target_h)

    def send_click(tx, ty, button):
        if args.mon2:
            monitor2.click_absolute_mon2(controller, tx, ty, button=button)
        else:
            controller.click_absolute(tx, ty, target_w, target_h, button=button)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            now = time.time()
            if now - state.last_send < MIN_SEND_INTERVAL:
                return
            tx, ty = window_point_to_target(x, y)
            state.last_send = now
            state.last_target = (tx, ty)
            send_move(tx, ty)
        elif event in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
            button = BUTTON_LEFT if event == cv2.EVENT_LBUTTONDOWN else BUTTON_RIGHT
            tx, ty = window_point_to_target(x, y)
            send_click(tx, ty, button)
            state.last_target = (tx, ty)

    window_name = "remote_control"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, on_mouse)

    if args.keyboard:
        logger.info("Ready. Mouse and keyboard forwarded to the target PC. ESC to quit.")
    else:
        logger.info("Ready. Move the mouse over the window to control the target PC. q to quit.")

    mode_label = "MON2" if args.mon2 else "CALIB"
    kb_label = "+KB" if args.keyboard else ""

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.error("Failed to read a frame.")
                break

            tx, ty = state.last_target
            cv2.putText(
                frame,
                f"target=({tx:.0f},{ty:.0f})  {mode_label}{kb_label}  {'DRY-RUN' if controller.dry_run else 'ACTIVE'}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0) if not controller.dry_run else (0, 165, 255),
                2,
            )

            display_frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_AREA)
            cv2.imshow(window_name, display_frame)

            key = cv2.waitKeyEx(1)
            if key == -1:
                continue
            if args.keyboard:
                if key == KEY_ESC:
                    break
                forward_key(controller, key)
            elif key & 0xFF == ord("q"):
                break
    finally:
        controller.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
