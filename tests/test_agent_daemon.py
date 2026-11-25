# -*- coding: utf-8 -*-
import json
import os
import tempfile
import time

import pytest
import serial

import agent_daemon
import capture_frame
import hid_keycodes
import monitor2
from ch9329 import BUTTON_LEFT, BUTTON_RIGHT
from hid_keycodes import (
    MODIFIER_LEFT_CTRL,
    MODIFIER_LEFT_SHIFT,
    char_to_sequence,
    char_to_usage,
    named_key_to_usage,
)


class FakeController:
    """Fake controller that only records the high-level calls."""

    dry_run = True

    def __init__(self):
        self.calls = []
        self.closed = False

    def close(self):
        self.closed = True

    def move_absolute(self, x, y, w, h, buttons=0, wheel=0):
        self.calls.append(("move_absolute", x, y, w, h, buttons, wheel))

    def click_absolute(self, x, y, w, h, button=BUTTON_LEFT):
        self.calls.append(("click_absolute", x, y, w, h, button))

    def key_press(self, keycode, modifier=0, hold_seconds=0.0):
        self.calls.append(("key_press", keycode, modifier))

    def press_named_key(self, name, modifier=0):
        self.calls.append(("press_named_key", name, modifier))

    def type_text(self, text, char_delay=0.02, allow_unverified=False):
        # Same validation as the real CH9329Controller, via char_to_sequence:
        # with char_to_usage the fake accepted accented chars (which are two
        # events on the real one) and accepted unmeasured characters -- a test
        # could pass with text the rig refuses.
        for char in text:
            seq = char_to_sequence(char, allow_unverified=allow_unverified)
            if seq is None:
                raise ValueError(f"character with no HID mapping: {char!r}")
        self.calls.append(("type_text", text))

    def release_all_keys(self):
        # Mirrors the real CH9329Controller: the daemon calls this on the
        # connection recreated after a serial error, to release a stuck key.
        self.calls.append(("release_all_keys",))


def make_ctx(controller=None, capture_fn=None):
    controller = controller or FakeController()
    ctx = agent_daemon.DaemonContext(lambda: controller, capture_fn=capture_fn)
    return ctx, controller


# Test frames directory: NEVER a relative path. With "frames" a test that
# falls into the real ctx.capture() would save a capture of the target
# machine in the repo root -- private content, and outside .gitignore (only
# queue/frames/ is covered). It happened during a mutation test.
TEST_FRAMES_DIR = tempfile.mkdtemp(prefix="agentd_frames_")


@pytest.fixture(autouse=True)
def block_real_capture(monkeypatch):
    """No test may open the rig's capture card.

    Found in practice: once `goto` started checking the Name Box, a test that
    stubbed nothing read the REAL target screen and started depending on what
    was open on it. A test that touches hardware is not deterministic -- and,
    in a project that sends keys to another machine, it is a risk and not just
    an annoyance.

    The stub is at the CLASS level: a test that needs capture monkeypatches
    the INSTANCE (`ctx.capture_array`), which takes precedence.
    """
    def no_rig(*args, **kwargs):
        raise RuntimeError(
            "real capture blocked in tests; stub ctx.capture_array or pass "
            "capture_fn")

    monkeypatch.setattr(agent_daemon.DaemonContext, "capture_array",
                        no_rig, raising=False)


def run_steps(steps, ctx, frames_dir=TEST_FRAMES_DIR):
    return agent_daemon.execute_steps(steps, ctx, "req", frames_dir=frames_dir)


# ---------------------------------------------------------------------------
# parse_request
# ---------------------------------------------------------------------------

def test_parse_request_valid_returns_steps():
    steps = [{"action": "click", "x": 1, "y": 2}, {"action": "sleep", "seconds": 0}]
    assert agent_daemon.parse_request({"steps": steps}) == steps


@pytest.mark.parametrize(
    "data",
    [
        [1, 2, 3],                                # not an object
        {},                                       # no steps
        {"steps": []},                            # empty list
        {"steps": "click"},                       # not a list
        {"steps": [42]},                          # step is not an object
        {"steps": [{"x": 1}]},                    # step with no action
        {"steps": [{"action": "teleport"}]},      # unknown action
    ],
)
def test_parse_request_invalid_raises(data):
    with pytest.raises(ValueError):
        agent_daemon.parse_request(data)


# ---------------------------------------------------------------------------
# key and modifier resolution
# ---------------------------------------------------------------------------

def test_resolve_modifiers_combines_bits():
    assert agent_daemon.resolve_modifiers(["ctrl", "shift"]) == (
        MODIFIER_LEFT_CTRL | MODIFIER_LEFT_SHIFT
    )
    assert agent_daemon.resolve_modifiers(None) == 0
    assert agent_daemon.resolve_modifiers([]) == 0


def test_resolve_modifiers_unknown_raises():
    with pytest.raises(ValueError):
        agent_daemon.resolve_modifiers(["hyper"])


def test_resolve_key_named_and_char():
    assert agent_daemon.resolve_key("enter") == (named_key_to_usage("enter"), 0)
    assert agent_daemon.resolve_key("b") == (0x05, 0)
    # an uppercase carries the shift required by the character itself
    assert agent_daemon.resolve_key("B") == (0x05, MODIFIER_LEFT_SHIFT)


@pytest.mark.parametrize("key", ["notakey", "", None, "€"])
def test_resolve_key_unknown_raises(key):
    with pytest.raises(ValueError):
        agent_daemon.resolve_key(key)


# ---------------------------------------------------------------------------
# dispatch of each action
# ---------------------------------------------------------------------------

def test_click_maps_to_monitor2_virtual_coords():
    ctx, fake = make_ctx()
    ok, results = run_steps([{"action": "click", "x": 100, "y": 200, "button": "right"}], ctx)

    vx, vy = monitor2.to_virtual(100, 200)
    assert ok
    assert results[0]["status"] == "ok"
    assert fake.calls == [
        ("click_absolute", vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, BUTTON_RIGHT)
    ]


def test_click_default_button_is_left():
    ctx, fake = make_ctx()
    run_steps([{"action": "click", "x": 0, "y": 0}], ctx)
    assert fake.calls[0][-1] == BUTTON_LEFT


def test_click_unknown_button_is_step_error():
    ctx, fake = make_ctx()
    ok, results = run_steps([{"action": "click", "x": 0, "y": 0, "button": "quadruple"}], ctx)
    assert not ok
    assert results[0]["status"] == "error"
    assert fake.calls == []


def test_move_maps_to_monitor2_virtual_coords():
    ctx, fake = make_ctx()
    run_steps([{"action": "move", "x": 10, "y": 20}], ctx)

    vx, vy = monitor2.to_virtual(10, 20)
    assert fake.calls == [("move_absolute", vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, 0, 0)]


def test_move_missing_coordinate_is_step_error():
    ctx, fake = make_ctx()
    ok, results = run_steps([{"action": "move", "x": 10}], ctx)
    assert not ok
    assert "y" in results[0]["error"]


def test_scroll_sends_wheel_and_clamps():
    ctx, fake = make_ctx()
    run_steps([{"action": "scroll", "amount": -500, "x": 5, "y": 6}], ctx)

    vx, vy = monitor2.to_virtual(5, 6)
    assert fake.calls == [("move_absolute", vx, vy, monitor2.VIRTUAL_W, monitor2.VIRTUAL_H, 0, -127)]


def test_scroll_defaults_to_monitor_center():
    ctx, fake = make_ctx()
    run_steps([{"action": "scroll", "amount": 3}], ctx)

    vx, vy = monitor2.to_virtual(monitor2.MON2_W // 2, monitor2.MON2_H // 2)
    assert fake.calls[0][1:3] == (vx, vy)


def test_type_text_forwards_text():
    ctx, fake = make_ctx()
    ok, _ = run_steps([{"action": "type_text", "text": "=SUM(A1:A10)\n"}], ctx)
    assert ok
    assert fake.calls == [("type_text", "=SUM(A1:A10)\n")]


def test_press_key_named():
    ctx, fake = make_ctx()
    run_steps([{"action": "press_key", "key": "enter"}], ctx)
    assert fake.calls == [("key_press", named_key_to_usage("enter"), 0)]


def test_key_combo_ctrl_b():
    ctx, fake = make_ctx()
    run_steps([{"action": "key_combo", "key": "b", "modifiers": ["ctrl"]}], ctx)
    assert fake.calls == [("key_press", 0x05, MODIFIER_LEFT_CTRL)]


def test_key_combo_uppercase_keeps_char_shift():
    ctx, fake = make_ctx()
    run_steps([{"action": "key_combo", "key": "B", "modifiers": ["ctrl"]}], ctx)
    assert fake.calls == [("key_press", 0x05, MODIFIER_LEFT_CTRL | MODIFIER_LEFT_SHIFT)]


def test_goto_sends_f5_ref_enter_in_order(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    ctx, fake = make_ctx()
    ok, _ = run_steps([{"action": "goto", "ref": "A1:C10"}], ctx)

    assert ok
    assert fake.calls == [
        ("press_named_key", "f5", 0),
        ("type_text", "A1:C10"),
        ("press_named_key", "enter", 0),
    ]


def test_sleep_clamps_to_max(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    ctx, _ = make_ctx()
    ok, _ = run_steps([{"action": "sleep", "seconds": 9999}], ctx)
    assert ok
    assert slept == [agent_daemon.MAX_SLEEP_SECONDS]


def test_sleep_negative_is_step_error():
    ctx, _ = make_ctx()
    ok, results = run_steps([{"action": "sleep", "seconds": -1}], ctx)
    assert not ok
    assert results[0]["status"] == "error"


def test_capture_frame_uses_default_name_and_reports_path(tmp_path):
    captured = []

    def fake_capture(path):
        captured.append(path)
        return path

    ctx, _ = make_ctx(capture_fn=fake_capture)
    ok, results = agent_daemon.execute_steps(
        [{"action": "capture_frame"}], ctx, "007_test", frames_dir=str(tmp_path)
    )

    expected = os.path.join(str(tmp_path), "007_test_step0.png")
    assert ok
    assert captured == [expected]
    assert results[0]["frame_path"] == expected


def test_capture_frame_custom_relative_path_lands_in_frames_dir(tmp_path):
    captured = []
    ctx, _ = make_ctx(capture_fn=lambda p: captured.append(p) or p)
    agent_daemon.execute_steps(
        [{"action": "capture_frame", "path": "excel.png"}], ctx, "req", frames_dir=str(tmp_path)
    )
    assert captured == [os.path.join(str(tmp_path), "excel.png")]


# ---------------------------------------------------------------------------
# resilience
# ---------------------------------------------------------------------------

def test_failed_step_does_not_stop_the_batch():
    ctx, fake = make_ctx()
    steps = [
        {"action": "type_text", "text": "€"},   # no HID mapping -> error
        {"action": "click", "x": 1, "y": 2},    # must run anyway
    ]
    ok, results = run_steps(steps, ctx)

    assert not ok
    assert results[0]["status"] == "error"
    assert "mapping" in results[0]["error"]
    assert results[1]["status"] == "ok"
    assert fake.calls[-1][0] == "click_absolute"


class SerialFlakyController(FakeController):
    """Fails with SerialException on the first N click calls."""

    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def click_absolute(self, x, y, w, h, button=BUTTON_LEFT):
        if self.failures > 0:
            self.failures -= 1
            raise serial.SerialException("port dropped")
        super().click_absolute(x, y, w, h, button)


def test_serial_error_reconnects_and_retries_step():
    controllers = [SerialFlakyController(failures=1), FakeController()]
    created = []

    def factory():
        created.append(controllers.pop(0))
        return created[-1]

    ctx = agent_daemon.DaemonContext(factory)
    ok, results = run_steps([{"action": "click", "x": 1, "y": 1}], ctx)

    assert ok
    assert results[0]["status"] == "ok"
    assert len(created) == 2                      # reconnected
    assert created[0].closed                      # the errored connection was closed
    # the new connection releases stuck keys BEFORE redoing the action
    actions = [c[0] for c in created[1].calls]
    assert actions[0] == "release_all_keys"
    assert "click_absolute" in actions


def test_serial_error_twice_reports_error_and_next_step_reconnects():
    controllers = [
        SerialFlakyController(failures=5),
        SerialFlakyController(failures=5),
        FakeController(),
    ]
    created = []

    def factory():
        created.append(controllers.pop(0))
        return created[-1]

    ctx = agent_daemon.DaemonContext(factory)
    steps = [
        {"action": "click", "x": 1, "y": 1},   # fails 2x -> error
        {"action": "click", "x": 2, "y": 2},   # reconnects again -> ok
    ]
    ok, results = run_steps(steps, ctx)

    assert not ok
    assert results[0]["status"] == "error"
    assert "SerialException" in results[0]["error"]
    assert results[1]["status"] == "ok"
    assert len(created) == 3


def test_reconnect_releases_stuck_keys_but_the_first_connection_does_not():
    """LEARNINGS 0b: a serial failure between keydown and keyup leaves a key
    (maybe a modifier) stuck in the chip, and a stuck Ctrl/Win turns the
    following letters into shortcuts. reconnect() releases everything -- but
    the daemon reconnects by RECREATING the controller (drop + factory), not
    by calling reconnect(); that is why the release lives in the recreation
    path. The 1st connection releases nothing (there is no stuck key); only
    the reconnect releases."""
    controllers = [SerialFlakyController(failures=1), FakeController()]
    created = []

    def factory():
        created.append(controllers.pop(0))
        return created[-1]

    ctx = agent_daemon.DaemonContext(factory)
    first = ctx.controller()
    assert first.calls == []                           # 1st connection: nothing to release

    ok, _ = run_steps([{"action": "click", "x": 1, "y": 1}], ctx)
    assert ok
    assert len(created) == 2
    assert created[1].calls[0] == ("release_all_keys",)   # releases on reconnect
    assert created[1].calls[1][0] == "click_absolute"     # then redoes the action


def test_controller_factory_failure_is_step_error_not_crash():
    def factory():
        raise RuntimeError("CH340 not found")

    ctx = agent_daemon.DaemonContext(factory)
    ok, results = run_steps([{"action": "click", "x": 1, "y": 1}], ctx)

    assert not ok
    assert results[0]["status"] == "error"
    assert "CH340" in results[0]["error"]


# ---------------------------------------------------------------------------
# file queue / response generation
# ---------------------------------------------------------------------------

def make_queue(tmp_path):
    queue_dir = tmp_path / "queue"
    return agent_daemon.ensure_queue_dirs(str(queue_dir))


def test_process_request_file_writes_response_and_moves_request(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "001_hi.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [{"action": "type_text", "text": "hi"}]}, f)

    ctx, fake = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed
    assert not os.path.exists(request_path)
    assert os.path.exists(os.path.join(processed_dir, "001_hi.json"))

    with open(os.path.join(responses_dir, "001_hi.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["request"] == "001_hi.json"
    assert response["ok"] is True
    assert response["steps"] == [{"index": 0, "action": "type_text", "status": "ok"}]
    assert fake.calls == [("type_text", "hi")]


def test_process_request_file_reports_per_step_errors(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "002_mixed.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(
            {"steps": [{"action": "type_text", "text": "€"}, {"action": "move", "x": 1, "y": 1}]}, f
        )

    ctx, _ = make_ctx()
    agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    with open(os.path.join(responses_dir, "002_mixed.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["ok"] is False
    assert response["steps"][0]["status"] == "error"
    assert response["steps"][1]["status"] == "ok"


def test_recent_malformed_request_is_skipped_not_consumed(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "003_partial.json")
    with open(request_path, "w", encoding="utf-8") as f:
        f.write('{"steps": [')  # half-written

    ctx, _ = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed is False
    assert os.path.exists(request_path)  # stays for the next scan
    assert not os.path.exists(os.path.join(responses_dir, "003_partial.json"))


def test_old_malformed_request_gets_error_response(tmp_path):
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "004_garbage.json")
    with open(request_path, "w", encoding="utf-8") as f:
        f.write("{not json")
    old = time.time() - 60
    os.utime(request_path, (old, old))

    ctx, _ = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed
    assert not os.path.exists(request_path)
    with open(os.path.join(responses_dir, "004_garbage.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["ok"] is False
    assert "invalid request" in response["error"]


def test_invalid_schema_gets_error_response_even_if_recent(tmp_path):
    # well-formed JSON but with a wrong schema gets no tolerance window
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "005_schema.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [{"action": "teleport"}]}, f)

    ctx, _ = make_ctx()
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir=frames_dir
    )

    assert consumed
    with open(os.path.join(responses_dir, "005_schema.json"), encoding="utf-8") as f:
        response = json.load(f)
    assert response["ok"] is False
    assert "teleport" in response["error"]


def test_pending_requests_sorted_and_filtered(tmp_path):
    requests_dir, _, _, _, _, _ = make_queue(tmp_path)
    for name in ("002_b.json", "001_a.json", "note.txt", "_draft.json", ".hidden.json"):
        with open(os.path.join(requests_dir, name), "w", encoding="utf-8") as f:
            f.write("{}")

    pending = agent_daemon.pending_requests(requests_dir)
    assert [os.path.basename(p) for p in pending] == ["001_a.json", "002_b.json"]


def test_main_loop_processes_request_and_stops_on_sentinel(tmp_path):
    queue_dir = str(tmp_path / "queue")
    requests_dir, responses_dir, _, _, _, _ = agent_daemon.ensure_queue_dirs(queue_dir)
    with open(os.path.join(requests_dir, "001_x.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": [{"action": "press_key", "key": "enter"}]}, f)
    open(os.path.join(queue_dir, "stop"), "w").close()

    ctx, fake = make_ctx()
    agent_daemon.main_loop(ctx, queue_dir=queue_dir, poll_interval=0)

    assert not os.path.exists(os.path.join(queue_dir, "stop"))
    assert os.path.exists(os.path.join(responses_dir, "001_x.json"))
    assert fake.calls == [("key_press", named_key_to_usage("enter"), 0)]


# ---------------------------------------------------------------------------
# expect + required (batch abort)
# ---------------------------------------------------------------------------

class FakeScreen:
    """Stub of screen_utils for the expect tests.

    `template_results` / `ocr_results` are queues: with more than one item,
    each probe consumes the next (lets you simulate "the condition appears on
    the second attempt"); with a single item, it is returned indefinitely.
    """

    def __init__(self, template_results=None, ocr_results=None):
        self.template_results = list(template_results or [])
        self.ocr_results = list(ocr_results or [])
        self.template_calls = []
        self.ocr_calls = []
        self.ocr_upscales = []

    @staticmethod
    def _next(queue, fallback):
        if not queue:
            return fallback
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def find_image_in_frame(self, frame, path, confidence=0.85):
        self.template_calls.append((path, confidence))
        return self._next(self.template_results,
                          {"found": False, "confidence": 0.1})

    def ocr_region_from_frame(self, frame, region=None, lang="por", upscale=2):
        # `upscale` joined on 2026-11-07: expect/verify try several scales,
        # because short text does not come out at 2x ("FCFF" -> "Gigg").
        self.ocr_calls.append((region, lang))
        self.ocr_upscales.append(upscale)
        return self._next(self.ocr_results, {"text": "", "raw": ""})


def make_expect_ctx(monkeypatch, screen, controller=None):
    """ctx whose capture_array returns a fake frame, with screen_utils swapped
    for the stub."""
    ctx, fake = make_ctx(controller=controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame",
                        screen.find_image_in_frame)
    monkeypatch.setattr(agent_daemon.screen_utils, "ocr_region_from_frame",
                        screen.ocr_region_from_frame)
    return ctx, fake


def test_expect_rechecks_instead_of_reading_only_once(monkeypatch):
    """The default was ONE read at t=0, and that does not work here.

    The capture device serves an old frame (docs/CAPTURE_VIDEO_BUFFER.md).
    The real case: right after typing "PROBE ABNT2" in Notepad the expect read
    an empty string and aborted the batch -- the text was on screen, and OCR
    of the same crop read it correctly right after.

    The stub queue hands "not yet" and then "it appeared". There are three
    empties because each attempt sweeps scales 2, 4 and 6: the queue must
    drain the WHOLE attempt before the text appears, otherwise the test would
    pass with no second attempt at all.
    """
    screen = FakeScreen(ocr_results=[{"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "ready", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "ready", "poll": 0.01},
    ], ctx)

    assert ok is True
    assert results[0]["attempts"] >= 2


def test_expect_with_explicit_zero_timeout_reads_only_once(monkeypatch):
    # whoever wants the old behavior can still ask for it
    screen = FakeScreen(ocr_results=[{"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "", "raw": ""},
                                     {"text": "ready", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "ready", "timeout": 0},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"


def test_expect_default_is_not_zero():
    # the value itself is a choice; being greater than zero is not
    assert agent_daemon.EXPECT_TIMEOUT_DEFAULT > 0


def test_expect_template_found_lets_batch_continue(monkeypatch):
    screen = FakeScreen(template_results=[{"found": True, "x": 10, "y": 20,
                                           "confidence": 0.97}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "box.png"},
        {"action": "type_text", "text": "hi"},
    ], ctx)

    assert ok is True
    assert results[0]["status"] == "ok"
    assert results[0]["expect_ok"] is True
    assert results[1]["status"] == "ok"
    assert ("type_text", "hi") in fake.calls


def test_expect_template_missing_aborts_and_does_not_type(monkeypatch):
    """The incident scenario: the screen is not the expected one, so NOTHING is typed."""
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.12}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "whatsapp_box.png"},
        {"action": "type_text", "text": "secret message"},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert "ExpectationFailed" in results[0]["error"]
    assert results[0]["aborted_batch"] is True
    # the essential part: the write steps did not even run
    assert results[1]["status"] == "skipped"
    assert results[2]["status"] == "skipped"
    assert "aborted at step 0" in results[1]["reason"]
    assert fake.calls == []


def test_expect_reports_best_confidence_in_error(monkeypatch):
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.4231}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    _, results = run_steps([{"action": "expect", "template": "x.png"}], ctx)
    assert "0.4231" in results[0]["error"]


def test_expect_absent_satisfied_when_not_found(monkeypatch):
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.1}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "template": "lock_screen.png", "absent": True},
        {"action": "type_text", "text": "ok"},
    ], ctx)

    assert ok is True
    assert ("type_text", "ok") in fake.calls


def test_expect_absent_aborts_when_present(monkeypatch):
    """Direct guard against the incident: the lock screen is on screen."""
    screen = FakeScreen(template_results=[{"found": True, "x": 1, "y": 2,
                                           "confidence": 0.99}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "lock_screen.png", "absent": True},
        {"action": "type_text", "text": "Senha@1234!"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


def test_expect_retries_until_condition_appears(monkeypatch):
    screen = FakeScreen(template_results=[
        {"found": False, "confidence": 0.2},
        {"found": True, "x": 5, "y": 6, "confidence": 0.9},
    ])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    monkeypatch.setattr(agent_daemon.time, "sleep", lambda s: None)

    ok, results = run_steps([
        {"action": "expect", "template": "a.png", "timeout": 5, "poll": 0.1},
    ], ctx)

    assert ok is True
    assert results[0]["attempts"] == 2


def test_expect_required_false_records_but_does_not_abort(monkeypatch):
    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.1}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "template": "a.png", "required": False},
        {"action": "type_text", "text": "go on"},
    ], ctx)

    assert ok is False                      # the failure is recorded
    assert "aborted_batch" not in results[0]
    assert results[1]["status"] == "ok"     # but the batch went on
    assert ("type_text", "go on") in fake.calls


def test_expect_text_backend_matches_substring(monkeypatch):
    screen = FakeScreen(ocr_results=[{"text": "Type a message", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "type a", "region": [0, 0, 100, 50]},
    ], ctx)

    assert ok is True
    # lang=None on purpose: the language is chosen by
    # screen_utils.resolve_lang, from what is INSTALLED. Hardcoding "por"
    # here was what made every expect without an explicit lang die on this
    # machine, which only has the `eng` package.
    assert screen.ocr_calls == [([0, 0, 100, 50], None)]


def test_expect_text_without_tesseract_gives_actionable_error(monkeypatch):
    """pytesseract importable but the binary absent must not become 'not found'."""
    def boom(frame, region=None, lang="por"):
        raise RuntimeError("TesseractNotFoundError: tesseract is not installed")

    screen = FakeScreen()
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    monkeypatch.setattr(agent_daemon.screen_utils, "ocr_region_from_frame", boom)

    ok, results = run_steps([
        {"action": "expect", "text": "anything"},
        {"action": "type_text", "text": "must not type"},
    ], ctx)

    assert ok is False
    assert "Tesseract-OCR installed" in results[0]["error"]
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


def test_expect_does_not_require_serial_connection(monkeypatch):
    """expect only looks at the screen: it must not open the serial nor fail without it."""
    screen = FakeScreen(template_results=[{"found": True, "x": 1, "y": 1,
                                           "confidence": 0.9}])

    def exploding_factory():
        raise AssertionError("expect should not ask for the controller")

    ctx = agent_daemon.DaemonContext(exploding_factory)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame",
                        screen.find_image_in_frame)

    ok, _ = run_steps([{"action": "expect", "template": "a.png"}], ctx)
    assert ok is True


def test_required_true_aborts_on_any_action():
    ctx, fake = make_ctx()
    ok, results = run_steps([
        {"action": "type_text", "text": "€", "required": True},  # no mapping
        {"action": "type_text", "text": "after"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


def test_step_is_required_defaults():
    assert agent_daemon.step_is_required({"action": "expect"}) is True
    assert agent_daemon.step_is_required({"action": "type_text"}) is False
    assert agent_daemon.step_is_required(
        {"action": "expect", "required": False}) is False
    assert agent_daemon.step_is_required(
        {"action": "click", "required": True}) is True


@pytest.mark.parametrize("step, expected", [
    ({"action": "expect"}, "template"),
    ({"action": "expect", "template": "a.png", "text": "x"}, "not both"),
    ({"action": "click", "x": 1, "y": 2, "required": "sim"}, "'required'"),
])
def test_parse_request_validates_expect_and_required(step, expected):
    with pytest.raises(ValueError) as excinfo:
        agent_daemon.parse_request({"steps": [step]})
    assert expected in str(excinfo.value)


def test_parse_request_accepts_valid_expect():
    steps = agent_daemon.parse_request({"steps": [
        {"action": "expect", "template": "a.png", "absent": True, "timeout": 3},
    ]})
    assert steps[0]["action"] == "expect"


def test_default_char_delay_is_at_serial_floor():
    """Below ~0.029s the 9600 bps line saturates and the real rate gets worse."""
    assert agent_daemon.DEFAULT_CHAR_DELAY >= 0.029


def test_response_file_records_abort_and_skipped_steps(tmp_path, monkeypatch):
    """Operator-visible contract: the response says where it aborted and what
    did not run, so there is no doubt about what reached the screen."""
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = \
        make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "001_stored.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [
            {"action": "expect", "template": "box.png"},
            {"action": "type_text", "text": "must not go out"},
        ]}, f)

    screen = FakeScreen(template_results=[{"found": False, "confidence": 0.3}])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    consumed = agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir,
        failed_dir, frames_dir=frames_dir)

    assert consumed
    with open(os.path.join(responses_dir, "001_stored.json"), encoding="utf-8") as f:
        response = json.load(f)

    assert response["ok"] is False
    assert response["steps"][0]["aborted_batch"] is True
    assert response["steps"][1]["status"] == "skipped"
    assert response["steps"][1]["reason"] == "batch aborted at step 0"
    assert fake.calls == []


# ---------------------------------------------------------------------------
# expect end-to-end: real template + real cv2.matchTemplate
# ---------------------------------------------------------------------------

TEMPLATE_WPP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "wpp_caixa_vazia.png")


def _synthetic_frame(with_template, seed=7):
    """1920x1080 frame of deterministic noise, optionally with the template
    pasted at a known position."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(seed)
    frame = rng.integers(0, 60, size=(1080, 1920, 3), dtype=numpy.uint8)
    if with_template:
        tmpl = cv2.imread(TEMPLATE_WPP)
        assert tmpl is not None, f"template missing: {TEMPLATE_WPP}"
        th, tw = tmpl.shape[:2]
        frame[970:970 + th, 1858:1858 + tw] = tmpl
    return frame


@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="versioned template missing")
def test_expect_finds_real_template_in_synthetic_frame(monkeypatch):
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(True), raising=False)

    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_caixa_vazia.png"},
        {"action": "type_text", "text": "ok"},
    ], ctx)

    assert ok is True, results
    assert results[0]["confidence"] >= 0.85
    assert ("type_text", "ok") in fake.calls


@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="versioned template missing")
def test_expect_rejects_frame_without_template(monkeypatch):
    """Wrong screen => no typing. The case the incident produced."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(False), raising=False)

    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_caixa_vazia.png"},
        {"action": "type_text", "text": "must not go out"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert fake.calls == []


TEMPLATE_JANELA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "wpp_janela.png")


@pytest.mark.skipif(not os.path.exists(TEMPLATE_JANELA),
                    reason="versioned template missing")
def test_expect_window_template_is_composer_independent(monkeypatch):
    """wpp_janela exists for phases E2+, when the box ALREADY has text and
    wpp_caixa_vazia stops matching. It must match in both cases."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(11)
    tmpl = cv2.imread(TEMPLATE_JANELA)
    assert tmpl is not None
    th, tw = tmpl.shape[:2]

    frame = rng.integers(0, 60, size=(1080, 1920, 3), dtype=numpy.uint8)
    frame[4:4 + th, 6:6 + tw] = tmpl

    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: frame, raising=False)
    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_janela.png"},
        {"action": "type_text", "text": "second paragraph"},
    ], ctx)

    assert ok is True, results
    assert results[0]["confidence"] >= 0.85
    assert ("type_text", "second paragraph") in fake.calls


@pytest.mark.skipif(not os.path.exists(TEMPLATE_JANELA),
                    reason="versioned template missing")
def test_two_templates_compose_in_one_batch(monkeypatch):
    """Phase D/E1: requires the WhatsApp window AND an empty box. If only the
    window matches (box with text), the batch must abort before typing."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(12)
    window = cv2.imread(TEMPLATE_JANELA)
    th, tw = window.shape[:2]

    # window present, microphone ABSENT => the box is not empty
    frame = rng.integers(0, 60, size=(1080, 1920, 3), dtype=numpy.uint8)
    frame[4:4 + th, 6:6 + tw] = window

    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: frame, raising=False)
    ok, results = run_steps([
        {"action": "expect", "template": "templates/wpp_janela.png"},
        {"action": "expect", "template": "templates/wpp_caixa_vazia.png"},
        {"action": "type_text", "text": "must not go out"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "ok"        # window matched
    assert results[1]["aborted_batch"] is True  # box was not empty
    assert results[2]["status"] == "skipped"
    assert fake.calls == []


# ---------------------------------------------------------------------------
# keep-alive
# ---------------------------------------------------------------------------

class FakeClock:
    """Controllable monotonic clock, so we do not actually sleep."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class NudgeController(FakeController):
    def move_relative(self, dx, dy, buttons=0, wheel=0):
        self.calls.append(("move_relative", dx, dy))


def run_loop_ticks(ctx, tmp_path, monkeypatch, ticks, **kwargs):
    """Run main_loop for `ticks` iterations of 1s and then stop.

    Each check of the stop file counts one iteration and advances the fake
    clock by 1s; after `ticks` it returns True and the loop ends.
    """
    clock = FakeClock()
    monkeypatch.setattr(agent_daemon.time, "monotonic", clock)
    monkeypatch.setattr(agent_daemon.time, "sleep", lambda s: None)

    queue_dir = str(tmp_path / "queue")
    agent_daemon.ensure_queue_dirs(queue_dir)
    stop_path = os.path.join(queue_dir, "stop")

    real_exists = os.path.exists
    state = {"n": 0}

    def fake_exists(path):
        if path == stop_path:
            state["n"] += 1
            clock.advance(1.0)
            return state["n"] > ticks
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", fake_exists)
    agent_daemon.main_loop(ctx, queue_dir=queue_dir, poll_interval=0, **kwargs)
    return state["n"]


def nudges_of(fake):
    return [c for c in fake.calls if c[0] == "move_relative"]


def test_nudge_mouse_moves_and_returns():
    ctx, fake = make_ctx(controller=NudgeController())
    assert agent_daemon.nudge_mouse(ctx) is True
    assert fake.calls == [("move_relative", 1, 0), ("move_relative", -1, 0)]


def test_nudge_mouse_never_raises_and_drops_controller():
    """The keep-alive must never bring down the loop."""

    class Broken(NudgeController):
        def move_relative(self, dx, dy, buttons=0, wheel=0):
            raise serial.SerialException("cable dropped")

    broken = Broken()
    ctx, _ = make_ctx(controller=broken)
    ctx.controller()                       # forces creation
    assert agent_daemon.nudge_mouse(ctx) is False
    assert broken.closed is True           # connection dropped to reconnect


def test_keep_alive_nudges_when_idle(tmp_path, monkeypatch):
    ctx, fake = make_ctx(controller=NudgeController())
    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=12,
                   keep_alive_seconds=5, keep_alive_max_idle=3600)

    nudges = nudges_of(fake)
    assert len(nudges) >= 4, nudges       # 12s / 5s => >= 2 nudges (2 calls each)
    assert nudges[0] == ("move_relative", 1, 0)
    assert nudges[1] == ("move_relative", -1, 0)


def test_keep_alive_is_off_by_default(tmp_path, monkeypatch):
    """Keeping the machine unlocked gives up a protection: only with an
    explicit choice.

    The ticks must exceed KEEP_ALIVE_SECONDS, otherwise the test passes
    vacuously: with the default 120s interval, running 30 ticks would prove
    nothing (an ON default would not have fired yet either).
    """
    ctx, fake = make_ctx(controller=NudgeController())
    ticks = agent_daemon.KEEP_ALIVE_SECONDS + 10
    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=ticks)
    assert fake.calls == [], "keep-alive fired without being asked"


def test_keep_alive_expires_after_max_idle(tmp_path, monkeypatch):
    """Past the limit with no requests, it stops on its own and the screen re-locks."""
    ctx, fake = make_ctx(controller=NudgeController())
    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=40,
                   keep_alive_seconds=2, keep_alive_max_idle=10)

    nudges = nudges_of(fake)
    # Without expiry it would be ~20 nudges (40 calls) in 40 ticks. With
    # expiry at 10s, ~5 nudges (10 calls).
    assert len(nudges) <= 14, "keep-alive did not expire: %d calls" % len(nudges)
    assert len(nudges) >= 4, "keep-alive did not even run"


def test_keep_alive_does_not_fire_between_steps_of_a_request(tmp_path, monkeypatch):
    """The keep-alive lives in the loop, not in step execution: it can never
    move the mouse in the middle of typing."""
    ctx, fake = make_ctx(controller=NudgeController())
    queue_dir = str(tmp_path / "queue")
    requests_dir, _, _, _, _, _ = agent_daemon.ensure_queue_dirs(queue_dir)
    with open(os.path.join(requests_dir, "001_x.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": [
            {"action": "type_text", "text": "abc"},
            {"action": "type_text", "text": "def"},
        ]}, f)

    run_loop_ticks(ctx, tmp_path, monkeypatch, ticks=20,
                   keep_alive_seconds=1, keep_alive_max_idle=3600)

    # no mouse call between the two type_text
    kinds = [c[0] for c in fake.calls]
    first, last = kinds.index("type_text"), len(kinds) - 1 - kinds[::-1].index("type_text")
    assert "move_relative" not in kinds[first:last], fake.calls


# ---------------------------------------------------------------------------
# verify: post-condition coupled to the action
# ---------------------------------------------------------------------------

MIC_PRESENT = {"found": True, "confidence": 1.0, "x": 1858, "y": 970}
MIC_ABSENT = {"found": False, "confidence": 0.6983}


def test_verify_satisfied_lets_batch_continue(monkeypatch):
    screen = FakeScreen(template_results=[MIC_ABSENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        # typed: the microphone should have become the send arrow (be absent)
        {"action": "type_text", "text": "hi",
         "verify": {"template": "box.png", "absent": True}},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is True
    assert results[0]["verify"]["expect_ok"] is True
    assert results[1]["status"] == "ok"
    assert ("key_press", named_key_to_usage("enter"), 0) in fake.calls


def test_verify_failure_aborts_batch(monkeypatch):
    # microphone still present => the box is still empty => nothing was typed
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "type_text", "text": "hi",
         "verify": {"template": "box.png", "absent": True}},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert results[0]["verify_failed"] is True
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    # the Enter must NOT have been sent
    assert fake.calls == [("type_text", "hi")]


def test_verify_catches_enter_that_did_not_send(monkeypatch):
    """Regression for the real phase-F bug (2026-11-06).

    A send request returned ok=True and sent nothing: the `Enter` landed
    outside the compose field and the text stayed in the box. No pre-condition
    catches this -- before the Enter the screen was correct. The post-condition
    catches it: on a real send the box empties again and the microphone
    reappears (measured: 1.0000 in F2_enviada against 0.6983 in 389_digitada,
    threshold 0.85).
    """
    screen = FakeScreen(template_results=[MIC_ABSENT])  # text still in the box
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "templates/wpp_caixa_vazia.png",
                    "confidence": 0.85, "timeout": 5}},
    ], ctx)

    assert ok is False
    assert results[0]["verify_failed"] is True
    assert "0.6983" in results[0]["error"] or "0.698" in results[0]["error"]


def test_verify_required_false_does_not_abort(monkeypatch):
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "type_text", "text": "hi",
         "verify": {"template": "box.png", "absent": True, "required": False}},
        {"action": "press_key", "key": "enter"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert "aborted_batch" not in results[0]
    assert results[1]["status"] == "ok"


def test_verify_runs_after_the_action(monkeypatch):
    """The post-condition must look at the screen AFTER the key goes out."""
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    seen = []
    original = screen.find_image_in_frame

    def probe(frame, path, confidence=0.85):
        seen.append(list(fake.calls))
        return original(frame, path, confidence)

    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame", probe)
    run_steps([{"action": "type_text", "text": "hi",
                "verify": {"template": "box.png"}}], ctx)

    assert seen, "the verify did not run"
    assert ("type_text", "hi") in seen[0]


def test_verify_skipped_when_the_action_itself_failed(monkeypatch):
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        # character with no HID mapping: type_text itself raises
        {"action": "type_text", "text": "—",
         "verify": {"template": "box.png"}},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert "verify" not in results[0]
    assert "verify_failed" not in results[0]
    assert screen.template_calls == []


def test_verify_absent_false_wants_the_template_present(monkeypatch):
    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "box.png"}},
    ], ctx)

    assert ok is True
    assert results[0]["verify"]["expect_ok"] is True


# ---------------------------------------------------------------------------
# verify / frame validation in parse_request
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", [
    {"action": "click", "x": 1, "y": 2, "verify": "box.png"},
    {"action": "click", "x": 1, "y": 2, "verify": []},
    {"action": "click", "x": 1, "y": 2, "verify": {}},
    {"action": "click", "x": 1, "y": 2, "verify": {"template": "a", "text": "b"}},
    {"action": "click", "x": 1, "y": 2,
     "verify": {"template": "a", "required": "sim"}},
    {"action": "expect", "template": "a", "verify": {"template": "b"}},
    {"action": "click", "x": 1, "y": 2, "frame": "sim"},
])
def test_parse_request_rejects_bad_verify_or_frame(step):
    with pytest.raises(ValueError):
        agent_daemon.parse_request({"steps": [step]})


def test_parse_request_accepts_verify_block():
    steps = [{"action": "press_key", "key": "enter", "frame": True,
              "verify": {"template": "templates/wpp_caixa_vazia.png",
                         "confidence": 0.85, "timeout": 5}}]
    assert agent_daemon.parse_request({"steps": steps}) == steps


def test_parse_request_accepts_verify_by_text():
    steps = [{"action": "type_text", "text": "hi",
              "verify": {"text": "Type a message"}}]
    assert agent_daemon.parse_request({"steps": steps}) == steps


# ---------------------------------------------------------------------------
# automatic per-step capture
# ---------------------------------------------------------------------------

def capture_recorder():
    saved = []

    def capture_fn(path, cap=None):
        saved.append(path)
        return path

    return saved, capture_fn


def run_steps_with_frames(steps, ctx, capture_each_step=True):
    return agent_daemon.execute_steps(steps, ctx, "req",
                                      frames_dir=TEST_FRAMES_DIR,
                                      capture_each_step=capture_each_step)


def test_capture_each_step_saves_a_frame_after_write_actions():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    ok, results = run_steps_with_frames([
        {"action": "click", "x": 1, "y": 2},
        {"action": "sleep", "seconds": 0},
        {"action": "type_text", "text": "hi"},
    ], ctx)

    assert ok is True
    assert results[0]["frame_path"] == os.path.join(TEST_FRAMES_DIR, "req_step0.png")
    assert "frame_path" not in results[1], "sleep did not change the screen"
    assert results[2]["frame_path"] == os.path.join(TEST_FRAMES_DIR, "req_step2.png")
    assert len(saved) == 2


def test_capture_each_step_off_by_default():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    ok, results = run_steps([{"action": "click", "x": 1, "y": 2}], ctx)

    assert ok is True
    assert saved == []
    assert "frame_path" not in results[0]


def test_step_frame_flag_overrides_the_batch_default():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    run_steps_with_frames([
        {"action": "click", "x": 1, "y": 2, "frame": False},
        {"action": "sleep", "seconds": 0, "frame": True},
    ], ctx)

    assert saved == [os.path.join(TEST_FRAMES_DIR, "req_step1.png")]


def test_step_frame_flag_works_without_the_batch_default():
    saved, capture_fn = capture_recorder()
    ctx, fake = make_ctx(capture_fn=capture_fn)
    run_steps([{"action": "click", "x": 1, "y": 2, "frame": True}], ctx)

    assert saved == [os.path.join(TEST_FRAMES_DIR, "req_step0.png")]


def test_capture_failure_does_not_fail_a_good_action():
    """Capture is evidence, not a result."""
    def capture_fn(path, cap=None):
        raise OSError("capture device busy")

    ctx, fake = make_ctx(capture_fn=capture_fn)
    ok, results = run_steps_with_frames([{"action": "click", "x": 1, "y": 2}], ctx)

    assert ok is True
    assert results[0]["status"] == "ok"
    assert "capture device busy" in results[0]["frame_error"]


def test_frame_is_saved_before_the_verify_runs(monkeypatch):
    """If the verify fails, the PNG I will look at is the failed state's."""
    order = []

    def capture_fn(path, cap=None):
        order.append("capture")
        return path

    screen = FakeScreen(template_results=[MIC_PRESENT])
    ctx, fake = make_ctx(capture_fn=capture_fn)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)

    def probe(frame, path, confidence=0.85):
        order.append("verify")
        return MIC_PRESENT

    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame", probe)
    ok, results = run_steps_with_frames([
        {"action": "type_text", "text": "hi",
         "verify": {"template": "box.png", "absent": True}},
    ], ctx)

    assert ok is False
    # What this test pins is the ORDER: the capture comes before any read.
    # How many reads come after is a matter for EXPECT_TIMEOUT_DEFAULT, which
    # rechecks up to 5 times.
    assert order[0] == "capture"
    assert order.count("capture") == 1
    assert set(order[1:]) == {"verify"}
    assert results[0]["frame_path"] == os.path.join(TEST_FRAMES_DIR, "req_step0.png")


@pytest.mark.parametrize("data,default,expected", [
    ({"steps": []}, False, False),
    ({"steps": []}, True, True),
    ({"steps": [], "capture_each_step": True}, False, True),
    ({"steps": [], "capture_each_step": False}, True, False),
])
def test_request_capture_each_step_override(data, default, expected):
    assert agent_daemon.request_capture_each_step(data, default) is expected


# ---------------------------------------------------------------------------
# verify end-to-end: real template + real cv2, both ways
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="versioned template missing")
def test_verify_accepts_send_that_emptied_the_box(monkeypatch):
    """A real send: the box empties again and the microphone reappears.
    Measured on the real corpus: F2_enviada = 1.0000."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(True), raising=False)

    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "templates/wpp_caixa_vazia.png",
                    "confidence": 0.85}},
    ], ctx)

    assert ok is True, results
    assert results[0]["verify"]["expect_ok"] is True
    assert results[0]["verify"]["confidence"] >= 0.85


@pytest.mark.skipif(not os.path.exists(TEMPLATE_WPP),
                    reason="versioned template missing")
def test_verify_rejects_send_that_left_the_text_in_the_box(monkeypatch):
    """The real phase-F bug, end to end.

    The daemon's `ok=True` does not prove the key had an effect. With the text
    still in the box WhatsApp shows the send arrow, not the microphone, and
    the post-condition fails (measured: 389_digitada = 0.6983 against the 0.85
    threshold). Before `verify` this passed as a success."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array",
                        lambda: _synthetic_frame(False), raising=False)

    ok, results = run_steps([
        {"action": "press_key", "key": "enter",
         "verify": {"template": "templates/wpp_caixa_vazia.png",
                    "confidence": 0.85}},
        {"action": "type_text", "text": "must not run"},
    ], ctx)

    assert ok is False
    assert results[0]["verify_failed"] is True
    assert results[0]["aborted_batch"] is True
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "type_text" for c in fake.calls)


# ---------------------------------------------------------------------------
# frame pruning
# ---------------------------------------------------------------------------

def _make_frames(tmp_path, n, prefix="f"):
    """n PNGs with increasing mtime: the higher index is the newest."""
    paths = []
    for i in range(n):
        p = tmp_path / f"{prefix}{i:03d}.png"
        p.write_bytes(b"\x89PNG" + bytes([i]))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        paths.append(p)
    return paths


def test_prune_frames_keeps_the_newest(tmp_path):
    _make_frames(tmp_path, 10)
    removed = agent_daemon.prune_frames(str(tmp_path), keep=3)

    assert len(removed) == 7
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f007.png", "f008.png", "f009.png"]


def test_prune_frames_is_off_by_default(tmp_path):
    _make_frames(tmp_path, 5)
    assert agent_daemon.prune_frames(str(tmp_path), keep=0) == []
    assert len(list(tmp_path.iterdir())) == 5


def test_prune_frames_noop_when_under_the_limit(tmp_path):
    _make_frames(tmp_path, 3)
    assert agent_daemon.prune_frames(str(tmp_path), keep=10) == []
    assert len(list(tmp_path.iterdir())) == 3


def test_prune_frames_ignores_non_png(tmp_path):
    _make_frames(tmp_path, 5)
    (tmp_path / "notes.txt").write_text("not a frame")
    agent_daemon.prune_frames(str(tmp_path), keep=1)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f004.png", "notes.txt"]


def test_prune_frames_survives_missing_dir():
    assert agent_daemon.prune_frames("does/not/exist", keep=5) == []


# ---------------------------------------------------------------------------
# pruning by size
# ---------------------------------------------------------------------------

def _make_sized_frames(tmp_path, sizes, prefix="f"):
    """PNGs of a given size, increasing mtime (higher index = newer)."""
    paths = []
    for i, size in enumerate(sizes):
        p = tmp_path / f"{prefix}{i:03d}.png"
        p.write_bytes(b"\x89PNG" + b"x" * (size - 4))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        paths.append(p)
    return paths


def test_prune_by_size_keeps_the_newest_that_fit(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 10)
    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=3000)

    assert len(removed) == 7
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f007.png", "f008.png", "f009.png"]


def test_prune_by_size_removes_oldest_first(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 5)
    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=2000)

    assert [os.path.basename(p) for p in removed] == [
        "f000.png", "f001.png", "f002.png"]


def test_prune_by_size_is_off_when_zero(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 5)
    assert agent_daemon.prune_frames(str(tmp_path), max_bytes=0) == []
    assert len(list(tmp_path.iterdir())) == 5


def test_prune_by_size_noop_when_under_budget(tmp_path):
    _make_sized_frames(tmp_path, [100] * 3)
    assert agent_daemon.prune_frames(str(tmp_path), max_bytes=10_000) == []
    assert len(list(tmp_path.iterdir())) == 3


def test_prune_keeps_the_newest_even_if_it_busts_the_budget(tmp_path):
    """A too-tight cap must not empty the directory: the newest frame is the
    most useful, and losing it would leave nothing to look at."""
    _make_sized_frames(tmp_path, [500, 9000])   # f001 alone busts it
    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=1000)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["f001.png"]
    assert [os.path.basename(p) for p in removed] == ["f000.png"]


def test_prune_applies_the_tighter_of_the_two_limits(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 10)
    # size would leave 5; count leaves 2 => count wins
    agent_daemon.prune_frames(str(tmp_path), keep=2, max_bytes=5000)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f008.png", "f009.png"]


def test_prune_applies_the_tighter_limit_when_it_is_the_size(tmp_path):
    _make_sized_frames(tmp_path, [1000] * 10)
    # count would leave 8; size leaves 3 => size wins
    agent_daemon.prune_frames(str(tmp_path), keep=8, max_bytes=3000)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "f007.png", "f008.png", "f009.png"]


def test_prune_never_touches_the_keep_subdir(tmp_path):
    """queue/frames/keep/ holds the cited evidence and the template
    validation corpus: pruning by size must not take that."""
    _make_sized_frames(tmp_path, [1000] * 5)
    protected = tmp_path / agent_daemon.KEEP_SUBDIR
    protected.mkdir()
    _make_sized_frames(protected, [9000] * 4, prefix="evidence")

    removed = agent_daemon.prune_frames(str(tmp_path), max_bytes=1000)

    assert len(list(protected.iterdir())) == 4
    assert all(agent_daemon.KEEP_SUBDIR not in p for p in removed)
    # and the contents of keep/ do not count toward the parent directory cap
    assert (tmp_path / "f004.png").exists()


def test_prune_ignores_directories_named_like_png(tmp_path, caplog):
    """A directory named *.png must never become a candidate.

    Without the isfile filter the result would be the same -- os.remove fails
    on a directory and the error is swallowed --, but the log would gain a
    "could not prune" that sends the operator to investigate a problem that
    does not exist.
    """
    _make_sized_frames(tmp_path, [1000] * 3)
    folder = tmp_path / "folder.png"
    folder.mkdir()
    # OLDER than the frames: freshly created it would be the "newest" and
    # would escape via the last-frame protection, leaving the test vacuous.
    os.utime(folder, (1_600_000_000, 1_600_000_000))

    with caplog.at_level("WARNING", logger=agent_daemon.logger.name):
        agent_daemon.prune_frames(str(tmp_path), max_bytes=1000)

    assert (tmp_path / "folder.png").is_dir()
    assert "could not prune" not in caplog.text


def test_default_frames_budget_is_100_mb():
    assert agent_daemon.DEFAULT_FRAMES_MAX_MB == 100


# ---------------------------------------------------------------------------
# goto: landing verification via the Name Box
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ref,expected", [
    ("A1", "A1"),
    ("b37", "B37"),
    ("$B$37", "B37"),
    ("A1:C10", "A1"),          # range: the active cell is the first
    ("ZZ1000", "ZZ1000"),
    ("  C5  ", "C5"),
    ("my_name", None),         # defined name: cannot be predicted
    ("", None),
    ("A0", None),              # row 0 does not exist
])
def test_expected_landing_cell(ref, expected):
    assert agent_daemon.expected_landing_cell(ref) == expected


def make_namebox_ctx(monkeypatch, readings, controller=None):
    """ctx whose read_name_box returns the `readings` queue (the last repeats)."""
    ctx, fake = make_ctx(controller=controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    pending = list(readings)

    def read_name_box(frame, region=None, lang="eng"):
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(agent_daemon.screen_utils, "read_name_box",
                        read_name_box)
    return ctx, fake


def test_goto_ok_when_it_lands_on_the_requested_cell(monkeypatch):
    ctx, fake = make_namebox_ctx(monkeypatch, ["A34"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34"},
        {"action": "type_text", "text": "VALUATION"},
    ], ctx)

    assert ok is True, results
    assert results[0]["landed"] == "A34"
    assert results[0]["checked"] is True
    assert ("type_text", "VALUATION") in fake.calls


def test_goto_wrong_aborts_the_batch_before_typing(monkeypatch):
    """Regression for the 2026-11-06 incident.

    The goto to A34 did not land; the next line was typed from row 32 and the
    formula =SOMA(B32:F32) landed on row 32 itself, creating a circular
    reference. Excel's dialog then ate the keys and the rest of the block came
    out shifted. None of it would happen if the goto had checked where it
    stopped.
    """
    ctx, fake = make_namebox_ctx(monkeypatch, ["A32"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 0},
        {"action": "type_text", "text": "period PV\t=SOMA(B32:F32)"},
    ], ctx)

    assert ok is False
    assert results[0]["status"] == "error"
    assert results[0]["aborted_batch"] is True
    assert "A32" in results[0]["error"] and "A34" in results[0]["error"]
    assert results[1]["status"] == "skipped"
    # The goto itself types the reference into the "Go To" box, so there is a
    # legitimate type_text in fake.calls. What must not exist is the FORMULA.
    assert ("type_text", "A34") in fake.calls
    assert not any(c[0] == "type_text" and "SOMA" in c[1] for c in fake.calls)


def test_goto_waits_for_the_name_box_to_update(monkeypatch):
    """The Name Box takes a while to reflect; checking only once would fail."""
    ctx, fake = make_namebox_ctx(monkeypatch, [None, "A1", "A34"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 5},
    ], ctx)

    assert ok is True, results
    assert results[0]["attempts"] == 3


def test_goto_without_ocr_goes_on_without_checking(monkeypatch):
    """A machine without Tesseract must not become an aborted batch."""
    ctx, fake = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)

    def no_ocr(frame, region=None, lang="eng"):
        raise RuntimeError("reading the Name Box requires Tesseract-OCR")

    monkeypatch.setattr(agent_daemon.screen_utils, "read_name_box", no_ocr)
    ok, results = run_steps([
        {"action": "goto", "ref": "A34"},
        {"action": "type_text", "text": "ok"},
    ], ctx)

    assert ok is True
    assert results[0]["checked"] is False
    assert ("type_text", "ok") in fake.calls


def test_goto_verify_position_false_does_not_check(monkeypatch):
    ctx, fake = make_namebox_ctx(monkeypatch, ["ZZZ999"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_position": False},
    ], ctx)

    assert ok is True
    assert "landed" not in results[0]


def test_goto_with_non_coordinate_ref_does_not_check(monkeypatch):
    ctx, fake = make_namebox_ctx(monkeypatch, ["B2"])
    ok, results = run_steps([{"action": "goto", "ref": "named_range"}], ctx)

    assert ok is True
    assert results[0]["checked"] is False


def test_goto_is_among_the_actions_that_abort():
    """A failed goto is not one step less: it is the rest of the batch in the
    wrong place."""
    assert "goto" in agent_daemon.ABORT_BY_DEFAULT
    assert agent_daemon.step_is_required({"action": "goto", "ref": "A1"}) is True


# ---------------------------------------------------------------------------
# Name Box reading (screen_utils.parse_cell_ref)
# ---------------------------------------------------------------------------

import screen_utils


# ---------------------------------------------------------------------------
# OCR language
# ---------------------------------------------------------------------------

def test_resolve_lang_picks_an_installed_language(monkeypatch):
    """The default was "por" hardcoded, and this machine only has "eng":
    every expect without an explicit lang died with an error about
    TESSDATA_PREFIX, which sends you to look at the wrong environment variable."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ("eng", "osd"))
    assert screen_utils.resolve_lang(None) == "eng"


def test_resolve_lang_prefers_portuguese_when_present(monkeypatch):
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ("eng", "osd", "por"))
    assert screen_utils.resolve_lang(None) == "por"


def test_resolve_lang_explains_what_is_missing(monkeypatch):
    """The message must NAME what exists. Tesseract's talks about
    TESSDATA_PREFIX, and the problem is usually just the missing package."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ("eng",))
    with pytest.raises(RuntimeError) as exc:
        screen_utils.resolve_lang("por")
    assert "por" in str(exc.value)
    assert "eng" in str(exc.value)


def test_resolve_lang_respects_an_installed_request(monkeypatch):
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ("eng", "por"))
    assert screen_utils.resolve_lang("por+eng") == "por+eng"


def test_resolve_lang_follows_the_preference_not_the_alphabetical_order(
        monkeypatch):
    """Without this test the preference list is not being proven.

    Caught by a mutation test: shortening LANG_PREFERENCE to ("por",) broke
    nothing, because the fallback returned "eng" by chance -- "eng" is the
    first in alphabetical order among the installed ones here. With "deu" in
    the list, chance points the wrong way."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ("deu", "eng", "osd"))
    assert screen_utils.resolve_lang(None) == "eng"


def test_resolve_lang_does_not_return_osd(monkeypatch):
    """`osd` only detects orientation and script -- OCR on it reads no text.
    It comes in every install and is alphabetically before `por`."""
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ("deu", "osd"))
    assert screen_utils.resolve_lang(None) == "deu"


def test_resolve_lang_does_not_hang_without_tesseract(monkeypatch):
    # without Tesseract the languages cannot be listed; the right error comes
    # later, from whoever tries to use it, and not from here
    monkeypatch.setattr(screen_utils, "available_languages",
                        lambda reload=False: ())
    assert screen_utils.resolve_lang(None) == screen_utils.LANG_PREFERENCE[0]
    assert screen_utils.resolve_lang("por") == "por"


@pytest.mark.parametrize("read_text,expected", [
    ("A1", "A1"),
    ("B37", "B37"),
    ("K9", "K9"),
    ("  b37 ", "B37"),
    ("$B$37", "B37"),
    ("ZZ1000", "ZZ1000"),
    # classic confusions in the DIGIT part, disambiguated by position
    ("B3I", "B31"),
    ("B1O", "B10"),
    ("A1S", "A15"),
    ("C2B", "C28"),
])
def test_parse_cell_ref_fixes_ocr_confusion(read_text, expected):
    assert screen_utils.parse_cell_ref(read_text) == expected


@pytest.mark.parametrize("read_text", [
    "", None, "ABC",      # no digit at all: the row cannot be inferred
    "AI",                 # could be column AI or "A1" -- ambiguous
    "BS",                 # same: column BS or "B5"
    "K0", "A0",           # row 0 does not exist
    "1A",                 # a digit before the letter is not a reference
    "123",
])
def test_parse_cell_ref_fails_closed_when_ambiguous(read_text):
    """Prefer None to guessing.

    A wrong guess here makes `goto` believe it landed on the right cell and
    enables typing in the wrong place -- exactly the accident this check
    exists to prevent. Without a digit to anchor the split between column and
    row, 'BS' could be column BS or 'B5': returning None is the honest answer.
    """
    assert screen_utils.parse_cell_ref(read_text) is None


def test_read_name_box_reads_synthetic_text():
    """Full path with real cv2+Tesseract, without depending on the rig."""
    cv2 = pytesseract_img = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract not installed")

    x, y, w, h = screen_utils.NAME_BOX_REGION
    frame = numpy.zeros((y + h + 40, x + w + 40, 3), dtype=numpy.uint8)
    # Excel Name Box in dark theme: light text on a dark background
    frame[:] = (32, 32, 32)
    cv2.putText(frame, "B37", (x + 2, y + h - 6), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (240, 240, 240), 1, cv2.LINE_AA)

    assert screen_utils.read_name_box(frame) == "B37"


def test_read_name_box_blank_frame_is_empty_not_unreadable():
    """A frame with nothing is a BLANK region ("") -- not "unreadable text".

    The distinction decides what `goto` does: blank aborts (cell-edit mode),
    unreadable goes on without confirming.
    """
    numpy = pytest.importorskip("numpy")
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract not installed")
    frame = numpy.zeros((400, 400, 3), dtype=numpy.uint8)
    assert screen_utils.read_name_box(frame) == ""


# ---------------------------------------------------------------------------
# goto: "could not read" != "is in the wrong place"
# ---------------------------------------------------------------------------

def test_goto_empty_box_aborts_due_to_edit_mode(monkeypatch):
    """A blank Name Box is POSITIVE evidence of a bad state.

    In Excel it only goes blank in cell-edit mode, and there F5 does not even
    navigate -- it was the state the rig got into after a truncated formula.
    Typing on from there would write inside the cell being edited.
    """
    ctx, fake = make_namebox_ctx(monkeypatch, [""])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 0},
        {"action": "type_text", "text": "must not run"},
    ], ctx)

    assert ok is False
    assert results[0]["aborted_batch"] is True
    assert "EMPTY" in results[0]["error"]
    assert "edit" in results[0]["error"]
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "type_text" and "must not" in c[1] for c in fake.calls)


def test_goto_unreadable_goes_on_without_confirming(monkeypatch):
    """OCR that does not decode is a LACK of proof, not proof of error.

    Aborting here would let OCR fragility -- which errs on short refs like
    "A1" depending on the scale -- bring down perfectly correct batches. It
    goes on, but records checked=False to stay auditable.
    """
    ctx, fake = make_namebox_ctx(monkeypatch, [None])
    ok, results = run_steps([
        {"action": "goto", "ref": "A34", "verify_timeout": 0},
        {"action": "type_text", "text": "may run"},
    ], ctx)

    assert ok is True
    assert results[0]["checked"] is False
    assert "unreadable" in results[0]["reason"]
    assert ("type_text", "may run") in fake.calls


def test_the_three_goto_outcomes_are_distinct(monkeypatch):
    """Right cell / wrong cell / unreadable must not collapse into two."""
    outcomes = {}
    for name, reading in [("right", "A34"), ("wrong", "A32"), ("unreadable", None)]:
        ctx, _ = make_namebox_ctx(monkeypatch, [reading])
        ok, results = run_steps(
            [{"action": "goto", "ref": "A34", "verify_timeout": 0}], ctx)
        outcomes[name] = (ok, results[0].get("checked"))

    assert outcomes["right"] == (True, True)
    assert outcomes["wrong"][0] is False
    assert outcomes["unreadable"] == (True, False)


def test_read_name_box_distinguishes_empty_from_unreadable():
    """'' = blank region; None = has text but did not decode."""
    numpy = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    if screen_utils.locate_tesseract() is None:
        pytest.skip("Tesseract not installed")

    x, y, w, h = screen_utils.NAME_BOX_REGION
    empty = numpy.full((y + h + 20, x + w + 20, 3), 32, dtype=numpy.uint8)
    assert screen_utils.read_name_box(empty) == ""

    with_text = empty.copy()
    cv2.putText(with_text, "####", (x + 2, y + h - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
    assert screen_utils.read_name_box(with_text) is None


# ---------------------------------------------------------------------------
# gate for unmeasured ABNT2 characters
# ---------------------------------------------------------------------------

def test_unverified_in_steps_points_to_step_and_characters(monkeypatch):
    # The real set has been EMPTY since the probe of 2026-11-07, so a
    # character is injected: the daemon's gate must stay tested for the next
    # entry someone infers, and not only while there is a pending one.
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset('"[]'))
    steps = [
        {"action": "goto", "ref": "A1"},
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
        {"action": "type_text", "text": 'label "x" and [y]'},
    ]
    assert agent_daemon.unverified_in_steps(steps) == [(2, ['"', "[", "]"])]


def test_unverified_in_steps_does_not_complain_about_measured_chars():
    steps = [{"action": "type_text", "text": 'label "x" and [y] ~ ^ ´'}]
    assert agent_daemon.unverified_in_steps(steps) == []


def test_unverified_in_steps_ignores_a_step_without_text():
    # it must not blow up on a malformed batch: the step validates its field
    steps = [{"action": "type_text"}, {"action": "click", "x": 1, "y": 2},
             "not a dict"]
    assert agent_daemon.unverified_in_steps(steps) == []


def test_batch_with_unmeasured_char_types_nothing(monkeypatch):
    """Refuse BEFORE the first key, not halfway.

    Stopping halfway is the worst outcome: half a formula stays in the cell as
    text and the next step types on top of it. Step 0 here is valid on purpose
    -- it must not run either.
    """
    monkeypatch.setattr(hid_keycodes, "UNVERIFIED_CHARS", frozenset('"'))
    ctx, fake = make_ctx()
    ok, results = run_steps([
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
        {"action": "type_text", "text": "=SE(A1>0;\"sim\";\"nao\")"},
    ], ctx)

    assert ok is False
    assert fake.calls == []
    assert [r["status"] for r in results] == ["skipped", "skipped"]
    assert "never measured on the rig" in results[0]["reason"]
    assert "step 1" in results[0]["reason"]


def test_batch_without_a_suspect_char_runs_normally():
    # the gate must not become a "I will not type anything anymore"
    ctx, fake = make_ctx()
    ok, _ = run_steps(
        [{"action": "type_text", "text": "=POTÊNCIA(1+$B$9;B30)"}], ctx)

    assert ok is True
    assert ("type_text", "=POTÊNCIA(1+$B$9;B30)") in fake.calls


# ---------------------------------------------------------------------------
# single instance per queue
# ---------------------------------------------------------------------------

def test_second_daemon_on_the_same_queue_is_refused(tmp_path):
    """Two daemons on the same queue contend for the same request and the
    same serial port: the bytes of the two batches interleave on the 9600 bps
    line and the text comes out halfway, with no error at all.
    """
    first = agent_daemon.acquire_queue_lock(str(tmp_path))
    try:
        with pytest.raises(agent_daemon.AlreadyRunning):
            agent_daemon.acquire_queue_lock(str(tmp_path))
    finally:
        first.close()


def test_released_lock_accepts_the_next_daemon():
    """No stale lock: whoever closes gives the queue back.

    The lock is the OS's precisely for that -- a PID file would require
    checking whether the PID lives, and on Windows `os.kill(pid, 0)` calls
    TerminateProcess: the check would kill the process it is checking.
    """
    import tempfile

    folder = tempfile.mkdtemp(prefix="lock_")
    agent_daemon.acquire_queue_lock(folder).close()
    second = agent_daemon.acquire_queue_lock(folder)
    second.close()


def test_lock_records_the_pid_of_the_one_serving(tmp_path):
    handle = agent_daemon.acquire_queue_lock(str(tmp_path))
    try:
        path = tmp_path / agent_daemon.LOCK_NAME
        assert path.read_text().strip() == str(os.getpid())
    finally:
        handle.close()


def test_lock_creates_the_queue_if_it_does_not_exist(tmp_path):
    target = tmp_path / "new_queue"
    handle = agent_daemon.acquire_queue_lock(str(target))
    try:
        assert target.is_dir()
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# glyph confusion in the Name Box
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("requested,read_text", [
    ("A42", "AA2"),   # measured on the rig: the "4" becomes "A" and MOVES the cut
    ("B46", "B4G"),
    ("A1", "AI"),
    ("A60", "A6O"),
    ("C32", "C3Z"),
])
def test_confused_reading_counts_as_the_same_cell(requested, read_text):
    assert screen_utils.confusable_key(read_text) == screen_utils.confusable_key(requested)


@pytest.mark.parametrize("requested,read_text", [
    ("A34", "A32"),   # a genuinely different row
    ("A42", "B42"),   # a genuinely different column
    ("A1", "A60"),
    ("B46", "B46 "),  # (equal: a space does not count)
])
def test_a_different_cell_is_not_confused(requested, read_text):
    equal = screen_utils.confusable_key(read_text) == screen_utils.confusable_key(requested)
    assert equal == (requested.strip() == read_text.strip())


def test_confusion_classes_are_disjoint():
    """Merging "0/O" with "4/A" by transitivity would put "A" and "O" in the
    same class, and columns A and O are too far apart for that."""
    seen = {}
    for group in screen_utils._CONFUSABLE_CLASSES:
        for ch in group:
            assert ch not in seen, (
                "glyph %r in two classes: %r and %r" % (ch, seen[ch], group))
            seen[ch] = group
    # and "A" can never collapse with "O"
    assert screen_utils.confusable_key("A") != screen_utils.confusable_key("O")


def test_goto_accepts_the_right_cell_read_with_a_swapped_glyph(monkeypatch):
    """It was a false abort: the goto hit A42 and the batch stopped."""
    ctx, fake = make_namebox_ctx(monkeypatch, ["AA2"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A42"},
        {"action": "type_text", "text": "x"},
    ], ctx)

    assert ok is True
    assert results[0]["checked"] is True
    assert "OCR confusion" in results[0]["reason"]
    assert ("type_text", "x") in fake.calls


def test_goto_really_stops_when_the_cell_is_another(monkeypatch):
    # the guard must not become an "accepts anything"
    ctx, fake = make_namebox_ctx(monkeypatch, ["B42"])
    ok, results = run_steps([
        {"action": "goto", "ref": "A42"},
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
    ], ctx)

    assert ok is False
    assert ("type_text", "=SOMA(A1:A3)") not in fake.calls


# ---------------------------------------------------------------------------
# expect by text: several OCR scales
# ---------------------------------------------------------------------------

def test_expect_finds_the_text_at_a_larger_scale(monkeypatch):
    """It was the post-condition's false negative: "FCFF" is on screen, but at
    2x Tesseract read "Gigg" and the batch aborted."""
    screen = FakeScreen(ocr_results=[
        {"text": "Gigg 5612,8", "raw": ""},     # 2x: no good
        {"text": "FCFF 5612,8", "raw": ""},     # 4x: good
    ])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "FCFF", "region": [0, 0, 100, 50]},
    ], ctx)

    assert ok is True
    assert results[0]["upscale"] == 4
    assert screen.ocr_upscales[:2] == [2, 4]


def test_expect_stops_at_the_first_scale_that_matches(monkeypatch):
    # each scale is an OCR call; matching at the first must not cost the others
    screen = FakeScreen(ocr_results=[{"text": "PREMISSAS", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, results = run_steps([
        {"action": "expect", "text": "PREMISSAS", "region": [0, 0, 100, 50]},
    ], ctx)

    assert ok is True
    assert screen.ocr_upscales == [2]
    assert results[0]["upscale"] == 2


def test_absence_requires_not_matching_at_ANY_scale(monkeypatch):
    """The asymmetry that makes the check honest.

    A positive read proves presence. No positive read at a single scale does
    not prove absence -- it only proves that scale did not read. The
    spreadsheet reset depends on this: it asserts that "PREMISSAS" is gone.
    """
    screen = FakeScreen(ocr_results=[
        {"text": "unreadable garbage", "raw": ""},   # 2x does not see it
        {"text": "PREMISSAS", "raw": ""},            # 4x sees it: so NOT gone
    ])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "PREMISSAS", "absent": True,
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)

    assert ok is False
    assert screen.ocr_upscales[:2] == [2, 4]


def test_absence_confirmed_when_no_scale_sees_it(monkeypatch):
    screen = FakeScreen(ocr_results=[{"text": "empty spreadsheet", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "PREMISSAS", "absent": True,
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)

    assert ok is True
    # it swept ALL scales before asserting the absence
    assert screen.ocr_upscales == list(screen_utils.TEXT_SCALES)


def test_explicit_upscale_locks_to_a_single_scale(monkeypatch):
    screen = FakeScreen(ocr_results=[{"text": "A1", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    run_steps([
        {"action": "expect", "text": "A1", "region": [0, 0, 100, 50],
         "upscale": 10},
    ], ctx)

    assert screen.ocr_upscales == [10]


def test_expect_numeric_ignores_the_thousands_separator(monkeypatch):
    """The cell shows "67.804,85" after formatting; the post-condition looks
    for "67804". Without `numeric` that does not match."""
    screen = FakeScreen(ocr_results=[{"text": "Equity Value 67.804,85", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "67804", "numeric": True,
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)
    assert ok is True


def test_expect_without_numeric_does_not_cross_the_separator(monkeypatch):
    # the flag must change something: without it, "67804" is not in "67.804,85"
    screen = FakeScreen(ocr_results=[{"text": "Equity Value 67.804,85", "raw": ""}])
    ctx, _ = make_expect_ctx(monkeypatch, screen)
    ok, _ = run_steps([
        {"action": "expect", "text": "67804",
         "region": [0, 0, 100, 50], "timeout": 0},
    ], ctx)
    assert ok is False


def test_numeric_does_not_eat_the_decimal_comma():
    # 6,78 must not become 678: only the separator BETWEEN digits goes, and
    # the decimal comma stays
    assert screen_utils.normalize_digits("6,78") == "6,78"
    assert screen_utils.normalize_digits("1.234.567,89") == "1234567,89"
    assert screen_utils.normalize_digits("Planilha1.xlsx") == "Planilha1.xlsx"


# ---------------------------------------------------------------------------
# check_state action
# ---------------------------------------------------------------------------

def make_state_ctx(monkeypatch, states, controller=None):
    """ctx whose classify_frame returns the `states` queue (the last repeats)."""
    ctx, fake = make_ctx(controller=controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    pending = list(states)

    def classify_frame(frame, lang="eng"):
        state = pending.pop(0) if len(pending) > 1 else pending[0]
        return state, {}

    monkeypatch.setattr(agent_daemon.target_state, "classify_frame",
                        classify_frame)
    return ctx, fake


def test_check_state_returns_the_state_and_the_samples(monkeypatch):
    ctx, _ = make_state_ctx(monkeypatch, [agent_daemon.target_state.APP])
    ok, results = run_steps(
        [{"action": "check_state", "interval": 0}], ctx)

    assert ok is True
    assert results[0]["state"] == agent_daemon.target_state.APP
    assert results[0]["agree"] is True
    assert len(results[0]["per_frame"]) == 2   # two samples, always


def test_check_state_require_typable_refuses_a_locked_screen(monkeypatch):
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.LOCK_PHOTO])
    ok, results = run_steps([
        {"action": "check_state", "require_typable": True, "interval": 0},
        {"action": "type_text", "text": "=SOMA(A1:A3)"},
    ], ctx)

    assert ok is False
    assert ("type_text", "=SOMA(A1:A3)") not in fake.calls
    assert "LOCK_PHOTO" in results[0]["error"]


def test_check_state_refuses_when_the_samples_disagree(monkeypatch):
    """A signal in transition: the batch must not start now."""
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.BLACK, ts.APP])
    ok, results = run_steps([
        {"action": "check_state", "require_typable": True, "interval": 0},
        {"action": "type_text", "text": "x"},
    ], ctx)

    assert ok is False
    assert fake.calls == []
    assert "UNDETERMINED" in results[0]["error"]


def test_check_state_lets_through_when_it_can_type(monkeypatch):
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.LOCK_PASSWORD])
    ok, _ = run_steps([
        {"action": "check_state", "require_typable": True, "interval": 0},
        {"action": "type_text", "text": "senha"},
    ], ctx)

    assert ok is True
    assert ("type_text", "senha") in fake.calls


def test_check_state_without_require_typable_does_not_abort(monkeypatch):
    # it only reports; serves diagnosis without bringing down the batch
    ts = agent_daemon.target_state
    ctx, fake = make_state_ctx(monkeypatch, [ts.NO_SIGNAL])
    ok, results = run_steps([
        {"action": "check_state", "interval": 0},
        {"action": "press_key", "key": "esc"},
    ], ctx)

    assert ok is True
    assert results[0]["state"] == ts.NO_SIGNAL
    # the next step ran: without require_typable the action only reports
    assert results[1]["status"] == "ok"
    assert ("key_press", 0x29, 0) in fake.calls   # esc


def test_check_state_is_abortive_by_nature():
    assert "check_state" in agent_daemon.ABORT_BY_DEFAULT


# ---------------------------------------------------------------------
# capture_array is the path of the VERIFICATIONS (expect, ocr_region,
# find_image, wait_for_text, check_state). Until 2026-11-08 it had its own
# copy of the grab/read and so was left out of the stale-frame fix -- the
# fix covered only the path that saves a PNG.
# ---------------------------------------------------------------------

# Saved at import, BEFORE the autouse fixture that blocks real capture:
# these two tests want to exercise the real implementation, not a stub.
_CAPTURE_ARRAY_REAL = agent_daemon.DaemonContext.capture_array


class FakeCapture:
    """Returns 'previous_frame' on the first read() and 'current_frame'
    after -- imitates the pipeline that stays one capture behind."""

    def __init__(self):
        self.grabs = 0
        self.reads = 0

    def grab(self):
        self.grabs += 1
        return True

    def read(self):
        self.reads += 1
        return True, "previous_frame" if self.reads == 1 else "current_frame"

    def release(self):
        pass


def test_capture_array_does_not_return_the_previous_frame(monkeypatch):
    """The regression that motivated everything: the path that decides whether
    it can type was reading the frame from before the action."""
    monkeypatch.setattr(agent_daemon.DaemonContext, "capture_array",
                        _CAPTURE_ARRAY_REAL)
    cap = FakeCapture()
    ctx = agent_daemon.DaemonContext(lambda: None)
    monkeypatch.setattr(ctx, "_ensure_capture", lambda: cap, raising=False)

    assert ctx.capture_array() == "current_frame"
    assert cap.reads > 1, "without a discarded read() the previous frame comes back"


def test_the_two_capture_paths_use_the_same_read(monkeypatch, tmp_path):
    """Pins the CAUSE of the bug, not just the symptom.

    The defect was not forgetting one discard: it was having two copies of
    the read, so that fixing one left the other behind. If someone
    reimplements grab/read on one side, the two paths start to diverge and
    this test fails."""
    monkeypatch.setattr(capture_frame.cv2, "imwrite", lambda path, frame: True)

    cap_file = FakeCapture()
    capture_frame.capture_frame_to_file(str(tmp_path / "a.png"), cap=cap_file)

    monkeypatch.setattr(agent_daemon.DaemonContext, "capture_array",
                        _CAPTURE_ARRAY_REAL)
    cap_array = FakeCapture()
    ctx = agent_daemon.DaemonContext(lambda: None)
    monkeypatch.setattr(ctx, "_ensure_capture", lambda: cap_array, raising=False)
    ctx.capture_array()

    assert (cap_file.grabs, cap_file.reads) == (cap_array.grabs, cap_array.reads)


def test_the_default_timeout_covers_the_worst_measured_case_with_margin():
    """The expect default is not a round number picked at random.

    Measured on the rig on 2026-11-08: 10 of 10 expects passed, needing 2
    reads in nine of them. The default must give well more than that, or it
    goes back to failing with the text on screen -- which was exactly the
    zero-`timeout` bug."""
    reads = int(agent_daemon.EXPECT_TIMEOUT_DEFAULT
                / agent_daemon.EXPECT_POLL_DEFAULT) + 1
    assert reads >= agent_daemon.EXPECT_ATTEMPTS_MEASURED * 2, (
        "the default lost its margin over the worst case measured on the rig")


def test_a_single_read_would_not_be_enough():
    """Pins why the default must not go back to zero.

    Nine of the ten measured cycles needed a SECOND read."""
    assert agent_daemon.EXPECT_ATTEMPTS_MEASURED > 1
    assert agent_daemon.EXPECT_TIMEOUT_DEFAULT > 0, (
        "with timeout 0 the expect reads only once, and the rig showed that one "
        "read fails 9 of 10 times with the text on screen")


# ---------------------------------------------------------------------
# type_text "secret": the password guard.
#
# Born from a batch I built on 2026-11-08: it read LOCK_PHOTO -- a state that
# can_type() refuses -- and typed the password right after, because nothing
# forced a look. It worked by luck.
# ---------------------------------------------------------------------

def _ctx_with_state(monkeypatch, state, agree=True):
    controller = FakeController()
    ctx = agent_daemon.DaemonContext(lambda: controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.target_state, "sample",
                        lambda *a, **k: {"state": state,
                                         "agree": agree,
                                         "per_frame": [state, state]})
    return ctx, controller


def test_secret_types_on_the_password_screen(monkeypatch):
    ctx, controller = _ctx_with_state(monkeypatch, agent_daemon.target_state.LOCK_PASSWORD)
    ok, _ = run_steps([{"action": "type_text", "text": "s3nh4", "secret": True}], ctx)
    assert ok
    assert ("type_text", "s3nh4") in controller.calls


@pytest.mark.parametrize("state", [
    "APP",                 # the dangerous case: an application window focused
    "LOCK_PHOTO",
    "NO_SIGNAL",
    "BLACK",
    "UNDETERMINED",
])
def test_secret_refuses_on_any_screen_other_than_the_password_one(monkeypatch, state):
    """APP is on the list on purpose: can_type() accepts APP, and that is why
    the guard CANNOT be can_type -- the password would go to the spreadsheet,
    the chat or the search bar that had focus."""
    ctx, controller = _ctx_with_state(monkeypatch, state)
    ok, results = run_steps([{"action": "type_text", "text": "s3nh4", "secret": True}], ctx)
    assert not ok
    assert not any(c[0] == "type_text" for c in controller.calls), (
        "the password must NOT have been sent")
    assert "refused" in results[0]["error"]


def test_secret_refuses_when_the_samples_disagree(monkeypatch):
    """A screen in transition is no place to type a password."""
    ctx, controller = _ctx_with_state(
        monkeypatch, agent_daemon.target_state.LOCK_PASSWORD, agree=False)
    ok, _ = run_steps([{"action": "type_text", "text": "s3nh4", "secret": True}], ctx)
    assert not ok
    assert not any(c[0] == "type_text" for c in controller.calls)


def test_refused_secret_aborts_the_batch(monkeypatch):
    """If the following steps ran, the Enter would submit an empty field and
    burn one of the three password attempts."""
    ctx, controller = _ctx_with_state(monkeypatch, "APP")
    ok, results = run_steps([
        {"action": "type_text", "text": "s3nh4", "secret": True},
        {"action": "press_key", "key": "enter"},
    ], ctx)
    assert not ok
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "press_named_key" for c in controller.calls), (
        "the Enter must not have run: it would submit an empty field and burn "
        "one of the three attempts")


def test_malformed_secret_is_refused_instead_of_ignored():
    """A 'secret' that is worth nothing is worse than none: it gives the
    confidence of a guard that does not exist."""
    with pytest.raises(ValueError, match="secret"):
        agent_daemon.parse_request(
            {"steps": [{"action": "type_text", "text": "x", "secret": "true"}]})
    with pytest.raises(ValueError, match="secret"):
        agent_daemon.parse_request(
            {"steps": [{"action": "press_key", "key": "enter", "secret": True}]})


def test_request_with_a_secret_is_deleted_not_archived(tmp_path):
    """A password archived in processed/ stays in cleartext on disk. Until now
    this depended on me remembering to delete it by hand."""
    req = tmp_path / "900_enter.json"
    req.write_text("{}", encoding="utf-8")
    processed = tmp_path / "processed"
    processed.mkdir()

    agent_daemon._finish_request(str(req), str(processed), secret=True)

    assert not req.exists()
    assert list(processed.iterdir()) == [], "the password must not go to processed/"


def test_an_ordinary_request_is_still_archived(tmp_path):
    req = tmp_path / "901_normal.json"
    req.write_text("{}", encoding="utf-8")
    processed = tmp_path / "processed"
    processed.mkdir()

    agent_daemon._finish_request(str(req), str(processed))

    assert [p.name for p in processed.iterdir()] == ["901_normal.json"]


def test_has_secret_step_finds_it_in_any_position():
    steps = [{"action": "click"}, {"action": "type_text", "secret": True}]
    assert agent_daemon.has_secret_step(steps)
    assert not agent_daemon.has_secret_step([{"action": "type_text"}])
    assert not agent_daemon.has_secret_step([])


def test_request_with_a_secret_does_not_remain_on_disk_through_the_daemon(tmp_path, monkeypatch):
    """The previous test called _finish_request DIRECTLY and so did not cover
    the wiring: on a mutation that went back to archiving the request with a
    password, it passed. This one goes through the real path.

    It matters because what leaks is not the function -- it is the file left
    in processed/ with the password in cleartext."""
    requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir = make_queue(tmp_path)
    request_path = os.path.join(requests_dir, "902_enter.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({"steps": [
            {"action": "type_text", "text": "s3nh4-for-real", "secret": True}
        ]}, f)

    ctx, _ = make_ctx()
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    monkeypatch.setattr(agent_daemon.target_state, "sample",
                        lambda *a, **k: {"state": agent_daemon.target_state.LOCK_PASSWORD,
                                         "agree": True,
                                         "per_frame": ["LOCK_PASSWORD"] * 2})

    agent_daemon.process_request_file(
        request_path, ctx, responses_dir, processed_dir, processing_dir,
        failed_dir, frames_dir=frames_dir)

    assert not os.path.exists(request_path)
    assert os.listdir(processed_dir) == [], "request with a password archived"
    assert os.listdir(processing_dir) == []

    # and the response, which STAYS on disk, must not carry the text
    with open(os.path.join(responses_dir, "902_enter.json"), encoding="utf-8") as f:
        raw_text = f.read()
    assert "s3nh4-for-real" not in raw_text


# ---------------------------------------------------------------------
# focus_window: look BEFORE you click.
#
# On 2026-11-19 a batch of mine clicked the WhatsApp icon on the taskbar. The
# window was ALREADY focused, and clicking the icon of a focused window
# MINIMIZES it -- I knocked down the screen the user had left ready, and the
# next expect aborted the batch.
# ---------------------------------------------------------------------

def _ctx_focus(monkeypatch, results):
    """results: list of find_image_in_frame responses, in order."""
    controller = FakeController()
    ctx = agent_daemon.DaemonContext(lambda: controller)
    monkeypatch.setattr(ctx, "capture_array", lambda: "FRAME", raising=False)
    pending = list(results)
    monkeypatch.setattr(agent_daemon.screen_utils, "find_image_in_frame",
                        lambda *a, **k: pending.pop(0) if pending else {"found": False, "confidence": 0.0})
    return ctx, controller


def test_focus_window_does_not_click_if_the_window_is_already_in_front(monkeypatch):
    """The exact regression: clicking here MINIMIZES the window."""
    ctx, controller = _ctx_focus(monkeypatch, [{"found": True, "confidence": 0.99}])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "x": 898, "y": 1057}], ctx)
    assert ok
    assert results[0]["already_fronted"] is True
    assert results[0]["clicked"] is False
    assert controller.calls == [], "it must not have clicked anything"


def test_focus_window_clicks_when_the_window_is_not_in_front(monkeypatch):
    ctx, controller = _ctx_focus(monkeypatch, [
        {"found": False, "confidence": 0.3},   # not in front yet
        {"found": True, "confidence": 0.99},   # came after the click
    ])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "x": 898, "y": 1057}], ctx)
    assert ok
    assert results[0]["clicked"] is True
    assert any(c[0] == "click_absolute" for c in controller.calls)


def test_focus_window_finds_the_icon_by_image(monkeypatch):
    """A fixed coordinate is fragile: on the same day the icon moved from 876 to 898."""
    ctx, controller = _ctx_focus(monkeypatch, [
        {"found": False, "confidence": 0.3},               # window not in front
        {"found": True, "confidence": 0.98, "x": 898, "y": 1058},  # icon found
        {"found": True, "confidence": 0.99},               # window came
    ])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "icon_template": "templates/wpp_icone_barra.png"}], ctx)
    assert ok
    assert (results[0]["x"], results[0]["y"]) == (898, 1058)


def test_focus_window_without_icon_and_without_window_does_not_click_blindly(monkeypatch):
    """With no idea where to click, it refuses -- it does not guess a coordinate."""
    ctx, controller = _ctx_focus(monkeypatch, [
        {"found": False, "confidence": 0.3},   # window not in front
        {"found": False, "confidence": 0.2},   # icon not found
    ])
    ok, results = run_steps([{"action": "focus_window",
                              "template": "templates/wpp_janela.png",
                              "icon_template": "templates/wpp_icone_barra.png"}], ctx)
    assert not ok
    assert controller.calls == []
    assert "icon" in results[0]["error"]


def test_focus_window_aborts_the_batch_when_the_window_does_not_come(monkeypatch):
    """If the window did not come, the following write steps do NOT run."""
    ctx, controller = _ctx_focus(monkeypatch, [{"found": False, "confidence": 0.1}])
    ok, results = run_steps([
        {"action": "focus_window", "template": "templates/wpp_janela.png",
         "x": 898, "y": 1057, "timeout": 0},
        {"action": "type_text", "text": "must not go out"},
    ], ctx)
    assert not ok
    assert results[1]["status"] == "skipped"
    assert not any(c[0] == "type_text" for c in controller.calls)
