import ch9329
import remote_control


def test_key_to_hid_printable_chars():
    assert remote_control.key_to_hid(ord("a")) == ("char", "a")
    assert remote_control.key_to_hid(ord("Q")) == ("char", "Q")
    assert remote_control.key_to_hid(ord("=")) == ("char", "=")
    assert remote_control.key_to_hid(ord(" ")) == ("char", " ")


def test_key_to_hid_control_chars_become_named_keys():
    assert remote_control.key_to_hid(13) == ("named", "enter")
    assert remote_control.key_to_hid(10) == ("named", "enter")
    assert remote_control.key_to_hid(8) == ("named", "backspace")
    assert remote_control.key_to_hid(9) == ("named", "tab")


def test_key_to_hid_arrow_keys_waitkeyex_windows():
    assert remote_control.key_to_hid(0x250000) == ("named", "left")
    assert remote_control.key_to_hid(0x260000) == ("named", "up")
    assert remote_control.key_to_hid(0x270000) == ("named", "right")
    assert remote_control.key_to_hid(0x280000) == ("named", "down")


def test_key_to_hid_ignores_no_key_and_unknown():
    assert remote_control.key_to_hid(-1) is None
    assert remote_control.key_to_hid(None) is None
    assert remote_control.key_to_hid(0x999999) is None
    # ESC is not forwarded (reserved for quitting the window)
    assert remote_control.key_to_hid(27) is None


def _controller_with_recorder():
    controller = ch9329.CH9329Controller(port=None, dry_run=True)
    sent = []
    controller._send = sent.append
    return controller, sent


def test_forward_key_sends_press_and_release():
    controller, sent = _controller_with_recorder()
    assert remote_control.forward_key(controller, ord("a")) is True
    assert len(sent) == 2  # press + release
    assert sent[0][7] == 0x04  # usage of "a"
    assert sent[1][7] == 0x00  # release


def test_forward_key_named_enter():
    controller, sent = _controller_with_recorder()
    assert remote_control.forward_key(controller, 13) is True
    assert sent[0][7] == 0x28  # usage of enter


def test_forward_key_unknown_sends_nothing():
    controller, sent = _controller_with_recorder()
    assert remote_control.forward_key(controller, -1) is False
    assert remote_control.forward_key(controller, 0x999999) is False
    assert sent == []
