# -*- coding: utf-8 -*-
import pytest

import ch9329
import hid_keycodes


def test_checksum_is_sum_mod_256():
    assert ch9329.checksum([0x57, 0xAB, 0x00, 0x02, 0x01, 0xFF]) == sum([0x57, 0xAB, 0x00, 0x02, 0x01, 0xFF]) % 256


def test_build_frame_layout_and_checksum():
    frame = ch9329.build_frame(cmd=0x02, data=[1, 2, 3], addr=0x00)
    body = [0x57, 0xAB, 0x00, 0x02, 3, 1, 2, 3]
    assert frame == bytes(body + [sum(body) % 256])


def test_clamp_signed_byte_roundtrips_full_range():
    assert ch9329.clamp_signed_byte(0) == 0
    assert ch9329.clamp_signed_byte(127) == 127
    assert ch9329.clamp_signed_byte(-127) == 256 - 127


def test_clamp_signed_byte_clamps_out_of_range():
    assert ch9329.clamp_signed_byte(200) == 127
    assert ch9329.clamp_signed_byte(-200) == 256 - 127


def test_scale_to_abs_negative_pixel_clamps_to_zero():
    # regression: scale_to_abs must no longer "wrap" negative pixels to the
    # opposite end of the absolute range (bug fixed)
    assert ch9329.scale_to_abs(-5, 1920) == 0
    assert ch9329.scale_to_abs(-1, 1920) == 0


def test_scale_to_abs_proportional_mapping():
    assert ch9329.scale_to_abs(0, 1920) == 0
    assert ch9329.scale_to_abs(960, 1920) == 2048


def test_scale_to_abs_clamps_upper_bound():
    assert ch9329.scale_to_abs(1919, 1920) == int((ch9329.ABS_RANGE * 1919) / 1920)
    assert ch9329.scale_to_abs(5000, 1920) == ch9329.ABS_RANGE - 1


def test_build_mouse_absolute_frame_marker_and_command():
    frame = ch9329.build_mouse_absolute_frame(100, 200, 1920, 1080, buttons=ch9329.BUTTON_LEFT)
    assert frame[3] == ch9329.CMD_MOUSE_ABS
    assert frame[5] == ch9329.ABS_MARKER
    assert frame[6] == ch9329.BUTTON_LEFT


def test_build_mouse_relative_frame_marker_and_command():
    frame = ch9329.build_mouse_relative_frame(10, -10, buttons=0)
    assert frame[3] == ch9329.CMD_MOUSE_REL
    assert frame[5] == ch9329.REL_MARKER
    assert frame[6] == 0  # buttons
    assert frame[7] == ch9329.clamp_signed_byte(10)
    assert frame[8] == ch9329.clamp_signed_byte(-10)


def test_build_keyboard_frame_pads_keys_to_six():
    frame = ch9329.build_keyboard_frame(modifier=ch9329.HEAD[0], keycodes=[0x04, 0x05])
    assert frame[3] == ch9329.CMD_KEYBOARD
    assert frame[4] == 8  # len(data): modifier + reserved + 6 keycodes
    keys = list(frame[7:13])
    assert keys == [0x04, 0x05, 0, 0, 0, 0]


def test_click_absolute_sends_button_down_then_up():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    controller.click_absolute(100, 100, 1920, 1080, button=ch9329.BUTTON_LEFT)

    assert len(sent) == 2
    assert sent[0][6] == ch9329.BUTTON_LEFT
    assert sent[1][6] == 0


def test_press_named_key_unknown_raises():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    with pytest.raises(ValueError):
        controller.press_named_key("not-a-real-key")


def test_type_text_unmapped_char_raises():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    with pytest.raises(ValueError):
        controller.type_text("€")  # not in CHAR_TABLE


def test_type_text_cedilla_now_mapped_abnt2():
    # regression: "ç" is now mapped (usage 0x33 in the ABNT2 layout)
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    controller.type_text("ç", char_delay=0)

    assert len(sent) == 2  # press + release
    assert sent[0][7] == 0x33  # first keycode of the report


class TestPartialTypeError:
    """A serial failure in the middle of type_text must say where it stopped.

    Regression for the bug that turned a correct password into a wrong one:
    the retry resent the whole string and concatenated it with what was
    already in the field (see docs/SCREEN_UNLOCK.md section 4).
    """

    def _controller_that_fails_at(self, limit):
        import serial as _serial
        from ch9329 import CH9329Controller

        ctrl = CH9329Controller.__new__(CH9329Controller)
        ctrl.dry_run = False
        ctrl.addr = 0x00
        sent = []

        def fake_send(frame):
            # count only the keydown (keyup comes with modifier/keycode zeroed)
            if frame[5] != 0x00 or frame[7] != 0x00:
                if len(sent) >= limit:
                    raise _serial.SerialException("WriteFile failed")
                sent.append(frame)

        ctrl._send = fake_send
        return ctrl, sent

    def test_reports_how_many_chars_went_out(self):
        from ch9329 import PartialTypeError

        ctrl, _ = self._controller_that_fails_at(3)
        with pytest.raises(PartialTypeError) as info:
            ctrl.type_text("abcdef", char_delay=0)
        assert info.value.typed == 3
        assert info.value.remaining == "def"

    def test_remaining_does_not_reinclude_what_was_typed(self):
        from ch9329 import PartialTypeError

        ctrl, _ = self._controller_that_fails_at(4)
        with pytest.raises(PartialTypeError) as info:
            ctrl.type_text("Senha@1234!", char_delay=0)
        # the retry must send ONLY the rest; concatenating the whole was the bug
        assert info.value.text == "Senha@1234!"
        assert "Senha@1234!".startswith(
            "Senha@1234!"[: info.value.typed])
        assert info.value.remaining == "Senha@1234!"[info.value.typed:]
        assert info.value.remaining != "Senha@1234!"

    def test_accented_counts_as_one_char(self):
        from ch9329 import PartialTypeError

        # 'a' = 1 event, 'á' = 2 events (dead key + vowel)
        ctrl, _ = self._controller_that_fails_at(3)
        with pytest.raises(PartialTypeError) as info:
            ctrl.type_text("aáx", char_delay=0)
        # 'a'(1) + 'á'(2) = 3 events ok, fails when starting the 'x'
        assert info.value.typed == 2
        assert info.value.remaining == "x"


class TestReleaseAllKeys:
    """A key stuck after a serial failure becomes an accidental shortcut.

    If the failure lands between keydown and keyup, the chip holds the key.
    A stuck modifier (Ctrl/Win) turns the following letters into shortcuts --
    observed symptom: Windows Search opening on its own in the middle of a text.
    """

    def test_sends_empty_keyboard_frame(self):
        from ch9329 import CH9329Controller, build_keyboard_frame

        ctrl = CH9329Controller.__new__(CH9329Controller)
        ctrl.dry_run = False
        ctrl.addr = 0x00
        sent = []
        ctrl._send = sent.append

        ctrl.release_all_keys()

        assert sent == [build_keyboard_frame(0, [], 0x00)]
        # no modifier and no keycode
        assert sent[0][5] == 0x00
        assert sent[0][7] == 0x00


def test_type_text_refuses_unmeasured_char_before_sending(monkeypatch):
    """The gate must close at the door of type_text, not after.

    "[" used to sit at usage 0x2F, which on ABNT2 is the acute accent:
    typing "[A" produced "Á" and the batch kept reporting success. Today "["
    has already been measured, so it is re-injected as unmeasured: the test
    is about the gate, not the list.
    """
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset("["))
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    with pytest.raises(hid_keycodes.UnverifiedMapping):
        controller.type_text("a[b", char_delay=0)

    # the "a" may have gone out (validation is per character), but no event
    # of the suspect character was sent
    assert len(sent) == 2  # only the press+release of "a"


def test_type_text_allow_unverified_enables_the_probe(monkeypatch):
    # "^" has already been measured (probe of 2026-11-07), so the unmeasured
    # one is injected: what this test pins is the flag, not the list.
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset("^"))
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append

    controller.type_text("^", char_delay=0, allow_unverified=True)

    # dead key + space = 2 events = 4 frames
    assert len(sent) == 4


# ---------------------------------------------------------------------
# parse_info: reading the keyboard lights on the target.
#
# It exists because on 2026-11-07 a correct password was refused by Windows
# and there was NO way to see the Caps Lock state: the chip accepts the key,
# the target turns the light on, and none of that showed up in the response.
# A stuck Caps Lock raises no error -- it just flips the case of every
# letter, and the symptom ("incorrect password") shows up far from the cause.
# ---------------------------------------------------------------------

def _frame_info(leds, version=0x30, usb=0x01, cmd=0x81, addr=0x00):
    body = [0x57, 0xAB, addr, cmd, 0x08, version, usb, leds, 0, 0, 0, 0, 0]
    body.append(sum(body) % 256)
    return bytes(body)


def test_parse_info_reads_caps_lock_on():
    info = ch9329.parse_info(_frame_info(ch9329.LED_CAPS_LOCK))
    assert info["caps_lock"] is True
    assert info["num_lock"] is False
    assert info["scroll_lock"] is False


def test_parse_info_separates_the_three_lights():
    """Each bit must be read in its own place. A parser that swaps num for
    caps passes a single-light test."""
    cases = [
        (ch9329.LED_NUM_LOCK, "num_lock"),
        (ch9329.LED_CAPS_LOCK, "caps_lock"),
        (ch9329.LED_SCROLL_LOCK, "scroll_lock"),
    ]
    for bit, name in cases:
        info = ch9329.parse_info(_frame_info(bit))
        lit = [k for k in ("num_lock", "caps_lock", "scroll_lock") if info[k]]
        assert lit == [name], "bit 0x%02X lit %s" % (bit, lit)


def test_parse_info_reads_all_three_together():
    info = ch9329.parse_info(_frame_info(0x07))
    assert (info["num_lock"], info["caps_lock"], info["scroll_lock"]) == (True, True, True)


def test_parse_info_no_lights():
    info = ch9329.parse_info(_frame_info(0x00))
    assert not any(info[k] for k in ("num_lock", "caps_lock", "scroll_lock"))


def test_parse_info_reads_usb_and_version():
    info = ch9329.parse_info(_frame_info(0x00, version=0x31, usb=0x00))
    assert info["version"] == 0x31
    assert info["usb_connected"] is False


@pytest.mark.parametrize("bad, reason", [
    (None, "missing response"),
    (b"", "empty response"),
    (b"\x57\xAB\x00\x81", "too short"),
    (b"\x00\x00\x00\x81\x08\x30\x01\x02\x00", "wrong header"),
    (b"\x57\xAB\x00\x82\x08\x30\x01\x02\x00", "echo of another command"),
])
def test_parse_info_refuses_invalid_response(bad, reason):
    """Invalid input must RAISE, never return everything off.

    A false "caps_lock: False" is worse than an error: it passes through
    diagnosis and clears the very cause one went to investigate."""
    with pytest.raises(ValueError):
        ch9329.parse_info(bad)
