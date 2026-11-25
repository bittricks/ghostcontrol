"""Closes the focused window on the target machine via Alt+F4 (HID)."""
import argparse
import time

from controller_utils import resolve_controller
from hid_keycodes import MODIFIER_LEFT_ALT, NAMED_KEYS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()

    controller = resolve_controller(port=args.port, baud=args.baud, dry_run=False)
    controller.key_press(NAMED_KEYS["f4"], modifier=MODIFIER_LEFT_ALT, hold_seconds=0.05)
    time.sleep(0.3)
    controller.close()
    print("Done.")


if __name__ == "__main__":
    main()
