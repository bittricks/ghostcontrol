"""
Serial protocol implementation for the CH9329 chip (UART -> USB HID
keyboard/mouse bridge). The CH9329 module is connected to the controller PC
through a CH340 USB-serial adapter (it shows up as a COM port) and to the
target PC through USB, where it behaves as a real USB keyboard/mouse.

Frame specification:
  [0x57] [0xAB] [ADDR] [CMD] [LEN] [DATA...] [SUM]
  SUM = sum of all preceding bytes, mod 256

Commands used:
  0x02 -> keyboard (8-byte HID boot report: mod, reserved, k0..k5)
  0x04 -> absolute mouse (marker 0x02, buttons, X 16bit LE, Y 16bit LE, wheel)
  0x05 -> relative mouse (marker 0x01, buttons, dx, dy, wheel)

Source: WCH CH9329 datasheet + the kvm-serial reference implementation
(docs/CH9329_PROTO.md, derived from beijixiaohu/CH9329_COMM).
"""
import logging
import time

import serial

from hid_keycodes import char_to_usage, char_to_sequence, named_key_to_usage


class PartialTypeError(serial.SerialException):
    """Serial failure IN THE MIDDLE of a type_text.

    `typed` = how many characters of `text` were already sent successfully.
    The handler must resend only `text[typed:]`; resending the whole string
    duplicates what is already in the destination field.
    """

    def __init__(self, typed, text, original):
        super().__init__(str(original))
        self.typed = typed
        self.text = text
        self.original = original

    @property
    def remaining(self):
        """The portion still to be typed."""
        return self.text[self.typed:]

logger = logging.getLogger(__name__)

HEAD = (0x57, 0xAB)

CMD_GET_INFO  = 0x01   # returns device info (lock keys, USB status)
CMD_KEYBOARD  = 0x02
CMD_MOUSE_ABS = 0x04
CMD_MOUSE_REL = 0x05
CMD_RESET     = 0x0F   # restores the default configuration and reboots the chip

# ACK frame: header(2)+addr(1)+(cmd|0x80)(1)+len(1)+status(1)+sum(1) = 7 bytes
# status 0x00 = OK; other values = error (invalid checksum, unknown cmd...)
ACK_LEN = 7

ABS_MARKER = 0x02
REL_MARKER = 0x01

BUTTON_LEFT = 0x01
BUTTON_RIGHT = 0x02
BUTTON_MIDDLE = 0x04

ABS_RANGE = 4096

# Bits of the LED byte in the CMD_GET_INFO response. These are the REAL
# lights the target Windows told to turn on, so it is the only honest way to
# know the lock state: the chip does not store this, the target drives it.
# It matters because a stuck Caps Lock raises NO error anywhere -- it just
# silently flips the case of every typed letter, and the symptom shows up
# far from the cause (e.g. "incorrect password").
LED_NUM_LOCK = 0x01
LED_CAPS_LOCK = 0x02
LED_SCROLL_LOCK = 0x04

# Positions inside the GET_INFO response frame:
# 57 AB <addr> 81 <len> <version> <usb status> <leds> ... <sum>
INFO_CMD_ECHO = 0x81
INFO_IDX_VERSION = 5
INFO_IDX_USB = 6
INFO_IDX_LEDS = 7
INFO_MIN_LEN = 8


def parse_info(frame):
    """Interpret the CMD_GET_INFO response.

    Separated from get_info() on purpose: the parser is testable without a
    serial port, which is where the index and bit errors live.

    Returns a dict with version, usb_connected, num/caps/scroll and the raw
    byte. Raises ValueError if the frame is not a GET_INFO response -- a
    short frame, a wrong header or an echo of a different command. It never
    returns "all off" for invalid input: a false "Caps Lock off" is worse
    than an error, because it passes through diagnosis.
    """
    if not frame:
        raise ValueError("GET_INFO did not respond (None or empty)")
    b = bytes(frame)
    if len(b) < INFO_MIN_LEN:
        raise ValueError(
            "GET_INFO response too short: %d bytes (%s)" % (len(b), b.hex(" ")))
    if b[0] != HEAD[0] or b[1] != HEAD[1]:
        raise ValueError("unexpected header in GET_INFO: %s" % b.hex(" "))
    if b[3] != INFO_CMD_ECHO:
        raise ValueError(
            "command echo 0x%02X, expected 0x%02X: %s"
            % (b[3], INFO_CMD_ECHO, b.hex(" ")))
    leds = b[INFO_IDX_LEDS]
    return {
        "version": b[INFO_IDX_VERSION],
        "usb_connected": bool(b[INFO_IDX_USB]),
        "leds": leds,
        "num_lock": bool(leds & LED_NUM_LOCK),
        "caps_lock": bool(leds & LED_CAPS_LOCK),
        "scroll_lock": bool(leds & LED_SCROLL_LOCK),
        "raw": b.hex(" "),
    }


def checksum(bytes_so_far):
    return sum(bytes_so_far) % 256


def build_frame(cmd, data, addr=0x00):
    body = [HEAD[0], HEAD[1], addr, cmd, len(data)] + list(data)
    body.append(checksum(body))
    return bytes(body)


def clamp_signed_byte(value):
    # & 0xFF already produces two's complement for negatives in Python
    # (-1 & 0xFF == 255), so a single path covers both signs
    return max(-127, min(127, int(value))) & 0xFF


def scale_to_abs(pixel, dimension):
    dimension = max(1, dimension)
    scaled = int((ABS_RANGE * pixel) / dimension)
    return max(0, min(ABS_RANGE - 1, scaled))


def build_mouse_absolute_frame(x, y, screen_w, screen_h, buttons=0, wheel=0, addr=0x00):
    abs_x = scale_to_abs(x, screen_w)
    abs_y = scale_to_abs(y, screen_h)
    data = [
        ABS_MARKER,
        buttons & 0xFF,
        abs_x & 0xFF,
        (abs_x >> 8) & 0xFF,
        abs_y & 0xFF,
        (abs_y >> 8) & 0xFF,
        clamp_signed_byte(wheel),
    ]
    return build_frame(CMD_MOUSE_ABS, data, addr=addr)


def build_mouse_relative_frame(dx, dy, buttons=0, wheel=0, addr=0x00):
    data = [
        REL_MARKER,
        buttons & 0xFF,
        clamp_signed_byte(dx),
        clamp_signed_byte(dy),
        clamp_signed_byte(wheel),
    ]
    return build_frame(CMD_MOUSE_REL, data, addr=addr)


def build_keyboard_frame(modifier=0, keycodes=(), addr=0x00):
    # the boot report requires exactly 6 keycodes: truncate and pad with 0
    keys = list(keycodes)[:6]
    keys += [0] * (6 - len(keys))
    data = [modifier & 0xFF, 0x00] + keys
    return build_frame(CMD_KEYBOARD, data, addr=addr)


class CH9329Controller:
    """High-level controller over the CH340/CH9329 serial port."""

    def __init__(self, port, baudrate=9600, addr=0x00, dry_run=False, timeout=1):
        self.addr = addr
        self.dry_run = dry_run
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial = None
        if not dry_run:
            self._serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def close(self):
        if self._serial is not None:
            self._serial.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def reconnect(self):
        """Close and reopen the serial port. Useful after a SerialException."""
        if self.dry_run:
            return
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self._serial = serial.Serial(self._port, baudrate=self._baudrate,
                                     timeout=self._timeout)
        # If the previous failure landed between keydown and keyup, the chip
        # was left with a (possibly modifier) key stuck -- and a stuck
        # Ctrl/Win turns the following letters into shortcuts. Release
        # everything on reconnect.
        self.release_all_keys()
        logger.info("reconnected to %s @ %d bps", self._port, self._baudrate)

    def _send(self, frame):
        if self.dry_run:
            # INFO level (not DEBUG): the whole point of dry-run is to show
            # the frames that would be sent, so it should appear by default
            logger.info("[dry-run] -> %s", frame.hex(" "))
            return
        self._serial.write(frame)

    def _read_ack(self, cmd, ack_timeout=0.15):
        """Read the ACK frame the chip emits after any command.
        Returns True if status == 0x00 (OK), False on timeout or error."""
        if self._serial is None:
            return False
        old_timeout = self._serial.timeout
        self._serial.timeout = ack_timeout
        try:
            resp = self._serial.read(ACK_LEN)
        finally:
            self._serial.timeout = old_timeout
        if len(resp) < ACK_LEN:
            logger.debug("ACK timeout for cmd 0x%02x (%d bytes)", cmd, len(resp))
            return False
        expected = (cmd | 0x80) & 0xFF
        if resp[0] != 0x57 or resp[1] != 0xAB or resp[3] != expected:
            logger.debug("unexpected ACK: %s", resp.hex(" "))
            return False
        return resp[5] == 0x00

    def send_with_ack(self, frame, retries=2, ack_timeout=0.15):
        """Send a frame and wait for the ACK; retries up to `retries` times.

        Use for critical operations (chip_reset, configuration commands).
        For type_text in a loop keep using _send (fire-and-forget) so you do
        not add ~150ms of latency per key.

        Returns True if the chip confirmed OK.
        """
        if self.dry_run:
            logger.info("[dry-run] -> %s", frame.hex(" "))
            return True
        cmd = frame[3]
        for attempt in range(retries):
            self._serial.reset_input_buffer()
            self._serial.write(frame)
            if self._read_ack(cmd, ack_timeout=ack_timeout):
                return True
            logger.warning("missing ACK for cmd 0x%02x (attempt %d/%d)",
                           cmd, attempt + 1, retries)
        return False

    def chip_reset(self):
        """Send CMD_RESET (0x0F): restores the chip's default configuration."""
        frame = build_frame(CMD_RESET, [], addr=self.addr)
        if self.dry_run:
            logger.info("[dry-run] chip_reset -> %s", frame.hex(" "))
            return
        self._serial.reset_input_buffer()
        self._serial.write(frame)
        time.sleep(0.1)  # wait for the chip to reinitialize
        self._serial.reset_input_buffer()
        logger.info("chip_reset sent")

    def get_info(self):
        """Send CMD_GET_INFO (0x01) and return the raw response frame.
        Returns bytes, or None on dry-run/timeout."""
        frame = build_frame(CMD_GET_INFO, [], addr=self.addr)
        if self.dry_run:
            logger.info("[dry-run] get_info -> %s", frame.hex(" "))
            return None
        self._serial.reset_input_buffer()
        self._serial.write(frame)
        old_timeout = self._serial.timeout
        self._serial.timeout = 0.5
        try:
            resp = self._serial.read(64)
        finally:
            self._serial.timeout = old_timeout
        return resp if resp else None

    def lock_state(self):
        """State of the keyboard lights on the TARGET (num/caps/scroll).

        In dry-run it returns None. Otherwise, any invalid response raises
        ValueError via parse_info -- see there for why."""
        resp = self.get_info()
        if resp is None and self.dry_run:
            return None
        return parse_info(resp)

    def move_absolute(self, x, y, screen_w, screen_h, buttons=0, wheel=0):
        self._send(build_mouse_absolute_frame(x, y, screen_w, screen_h, buttons, wheel, self.addr))

    def move_relative(self, dx, dy, buttons=0, wheel=0):
        self._send(build_mouse_relative_frame(dx, dy, buttons, wheel, self.addr))

    def click_absolute(self, x, y, screen_w, screen_h, button=BUTTON_LEFT):
        self.move_absolute(x, y, screen_w, screen_h, buttons=button)
        self.move_absolute(x, y, screen_w, screen_h, buttons=0)

    def release_all_keys(self):
        """Send an empty keyboard frame: release any stuck key/modifier.

        Idempotent and cheap. Use after reconnecting or when suspecting a
        stuck key (classic symptom: typed letters turn into shortcuts, e.g.
        Windows Search opening on its own in the middle of a text via
        `Win+s`).
        """
        self._send(build_keyboard_frame(0, [], self.addr))

    def key_press(self, keycode, modifier=0, hold_seconds=0.0):
        self._send(build_keyboard_frame(modifier, [keycode], self.addr))
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        self._send(build_keyboard_frame(0, [], self.addr))

    def press_named_key(self, name, modifier=0):
        usage_id = named_key_to_usage(name)
        if usage_id is None:
            raise ValueError(f"unknown named key: {name}")
        self.key_press(usage_id, modifier)

    def type_text(self, text, char_delay=0.03, allow_unverified=False):
        """Type `text` key by key.

        char_delay default 0.03s = the useful floor of this link. Each key
        event is 2 frames of 14 bytes; at 9600 8N1 that is ~29ms of serial
        line, so asking for less does not speed it up and in practice slows
        it down (the driver buffer fills and the write blocks). Above the
        floor the delay rules: 0.05 requested measures 49.8ms/event, 0.15
        measures 148.8ms/event. Use high values (~0.15) only where there is
        bot anti-detection to consider, such as messaging apps.

        `allow_unverified` enables the characters in
        hid_keycodes.UNVERIFIED_CHARS, whose usage is deduced from the ABNT2
        layout but was never read back on screen. It exists for the probe
        (probe_punctuation.py): in a real batch, typing an unmeasured usage
        corrupts silently.
        """
        for index, char in enumerate(text):
            seq = char_to_sequence(char, allow_unverified=allow_unverified)
            if seq is None:
                raise ValueError(f"character with no HID mapping: {char!r}")
            # An accented char = 2 events (dead key + vowel), and a literal
            # dead key = dead key + space. The char_delay between them is
            # essential: without the gap the dead key does not "arm".
            try:
                for usage_id, modifier in seq:
                    self.key_press(usage_id, modifier)
                    if char_delay > 0:
                        time.sleep(char_delay)
            except serial.SerialException as exc:
                # Report HOW MANY characters already went out, so whoever
                # retries resends only the rest. Resending the whole string
                # concatenates with what is already in the field -- that is
                # what once turned a correct password into a wrong one.
                raise PartialTypeError(index, text, exc) from exc
