"""
Command daemon for the operator agent (file-based queue).

MOTIVATION
==========
The operator agent can only act on the machine via computer-use (screenshot
+ click), which is expensive. This daemon inverts the flow: it is started
ONCE (the only computer-use cost), keeps the connection to the CH9329 open
and watches a queue folder. From then on the operator controls the target
machine simply by WRITING JSON files into this folder and READING the
responses -- zero screenshots, zero windows.

HOW TO START (via computer-use, a single time)
===============================================
With no console visible on the user's screen, use pythonw.exe (the Windows
GUI interpreter, which allocates no console). In the Run box (Win+R):

  pythonw C:\\path\\to\\project\\agent_daemon.py

(If "pythonw" is not on PATH, use the full path to the pythonw.exe that
sits next to the installation's python.exe.)

Console alternative (for debugging):
  python agent_daemon.py --verbose
Simulated mode, no hardware:
  python agent_daemon.py --dry-run

TO STOP: create an empty file  queue/stop  -- the daemon deletes it and exits.

LOG: agent_daemon.log (append) in the project folder.

PROTOCOL (the operator's "API")
===============================
Folder structure (created automatically in the project folder):

  queue/requests/   <- operator writes   NNN_name.json  (request)
  queue/processing/ <- request in progress (moved from requests/ at the start)
  queue/responses/  <- daemon writes the  NNN_name.json  (response, SAME name)
  queue/processed/  <- successful request moved here
  queue/failed/     <- requests with invalid JSON or a catastrophic error
  queue/frames/     <- PNGs produced by capture_frame steps
  queue/stop        <- shutdown sentinel (empty file)

IMPORTANT: if the daemon is interrupted while running a batch, the request
file stays in queue/processing/. Move it back to queue/requests/ by hand to
reprocess it (the response was NOT written).

Operator flow (all via file tools, no computer-use):
  1. Write queue/requests/001_task.json with a BATCH of steps.
  2. Wait/poll: read queue/responses/001_task.json once it exists.
  3. If any step was capture_frame, read the PNG named in frame_path.
Use numeric prefixes (001_, 002_, ...) -- the queue is processed in
alphabetical order of file name.

REQUEST -- JSON with a list of steps (send the whole batch at once):
  {
    "steps": [
      {"action": "click",         "x": 960, "y": 540, "button": "left"},
      {"action": "move",          "x": 100, "y": 100},
      {"action": "type_text",     "text": "=SUM(A1:A10)\\n", "char_delay": 0.02},
      {"action": "press_key",     "key": "enter"},
      {"action": "key_combo",     "key": "b", "modifiers": ["ctrl"]},
      {"action": "goto",          "ref": "B2"},
      {"action": "scroll",        "amount": -3, "x": 960, "y": 540},
      {"action": "sleep",         "seconds": 0.5},
      {"action": "capture_frame", "path": "after_the_formula.png"}
    ]
  }

Actions (coordinates are ALWAYS local to the target machine's monitor 2,
0,0 = top-left corner, mapped via monitor2.py):
  click         x, y; optional button: "left" (default) | "right" | "middle"
  move          x, y
  type_text     text (ABNT2 table from hid_keycodes.py; \\n = Enter, \\t = Tab);
                optional char_delay in seconds (default 0.03 = useful floor at
                9600 bps; asking for less slows it down. Use ~0.15 in messaging
                apps, for bot anti-detection, not for hardware, and 0.08-0.15
                on a long Excel formula: at 0.03 Excel loses a character even
                though the serial keeps up).
                AN UNMEASURED CHARACTER REFUSES THE WHOLE BATCH, before the
                first step: see hid_keycodes.UNVERIFIED_CHARS. Today it is
                [ ] { } \\ | ' " and the dead-key glyphs. A wrong usage raises
                no error, it emits another character -- and if it is a dead
                key, it swallows the next one.
  check_state   classifies the target screen with 2+ samples (samples,
                interval, lang). With require_typable=true, it refuses the
                batch if the state does not accept the keyboard. ONE sample
                does not classify: the capture device's buffer serves an old
                frame.
  press_key     key = a named key (enter, esc, tab, f1..f12, arrows, home,
                end, pageup, pagedown, delete, ...) or a character; optional
                modifiers; optional hold (seconds held down)
  key_combo     same as press_key, typically used with modifiers:
                ["ctrl"|"shift"|"alt"|"gui"/"win"] (e.g. Ctrl+B)
  goto          ref = a reference (e.g. "B2", "A1:C10"); opens "Go To" with
                F5, types the ref and presses Enter -- selects a cell/range in
                Excel without the mouse; optional delay after F5 (default 0.4s)
  scroll        amount (positive = up, negative = down, clamped to +/-127);
                x, y optional (default: center)
  capture_frame saves a PNG frame of the target screen (headless, no window);
                optional path (relative => inside queue/frames/);
                default: queue/frames/<request>_stepN.png
                A short sleep (~0.3s) still helps so the remote app can
                REDRAW after a keyboard action. What no longer helps is
                sleeping to escape an old frame:
                FIXED on 2026-11-07. The old version of this text told you to
                sleep >=1.0s because "at 0.3s the PNG showed the previous
                state". Measured on the rig, that was wrong: the lag is not in
                seconds, it is ONE capture. Waiting did not fix it -- 16 of 16
                single captures showed already-deleted text, even waiting 4
                seconds. What fixes it is the discarded read() inside
                capture_frame (DISCARD_READS), which costs ~25ms: after it, 0
                of 16.
  sleep         seconds (MAX_SLEEP_SECONDS cap per step)
  wait_for_change waits for a visual change on screen; timeout in seconds
                (default 10), threshold (mean diff 0-255, default 3.0),
                optional region [x,y,w,h], settle_ms (settling ms after the
                change, default 300). Replaces fixed sleeps with adaptive
                waiting. Returns {"changed": bool, "elapsed": s, "score": f}.
                Use a higher threshold (5-10) for obvious changes (window
                switch), lower (1-3) for subtle ones (cursor appearing, cell
                being selected).
  wait_for_text  waits for text to appear on screen via OCR; text (required
                substring), optional region [x,y,w,h], lang (default: the
                installed language, see screen_utils.resolve_lang), timeout in
                seconds (default 10). Returns {"found": bool, "text": str}.
                Requires pytesseract + Tesseract-OCR installed.
  find_image    searches for a PNG template on screen via matchTemplate;
                template (path relative to the project or absolute, required),
                confidence (default 0.85), click (bool -- clicks the center if
                found, default false). Returns {"found": bool, "x": int,
                "y": int, "confidence": f}. Tries 3 scales (0.9, 1.0, 1.1) for
                robustness to DPI variation.
  ocr_region    extracts text from a screen region; optional region [x,y,w,h]
                (None = whole screen), lang (default: the installed language),
                save_as (extra key in the result). Returns {"text": str,
                "raw": str}. Requires pytesseract + Tesseract-OCR.
  screenshot_diff compares two PNGs; before and after (paths, relative =>
                queue/frames/). Returns {"changed_pct": f, "regions":
                [[x,y,w,h],...], "diff_path": str|null}. diff_path is the
                "after" PNG with red rectangles on the changed regions (saved
                next to the after).
  hid_reset     sends CMD_RESET to the CH9329: restores the chip's default
                config (useful after unexpected keyboard/mouse behavior).
  type_text ... a "secret": true field marks the text as a PASSWORD. The step
                then: (a) checks the screen and only types if it is
                LOCK_PASSWORD, with two samples agreeing -- not even APP will
                do, because an application window is exactly where the
                password must not land; (b) aborts the batch if it refuses, so
                the following `Enter` does not submit an empty field and burn
                one of the 3 attempts; (c) makes the daemon DELETE the request
                instead of archiving it in processed/, so the password does
                not stay in cleartext on disk.
  focus_window  brings a window to the front WITHOUT knocking down what is
                already there. template (required) = visual mark of the
                window; icon_template OR x,y = the taskbar icon; confidence
                (0.85), timeout (8).
                It LOOKS at the screen FIRST: if the window is ALREADY in
                front, it clicks nothing and returns {"already_fronted":
                true}. This exists because clicking the icon of a window that
                is already focused MINIMIZES it -- on 2026-11-19 that is how a
                batch knocked down the WhatsApp the user had left ready on
                screen. Prefer icon_template over x,y: icon positions shift as
                apps open and close (on the same day WhatsApp moved from x=876
                to x=898).
                Aborts the batch if the window does not come.
  hid_info      reads the keyboard LIGHTS on the target (CMD_GET_INFO).
                Returns {"num_lock": bool, "caps_lock": bool, "scroll_lock":
                bool, "usb_connected": bool, "version": int}. Changes nothing,
                only reads. Use BEFORE typing when the letter case matters
                (password!): a stuck Caps Lock raises no error anywhere, it
                just flips upper/lower case, and the symptom shows up far from
                the cause.
  expect        CHECKS a screen condition and ABORTS the batch if it does not
                hold. It is the only step that stops execution by default.
                Exactly one of:
                  template  PNG to match on screen (cv2.matchTemplate);
                            optional confidence (default 0.85). PREFERRED: it
                            does not depend on an external binary.
                  text      substring to find via OCR; optional region
                            [x,y,w,h] and lang. REQUIRES Tesseract-OCR
                            installed -- the pytesseract package alone is NOT
                            enough and the step fails with an explicit error.
                absent (bool, default false) inverts it: requires that it NOT
                be on screen. timeout (default EXPECT_TIMEOUT_DEFAULT = 2.0s;
                explicit `timeout: 0` = a single read) and poll (default 0.5)
                allow waiting for the condition to appear. Measured on the
                rig: the expect needs 2 reads in 9 of every 10 times, so a
                single read fails with the text on screen.
                CAUTION when choosing the text: avoid DIGITS. Measured on
                2026-11-08, OCR read "ZEBRA01" as "ZEBRAO1" and failed 10 of
                10; with letter-only markers, it passed 10 of 10. 0/O, 1/l and
                5/S are the classic swaps.
                Returns {"expect_ok": true, "attempts": n, ...}.

Fields common to ANY step:
  required      (bool) if the step fails, the following steps do not run and
                are left with status "skipped". Default: false for all
                actions, EXCEPT `expect`, where the default is true. Use
                "required": false on an expect to only record the condition in
                the response without aborting.
  verify        (object) POST-condition: same syntax as `expect`
                (template|text, confidence, absent, timeout, poll), but
                checked AFTER the action runs, and only if it did not fail.
                It asks "did the screen change the way this action was
                supposed to change it?". A failure => the step becomes "error"
                with "verify_failed": true and the batch aborts (use
                "required": false INSIDE the verify to only record it).
                E.g.: {"action": "press_key", "key": "enter",
                     "verify": {"template": "templates/wpp_empty_box.png"}}
  frame         (bool) saves a PNG right after the action, before the verify.
                Without it, the request's `capture_each_step` / the daemon's
                --frame-per-step apply, which turn capture on only for the
                write actions (WRITE_ACTIONS).

REQUEST field (sibling of "steps"):
  capture_each_step (bool) turns the automatic per-step capture on/off for the
                whole batch, overriding the daemon default.

What `expect` is for: without it, the only way to guarantee that the text
lands in the right window is to return a capture to the operator between each
write action, which costs the human review latency at every step. With it,
the verification happens inside the batch in ~0.4s and the whole request can
be chained with MORE guarantee than manual review gave -- the sequence
"expect message box -> type_text" types nothing if the screen is not the
expected one. There was already an incident where a whole message was typed
into the Windows password field because the screen had re-locked mid-batch;
an expect at the start of the batch would have aborted.

Why `expect` is NOT enough and `verify` exists: an expect is a pre-condition,
it looks at the screen BEFORE the action. It does not catch the failure where
the screen was right, the chip confirmed the key, and still nothing happened
on the target machine. It really happened: a send request with `Enter`
returned ok=True and sent nothing -- without a click reasserting focus, the
Enter landed outside the compose field. Only a post-condition catches this.
On WhatsApp the post-condition is cheap because the app swaps the microphone
icon for the send arrow when there is text: after a real send the box empties
and the microphone comes back. Measured on the real frame corpus, against
templates/wpp_empty_box.png: empty box = 1.0000, text in the box = 0.6983,
with a threshold of 0.85 -- a margin of 0.15 on each side.

RESPONSE -- same name as the request, in queue/responses/:
  {
    "request": "001_task.json",
    "ok": false,                       <- true only if ALL steps are ok
    "started_at": "2026-07-01T10:00:00",
    "finished_at": "2026-07-01T10:00:03",
    "steps": [
      {"index": 0, "action": "click", "status": "ok"},
      {"index": 1, "action": "type_text", "status": "error",
       "error": "character with no HID mapping: '\\u20ac'"},
      {"index": 8, "action": "capture_frame", "status": "ok",
       "frame_path": "C:\\\\...\\\\queue\\\\frames\\\\001_task_step8.png"}
    ]
  }

A step with an error does NOT bring down the daemon and, by default, does not
abort the batch: the following steps continue and the error is recorded in
the response. The exception is a step with "required": true (implicit in
`expect`): on failure it gets "aborted_batch": true and the remaining steps
appear in the response with status "skipped" and the index that aborted.

A serial error (CH9329 disconnected) drops the current connection and the
step is retried ONCE with a fresh connection; if it fails again, it becomes
"error" in the response and the next step tries to reconnect once more.

Requests with invalid JSON produce an error response (after a tolerance
window of ~2s for files still being written).
"""
import argparse
import json
import logging
import os
import queue as _stdlib_queue
import re
import sys
import time
from datetime import datetime

import serial

import monitor2
import screen_utils
import target_state
from capture_frame import FLUSH_FRAMES, capture_frame_to_file, read_fresh_frame
from capture_utils import open_configured_capture
from ch9329 import BUTTON_LEFT, BUTTON_MIDDLE, BUTTON_RIGHT, PartialTypeError
from config import load_config, queue_dir
from controller_utils import resolve_controller
import hid_keycodes
from hid_keycodes import (
    MODIFIER_LEFT_ALT,
    MODIFIER_LEFT_CTRL,
    MODIFIER_LEFT_GUI,
    MODIFIER_LEFT_SHIFT,
    char_to_usage,
    named_key_to_usage,
    unverified_chars,
)

# Watchdog (instant filesystem events instead of polling)
# Install: pip install watchdog
try:
    from watchdog.events import PatternMatchingEventHandler as _PMHandler
    from watchdog.observers import Observer as _Observer

    class _RequestWatcher(_PMHandler):
        """Puts paths of new/renamed .json files into a stdlib queue."""

        def __init__(self, event_queue):
            super().__init__(patterns=["*.json"], ignore_directories=True,
                             case_sensitive=False)
            self._q = event_queue

        def on_created(self, event):
            self._q.put(event.src_path)

        def on_moved(self, event):
            # Catch atomic writes (.tmp -> .json via os.replace)
            if event.dest_path.lower().endswith(".json"):
                self._q.put(event.dest_path)

    _WATCHDOG_OK = True
except ImportError:
    _Observer = None
    _RequestWatcher = None
    _WATCHDOG_OK = False

logger = logging.getLogger(__name__)

# agent_daemon lives in src/; the project root (where templates/ and the log
# live) is one level up.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_DIR = queue_dir()   # outside the synced folder; see config.queue_dir
LOG_PATH = os.path.join(BASE_DIR, "agent_daemon.log")

POLL_INTERVAL = 0.1          # seconds between queue scans
PARSE_GRACE_SECONDS = 2.0    # tolerance for a file still being written
MAX_SLEEP_SECONDS = 60.0     # cap for a sleep step
DEFAULT_GOTO_DELAY = 0.4     # wait after F5 before typing the ref
# 0.03 is the useful floor at 9600 bps, not an arbitrary number: each key
# event is 2 frames of 14 bytes = 28 bytes = ~29ms of serial line. Asking for
# less does not speed it up -- the buffer fills, the write starts blocking and
# the real rate gets WORSE (measured: 0.020 -> 36.7ms/event, 0.018 ->
# 42.2ms/event, against 30.0ms/event asking for 0.030). See
# docs/ABNT2_HID_KEYBOARD.md.
DEFAULT_CHAR_DELAY = 0.03
GOTO_SETTLE_SECONDS = 0.3    # wait after Enter for the Go To box to close

# Keep-alive: the target machine's screen re-locks in ~5 min with no activity,
# which already caused an accident (a message typed into the password field
# because the screen locked mid-sequence). 120s gives comfortable headroom
# within the ~300s. Off by default: keeping the machine unlocked gives up a
# protection, so it has to be an explicit choice.
KEEP_ALIVE_SECONDS = 120
KEEP_ALIVE_MAX_IDLE = 3600   # stops on its own after 1h with no requests

BUTTONS = {
    "left": BUTTON_LEFT,
    "right": BUTTON_RIGHT,
    "middle": BUTTON_MIDDLE,
}

MODIFIERS = {
    "ctrl": MODIFIER_LEFT_CTRL,
    "shift": MODIFIER_LEFT_SHIFT,
    "alt": MODIFIER_LEFT_ALT,
    "gui": MODIFIER_LEFT_GUI,
    "win": MODIFIER_LEFT_GUI,
}

ACTION_NAMES = (
    "click", "move", "type_text", "press_key", "key_combo",
    "goto", "scroll", "capture_frame", "sleep",
    "wait_for_change", "wait_for_text", "find_image", "ocr_region",
    "screenshot_diff", "hid_reset", "expect", "check_state",
    "hid_info", "focus_window",
)

# Actions that, by their nature, abort the batch when they fail. An `expect`
# exists precisely to interrupt: letting the batch go on after an unsatisfied
# screen condition defeats its purpose.
#
# `goto` joined this list on 2026-11-06 after an incident on the rig: the goto
# to A34 did not land, the next line was typed from row 32, the formula
# "=SOMA(B32:F32)" landed on row 32 itself and created a circular reference.
# Excel's warning dialog then ate the keys, and the rest of the block came out
# shifted one column. A failed goto is not one step less: it is the whole rest
# of the batch typed in the wrong place.
ABORT_BY_DEFAULT = ("expect", "goto", "check_state", "focus_window")

# Actions that touch the target machine. These are the ones that get an
# automatic capture when the batch asks for `capture_each_step`: it is in them
# that a focus error becomes damage, and it is from them that I need the
# evidence afterward. `capture_frame` already saves on its own; `sleep` /
# `expect` changed nothing.
WRITE_ACTIONS = (
    "click", "type_text", "press_key", "key_combo", "goto", "scroll",
)


class ExpectationFailed(Exception):
    """An `expect` step's screen condition was not satisfied.

    Raised by execute_step; execute_steps treats it like any step error, but
    the `expect`'s implicit `required` aborts the rest of the batch.
    """


# ---------------------------------------------------------------------------
# request parsing / validation
# ---------------------------------------------------------------------------

def parse_request(data):
    """Validate the request JSON and return the list of steps.
    Raises ValueError with a clear message if the format is invalid."""
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object with a 'steps' key")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("'steps' must be a non-empty list of steps")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {i}: must be a JSON object")
        action = step.get("action")
        if action not in ACTION_NAMES:
            raise ValueError(
                f"step {i}: unknown action {action!r} (valid: {', '.join(ACTION_NAMES)})"
            )
        if "required" in step and not isinstance(step["required"], bool):
            raise ValueError(f"step {i}: 'required' must be true or false")
        if "frame" in step and not isinstance(step["frame"], bool):
            raise ValueError(f"step {i}: 'frame' must be true or false")
        if "secret" in step:
            # Refuse instead of ignore: a 'secret' that means nothing is worse
            # than none, because it gives the confidence of a guard that does
            # not exist -- and here what is lost is the password.
            if not isinstance(step["secret"], bool):
                raise ValueError(
                    f"step {i}: 'secret' must be true or false "
                    f"(got {step['secret']!r})")
            if step["secret"] and action != "type_text":
                raise ValueError(
                    f"step {i}: 'secret' only exists on type_text, and came "
                    f"on {action!r} -- there it would protect nothing")
        if action == "expect":
            _validate_screen_condition(step, f"step {i}: expect")
        if "verify" in step:
            spec = step["verify"]
            if not isinstance(spec, dict):
                raise ValueError(
                    f"step {i}: 'verify' must be an object with 'template' or 'text'"
                )
            if action == "expect":
                raise ValueError(
                    f"step {i}: 'verify' on an expect step is redundant "
                    f"(use two expect steps)"
                )
            if "required" in spec and not isinstance(spec["required"], bool):
                raise ValueError(f"step {i}: verify 'required' must be true or false")
            _validate_screen_condition(spec, f"step {i}: verify")
    return steps


def _validate_screen_condition(spec, where):
    """Validate the fields common to `expect` and the `verify` block."""
    has_template = isinstance(spec.get("template"), str) and spec["template"]
    has_text = isinstance(spec.get("text"), str) and spec["text"]
    if has_template and has_text:
        raise ValueError(f"{where} accepts 'template' OR 'text', not both")
    if not has_template and not has_text:
        raise ValueError(
            f"{where} requires 'template' (PNG, preferred) or 'text' (OCR)"
        )


def resolve_modifiers(names):
    """List of modifier names -> HID modifier byte."""
    modifier = 0
    for name in names or []:
        bit = MODIFIERS.get(str(name).lower())
        if bit is None:
            raise ValueError(
                f"unknown modifier {name!r} (valid: {', '.join(sorted(MODIFIERS))})"
            )
        modifier |= bit
    return modifier


def resolve_key(key):
    """A key name ('enter', 'f5', ...) or a single character -> (usage_id,
    base modifier required by the character itself, e.g. the shift of 'B')."""
    if not isinstance(key, str) or not key:
        raise ValueError("'key' must be a non-empty string")
    usage = named_key_to_usage(key)
    if usage is not None:
        return usage, 0
    if len(key) == 1:
        mapping = char_to_usage(key)
        if mapping is not None:
            return mapping
    raise ValueError(f"unknown key: {key!r}")


def _require_int(step, field):
    value = step.get(field)
    if not isinstance(value, (int, float)):
        raise ValueError(f"required field {field!r} missing or non-numeric")
    return int(value)


# ---------------------------------------------------------------------------
# daemon context: persistent CH9329 connection + cached capture device
# ---------------------------------------------------------------------------

class DaemonContext:
    """Holds the daemon's long-lived resources.

    - controller_factory: creates a connected CH9329Controller (or raises).
      The connection is created on demand and kept between requests;
      drop_controller() discards it after a serial error, so the next
      step/request reconnects.
    - capture device: opened on demand on the first capture_frame of a batch
      and closed at the end of the batch (release_capture), so it does not
      hold the device and block the user's capture_preview.py.
    - capture_fn(path): full OVERRIDE of the capture pipeline, used by the
      tests. When provided, the real HDMI capture device (_cap) is never
      opened; capture() delegates straight to it. In production (capture_fn
      omitted) capture() uses capture_frame_to_file with the cached capture
      device opened by _ensure_capture().
    """

    def __init__(self, controller_factory, capture_config=None, capture_fn=None):
        self._controller_factory = controller_factory
        self._controller = None
        self._reconnecting = False      # does the next creation release stuck keys?
        self._capture_config = capture_config
        self._capture_fn = capture_fn   # override for tests (see docstring)
        self._cap = None                # real HDMI capture device, cached

    def controller(self):
        if self._controller is None:
            self._controller = self._controller_factory()
            if self._controller is None:
                raise RuntimeError("controller_factory did not return a controller")
            if self._reconnecting:
                self._reconnecting = False
                self._release_stuck_keys()
        return self._controller

    def _release_stuck_keys(self):
        """Release any key stuck on the FRESHLY created connection.

        If a serial failure landed between keydown and keyup, the chip keeps
        holding the key; a stuck Ctrl/Win turns the following letters into
        shortcuts (Win+s opens Search in the middle of a text).
        CH9329Controller.reconnect() already does this, but the daemon does
        NOT reconnect by calling reconnect() -- it discards the controller
        (drop_controller) and recreates it via the factory. The release has to
        be HERE, in the recreation path, otherwise the protection sits in a
        method nothing calls. Best-effort: if the new connection is also bad,
        the release fails and the next step falls into the serial retry.
        """
        try:
            self._controller.release_all_keys()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "release_all_keys after reconnect failed (%s); continuing", exc)

    def drop_controller(self):
        if self._controller is not None:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None
            # The next controller creation is a RECONNECT: the new connection
            # should release stuck keys (see _release_stuck_keys).
            self._reconnecting = True

    def capture(self, output_path):
        if self._capture_fn is not None:
            return self._capture_fn(output_path)
        return capture_frame_to_file(output_path, cap=self._ensure_capture())

    def capture_array(self):
        """Capture a frame as a numpy array (without saving to disk). Used by
        find_image, ocr_region, wait_for_text, expect and check_state -- that
        is, by everything that DECIDES whether it can type.

        Delegates to read_fresh_frame: until 2026-11-08 this method had its
        own copy of the grab/read and so was left out of the stale-frame fix.
        Do not reimplement the read here."""
        return read_fresh_frame(self._ensure_capture())

    def _ensure_capture(self):
        if self._cap is None:
            config = self._capture_config or load_config()
            self._cap = open_configured_capture(config)
            if self._cap is None:
                raise RuntimeError("could not open the HDMI capture device")
        return self._cap

    def release_capture(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def close(self):
        self.drop_controller()
        self.release_capture()


# ---------------------------------------------------------------------------
# step execution
# ---------------------------------------------------------------------------

#: How long an `expect` re-checks before failing.
#:
#: It was 0.0 until 2026-11-07, that is: ONE read, at instant zero. On a rig
#: where the capture device serves an old frame -- which
#: docs/CAPTURE_VIDEO_BUFFER.md documents and this session saw again -- that
#: is the one configuration that cannot work. The case that caught it: right
#: after typing "PROBE ABNT2" in Notepad, the expect read an empty string and
#: aborted the batch; the text was on screen, and OCR of the same crop read it
#: correctly right after.
#:
#: At 2s with a 0.5s poll it is up to 5 reads. An expect that passes still
#: costs the time of one; only the one that would fail waits. An explicit
#: `timeout: 0` still gives a single read, for whoever wants it.
#:
#: MEASURED on the rig on 2026-11-08, already with the capture fixed: 10
#: cycles of "clear, type a marker, expect the marker" passed 10 of 10, and
#: the number of reads was 2 in NINE of them (1 in the other). So the old
#: default -- a single read at t=0 -- would have failed 9 of 10 times, with
#: the text on screen. With 2s/0.5s there is ~2.5x of headroom over the worst
#: measured case.
EXPECT_TIMEOUT_DEFAULT = 2.0

#: Interval between expect reads. See the measurement above: what fixes it is
#: RE-READING, and a re-read only helps if it is spaced out -- see
#: DISCARD_READS in capture_frame.py for why.
EXPECT_POLL_DEFAULT = 0.5

#: Reads measured as sufficient on the rig (10 of 10 in 2 or fewer). It is not
#: configuration: it is the number that justifies the timeout above, and it is
#: here so the test can require headroom over it.
EXPECT_ATTEMPTS_MEASURED = 2


def _run_expect(step, ctx):
    """Check a screen condition. Raises ExpectationFailed on failure.

    The `template` backend (cv2.matchTemplate) is preferred: it does not
    depend on an external binary. The `text` backend depends on Tesseract
    being installed, which may be absent even with pytesseract importable.
    """
    template = step.get("template")
    text = step.get("text")
    absent = bool(step.get("absent", False))
    timeout = max(0.0, float(step.get("timeout", EXPECT_TIMEOUT_DEFAULT) or 0.0))
    poll = max(0.05, float(step.get("poll", EXPECT_POLL_DEFAULT)
                           or EXPECT_POLL_DEFAULT))

    if template:
        path = template if os.path.isabs(template) else os.path.join(BASE_DIR, template)
        confidence = float(step.get("confidence", 0.85))
        what = "template %r (confidence >= %.2f)" % (os.path.basename(path), confidence)

        def probe():
            result = screen_utils.find_image_in_frame(
                ctx.capture_array(), path, confidence)
            return bool(result.get("found")), {
                "confidence": result.get("confidence"),
                "x": result.get("x"),
                "y": result.get("y"),
            }
    else:
        region = step.get("region")
        lang = step.get("lang")
        what = "text %r on screen" % text

        # An explicit `upscale` locks to a single scale; without it, it tries
        # several. For absent=True this is what makes the check honest: the
        # absence only holds if NO scale found the text. Finding it at any one
        # proves presence; not finding it at one proves nothing.
        scales = step.get("upscale")
        if scales is not None:
            scales = [int(scales)] if not isinstance(scales, (list, tuple)) \
                else [int(e) for e in scales]

        def probe():
            try:
                result = screen_utils.find_text_in_frame(
                    ctx.capture_array(), text, region=region, lang=lang,
                    scales=scales, numeric=bool(step.get("numeric")))
            except Exception as exc:
                # An OCR infrastructure error is not "condition not satisfied":
                # it must not become a silently false expect. Re-raise with the
                # explicit cause.
                if "tesseract" in f"{type(exc).__name__}{exc}".lower():
                    raise RuntimeError(
                        "expect by text requires Tesseract-OCR installed "
                        "(the pytesseract package alone is not enough): %s" % exc
                    ) from exc
                raise
            seen = result.get("text") or ""
            return bool(result.get("found")), {
                "text": seen,
                "upscale": result.get("upscale"),
                "upscales_tried": result.get("tried"),
            }

    deadline = time.monotonic() + timeout
    attempts = 0
    detail = {}
    while True:
        attempts += 1
        found, detail = probe()
        if found != absent:          # absent=False -> want found; absent=True -> want not-found
            out = {"expect_ok": True, "attempts": attempts}
            out.update({k: v for k, v in detail.items() if v is not None})
            return out
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)

    got = ""
    if "text" in detail:
        got = "; OCR read %r" % (detail["text"][:120])
    elif detail.get("confidence") is not None:
        got = "; best confidence was %.4f" % detail["confidence"]
    raise ExpectationFailed(
        "expected %s %s after %.1fs (%d attempt(s))%s"
        % (what, "ABSENT" if absent else "present", timeout, attempts, got)
    )


GOTO_VERIFY_TIMEOUT = 2.5
GOTO_VERIFY_POLL = 0.5

_REF_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)")


def expected_landing_cell(ref):
    """The cell the Name Box should show after a `goto` to `ref`.

    For a range ("A1:C10") Excel selects the range but the ACTIVE cell -- the
    one the Name Box displays -- is the first. Refs that are not coordinates
    (a defined name, for example) return None: there the text cannot be
    predicted, and checking would be worse than not checking.
    """
    match = _REF_RE.match((ref or "").split(":")[0].strip())
    if not match:
        return None
    return "%s%s" % (match.group(1).upper(), match.group(2))


def _verify_goto_landing(ref, step, ctx):
    """Confirm, from the Name Box, that the `goto` stopped where asked.

    With pixels alone, this is the only evidence that the F5 worked. Without
    it a goto swallowed by a modal dialog is invisible, and the whole rest of
    the batch is typed from the wrong cell.
    """
    expected = expected_landing_cell(ref)
    if expected is None:
        return {"landed": None, "checked": False, "reason": "non-coordinate ref"}

    region = step.get("name_box_region")
    deadline = time.monotonic() + float(
        step.get("verify_timeout", GOTO_VERIFY_TIMEOUT))
    seen = None
    attempts = 0
    while True:
        attempts += 1
        try:
            seen = screen_utils.read_name_box(ctx.capture_array(), region=region)
        except Exception as exc:  # noqa: BLE001
            # With no OCR, or no capture, it CANNOT be checked -- and that is
            # different from "I checked and it is wrong". Aborting here would
            # let an unstable capture card, or a machine without Tesseract,
            # bring down the whole batch. It goes on, but the response records
            # checked=False: an unchecked goto stays auditable instead of
            # passing for checked.
            logger.warning(
                "goto to %r could NOT be verified (%s: %s); continuing without "
                "checking the position", ref, type(exc).__name__, exc)
            return {"landed": None, "checked": False,
                    "reason": "%s: %s" % (type(exc).__name__, exc)}
        if seen == expected:
            return {"landed": seen, "checked": True, "attempts": attempts}
        if seen and screen_utils.confusable_key(seen) == \
                screen_utils.confusable_key(expected):
            # Same cell, read with a confused glyph ("A42" -> "AA2"). Recorded
            # as checked WITH a caveat, so it does not hide that the read was
            # not clean.
            return {"landed": seen, "checked": True, "attempts": attempts,
                    "reason": "read %r equals %r under OCR confusion"
                              % (seen, expected)}
        if time.monotonic() >= deadline:
            break
        time.sleep(GOTO_VERIFY_POLL)

    if seen == "":
        # Blank Name Box: Excel is in cell-edit mode, and there F5 does not
        # even navigate. It is POSITIVE evidence of a bad state, not a lack of
        # evidence -- aborting is the right call.
        raise ExpectationFailed(
            "goto to %r did not work: the Name Box is EMPTY, which in Excel "
            "means cell-edit mode (F5 does not navigate in that state). Send "
            "an `esc` first. (%d attempt(s))"
            % (ref, attempts))

    if seen is None:
        # There was text, but OCR did not decode it. This is NOT proof of
        # being in the wrong place -- it is a lack of proof. Aborting here
        # would let OCR fragility bring down correct batches; continuing with
        # checked=False leaves the fact recorded in the response.
        logger.warning(
            "goto to %r: could not READ the Name Box (%d attempt(s)); "
            "continuing without confirming the position", ref, attempts)
        return {"landed": None, "checked": False,
                "reason": "unreadable Name Box"}

    raise ExpectationFailed(
        "goto to %r did not land: the Name Box shows %r and not %r "
        "(%d attempt(s)). Typing from here would write in the wrong place, so "
        "the batch stops." % (ref, seen, expected, attempts))


def execute_step(step, ctx, default_frame_name, frames_dir):
    """Execute ONE step. Returns an extra dict for the result (e.g.
    frame_path) or None. Raises on failure."""
    action = step["action"]

    if action == "sleep":
        seconds = step.get("seconds")
        if not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError("'seconds' must be a number >= 0")
        time.sleep(min(float(seconds), MAX_SLEEP_SECONDS))
        return None

    if action == "capture_frame":
        path = step.get("path") or default_frame_name
        if not os.path.isabs(path):
            path = os.path.join(frames_dir, path)
        saved = ctx.capture(path)
        return {"frame_path": saved}

    # Before opening the serial port: `expect` only looks at the screen. It
    # must not require the CH9329 connected nor fail because of it.
    if action == "expect":
        return _run_expect(step, ctx)

    controller = ctx.controller()

    if action == "click":
        x, y = _require_int(step, "x"), _require_int(step, "y")
        button_name = str(step.get("button", "left")).lower()
        if button_name not in BUTTONS:
            raise ValueError(f"unknown button {button_name!r} (valid: {', '.join(BUTTONS)})")
        monitor2.click_absolute_mon2(controller, x, y, button=BUTTONS[button_name])
        return None

    if action == "move":
        x, y = _require_int(step, "x"), _require_int(step, "y")
        monitor2.move_absolute_mon2(controller, x, y)
        return None

    if action == "scroll":
        amount = _require_int(step, "amount")
        amount = max(-127, min(127, amount))
        x = _require_int(step, "x") if "x" in step else monitor2.MON2_W // 2
        y = _require_int(step, "y") if "y" in step else monitor2.MON2_H // 2
        monitor2.move_absolute_mon2(controller, x, y, wheel=amount)
        return None

    if action == "check_state":
        # Classify the target screen from TWO samples. With require_typable,
        # it refuses the batch if the state does not accept the keyboard --
        # the guard that was missing when I asserted twice that the screen
        # was locked from a single frame (LEARNINGS 35).
        result = target_state.sample(
            ctx.capture_array,
            samples=int(step.get("samples", 2)),
            interval=float(step.get("interval", 1.5)),
            lang=step.get("lang", "eng"))
        if step.get("require_typable") and not target_state.can_type(result):
            raise ExpectationFailed(
                "target screen in %s (samples: %s) -- not a state to type "
                "in. APP to work, LOCK_PASSWORD for the password; in the "
                "others the keyboard goes nowhere, or to the window that "
                "appears when the signal comes back."
                % (result["state"], result["per_frame"]))
        return {"state": result["state"],
                "agree": result["agree"],
                "per_frame": result["per_frame"]}

    if action == "type_text":
        text = step.get("text")
        if not isinstance(text, str):
            raise ValueError("required field 'text' missing or non-string")
        if step.get("secret"):
            _require_password_screen(step, ctx)
        char_delay = step.get("char_delay", DEFAULT_CHAR_DELAY)
        controller.type_text(text, char_delay=char_delay)
        return None

    if action in ("press_key", "key_combo"):
        usage, base_modifier = resolve_key(step.get("key"))
        modifier = base_modifier | resolve_modifiers(step.get("modifiers"))
        hold = step.get("hold", 0.0)
        controller.key_press(usage, modifier=modifier, hold_seconds=hold)
        return None

    if action == "goto":
        ref = step.get("ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("required field 'ref' missing or empty")
        delay = step.get("delay", DEFAULT_GOTO_DELAY)
        controller.press_named_key("f5")
        time.sleep(delay)
        controller.type_text(ref, char_delay=DEFAULT_CHAR_DELAY)
        controller.press_named_key("enter")
        # short pause for the "Go To" box to close before the next step starts
        # sending keys -- without it, a following step fired too quickly can
        # have keys swallowed/mixed by the focus transition (observed
        # empirically: goto+type_text chained without this pause produce wrong
        # entries in the Go To box itself).
        time.sleep(GOTO_SETTLE_SECONDS)
        if step.get("verify_position", True):
            return _verify_goto_landing(ref, step, ctx)
        return None

    if action == "wait_for_change":
        timeout = float(step.get("timeout", 10.0))
        threshold = float(step.get("threshold", 3.0))
        region = step.get("region")
        settle_ms = int(step.get("settle_ms", 300))
        cap = ctx._ensure_capture()
        return screen_utils.wait_for_change(
            cap, flush_frames=FLUSH_FRAMES, threshold=threshold,
            timeout=timeout, region=region, settle_ms=settle_ms,
        )

    if action == "wait_for_text":
        text_contains = step.get("text")
        if not isinstance(text_contains, str) or not text_contains:
            raise ValueError("'text' field required for wait_for_text")
        timeout = float(step.get("timeout", 10.0))
        region = step.get("region")
        lang = step.get("lang")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = ctx.capture_array()
            ocr = screen_utils.ocr_region_from_frame(frame, region=region, lang=lang)
            if text_contains.lower() in ocr["text"].lower():
                return {"found": True, "text": ocr["text"]}
            time.sleep(0.5)
        return {"found": False, "text": ""}

    if action == "find_image":
        template = step.get("template")
        if not isinstance(template, str) or not template:
            raise ValueError("'template' field required for find_image")
        if not os.path.isabs(template):
            template = os.path.join(BASE_DIR, template)
        confidence = float(step.get("confidence", 0.85))
        do_click = bool(step.get("click", False))
        frame = ctx.capture_array()
        result = screen_utils.find_image_in_frame(frame, template, confidence)
        if result["found"] and do_click:
            monitor2.click_absolute_mon2(ctx.controller(), result["x"], result["y"],
                                         button=BUTTON_LEFT)
        return result

    if action == "ocr_region":
        region = step.get("region")
        lang = step.get("lang")
        frame = ctx.capture_array()
        result = screen_utils.ocr_region_from_frame(frame, region=region, lang=lang)
        if "save_as" in step:
            result["save_as"] = step["save_as"]
        return result

    if action == "screenshot_diff":
        before = step.get("before")
        after = step.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            raise ValueError("'before' and 'after' fields required for screenshot_diff")
        if not os.path.isabs(before):
            before = os.path.join(frames_dir, before)
        if not os.path.isabs(after):
            after = os.path.join(frames_dir, after)
        return screen_utils.screenshot_diff(before, after)

    if action == "hid_reset":
        ctx.controller().chip_reset()
        return None

    if action == "focus_window":
        return _focus_window(step, ctx)

    if action == "hid_info":
        return ctx.controller().lock_state()

    raise ValueError(f"unknown action: {action!r}")  # defensive; parse already blocks it


def _resolve_template(path, field):
    if not isinstance(path, str) or not path:
        raise ValueError("field %r required" % field)
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def _focus_window(step, ctx):
    """Bring a window to the front, without minimizing the one already there.

    The order matters and is the whole point of this action: LOOK BEFORE YOU
    CLICK. Clicking the taskbar icon of a window that is already focused
    minimizes it -- the click is a toggle, not a "bring to front". On
    2026-11-19 a batch of mine did exactly that and knocked down the WhatsApp
    the user had left ready on screen.

    Locating the icon by image (icon_template) is preferable to a fixed
    coordinate: the taskbar reorders as apps open and close, and on the same
    day the WhatsApp icon moved from x=876 to 898.
    """
    template = _resolve_template(step.get("template"), "template")
    confidence = float(step.get("confidence", 0.85))
    timeout = max(0.0, float(step.get("timeout", 8.0) or 0.0))
    poll = max(0.05, float(step.get("poll", EXPECT_POLL_DEFAULT)))

    found = screen_utils.find_image_in_frame(ctx.capture_array(), template, confidence)
    if found.get("found"):
        return {"already_fronted": True, "clicked": False,
                "confidence": found.get("confidence")}

    icon = step.get("icon_template")
    if icon:
        target = screen_utils.find_image_in_frame(
            ctx.capture_array(), _resolve_template(icon, "icon_template"),
            float(step.get("icon_confidence", confidence)))
        if not target.get("found"):
            raise ExpectationFailed(
                "focus_window: could not find the icon %s on the taskbar "
                "(best confidence %.4f). The window was not in front either, "
                "so there is nowhere safe to click."
                % (icon, target.get("confidence") or -1))
        x, y = target["x"], target["y"]
    else:
        if step.get("x") is None or step.get("y") is None:
            raise ValueError("focus_window needs icon_template or x and y")
        x, y = int(step["x"]), int(step["y"])

    monitor2.click_absolute_mon2(ctx.controller(), x, y, button=BUTTON_LEFT)

    deadline = time.time() + timeout
    best = -1.0
    while True:
        r = screen_utils.find_image_in_frame(ctx.capture_array(), template, confidence)
        best = max(best, float(r.get("confidence") or -1))
        if r.get("found"):
            return {"already_fronted": False, "clicked": True, "x": x, "y": y,
                    "confidence": r.get("confidence")}
        if time.time() >= deadline:
            break
        time.sleep(poll)
    raise ExpectationFailed(
        "focus_window: clicked at (%d,%d) and the window did not come to the "
        "front in %.1fs (best confidence %.4f)" % (x, y, timeout, best))


def _require_password_screen(step, ctx):
    """Refuse the step if the target screen is not the password one.

    Guard for `type_text` with "secret": true. It exists because on
    2026-11-08 I myself built a batch that read LOCK_PHOTO -- a state that
    can_type() REFUSES -- and typed the password right after, because nothing
    forced a look. It worked by luck: the previous click had brought the panel
    back.

    The risk is not symmetric with the already-known case (any text landing in
    the password field, which the module docstring records): text lost in a
    password field vanishes, a PASSWORD lost in some window leaks -- into a
    document, a chat, a search bar.

    Why it requires LOCK_PASSWORD and not `can_type`: can_type also accepts
    APP, and an application window is exactly where the password must not land.

    Fail-closed throughout: disagreeing samples (UNDETERMINED) refuse, and a
    classification error bubbles up as a step error -- never "when in doubt,
    type".
    """
    result = target_state.sample(
        ctx.capture_array,
        samples=int(step.get("samples", 2)),
        interval=float(step.get("interval", 1.5)),
        lang=step.get("lang", "eng"))
    if not result.get("agree"):
        raise ExpectationFailed(
            "secret type_text refused: the samples disagreed (%s). A screen "
            "in transition is no place to type a password."
            % (result["per_frame"],))
    if result["state"] != target_state.LOCK_PASSWORD:
        raise ExpectationFailed(
            "secret type_text refused: target screen in %s, and only "
            "LOCK_PASSWORD is accepted. The password would go to whichever "
            "window had focus. (samples: %s)"
            % (result["state"], result["per_frame"]))


def has_secret_step(steps):
    """Does the request carry any password? Used to avoid archiving it."""
    return any(isinstance(s, dict) and s.get("secret") for s in (steps or []))


def step_is_required(step):
    """Does a step abort the batch if it fails?

    An explicit `required` rules. Without it, only the ABORT_BY_DEFAULT
    actions (today: `expect`) abort -- the rest keep the historical behavior
    of going on, so already-written requests do not break.
    """
    if "required" in step:
        return bool(step["required"])
    # A refused secret type_text MUST abort the batch: if the following steps
    # ran, the unlock `Enter` would submit the empty field and burn one of the
    # three password attempts.
    if step.get("action") == "type_text" and step.get("secret"):
        return True
    return step.get("action") in ABORT_BY_DEFAULT


def _verify_spec(step):
    """The step's `verify` block, normalized as an `expect` step.

    `verify` is the action's POST-condition: it runs after the action and asks
    "did the screen change the way this action was supposed to change it?". It
    is the only check that catches the failure class where the daemon sends
    the key, the chip confirms, and nothing happens on the target machine (an
    `Enter` that lands outside the compose field, for example). No
    pre-condition `expect` catches this: before the action the screen was
    correct.
    """
    spec = step.get("verify")
    if not isinstance(spec, dict):
        return None
    normalized = dict(spec)
    normalized["action"] = "expect"
    return normalized


def _wants_step_frame(step, capture_each_step):
    """Save an automatic PNG after this step?

    An explicit `frame` on the step rules. Without it the batch default
    applies, and only for the WRITE_ACTIONS: `capture_frame` already saves on
    its own and `sleep` / `expect` did not change the screen.
    """
    if "frame" in step:
        return bool(step["frame"])
    if not capture_each_step:
        return False
    return step.get("action") in WRITE_ACTIONS


DEFAULT_FRAMES_MAX_MB = 100
KEEP_SUBDIR = "keep"


def prune_frames(frames_dir, keep=0, max_bytes=0):
    """Delete the oldest PNGs in frames_dir until they fit the limits.

    Two caps, both optional and applied together (the tighter one wins):
      keep       maximum number of PNGs
      max_bytes  maximum summed size of the PNGs

    With per-step capture a 6-action send produces ~5 MB; without pruning the
    directory only grows, and it holds captures of the target screen (private
    content).

    It does NOT descend into subdirectories. That is how `queue/frames/keep/`
    works: a frame moved there is never pruned. It is where the frames that
    serve as cited evidence or as a corpus to validate a template live --
    deleting those by size would throw away precisely the measurement one
    wants to redo.

    Returns the list of removed paths, oldest to newest.
    """
    keep = max(0, int(keep or 0))
    max_bytes = max(0, int(max_bytes or 0))
    if not keep and not max_bytes:
        return []
    try:
        entries = []
        for name in os.listdir(frames_dir):
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(frames_dir, name)
            if not os.path.isfile(path):
                continue
            entries.append(path)
    except OSError:
        return []
    if not entries:
        return []

    # Newest first; a missing mtime (file disappearing) goes to the end and is
    # therefore the first candidate for pruning.
    entries.sort(key=_safe_mtime, reverse=True)

    doomed = []
    running = 0
    for i, path in enumerate(entries):
        if keep and i >= keep:
            doomed.append(path)
            continue
        running += _safe_size(path)
        # i > 0: the newest frame is never pruned by size. If a single PNG
        # already blows the cap, emptying the whole directory would lose
        # precisely the most useful frame -- the cap yields, the last frame
        # stays.
        if max_bytes and running > max_bytes and i > 0:
            doomed.append(path)
    if not doomed:
        return []

    removed = []
    for path in reversed(doomed):     # oldest to newest
        try:
            os.remove(path)
            removed.append(path)
        except OSError as exc:
            logger.warning("could not prune %s: %s", path, exc)
    if removed:
        logger.info(
            "frame pruning: %d removed, %d kept (cap: %s%s%s)",
            len(removed), len(entries) - len(removed),
            f"{keep} files" if keep else "",
            " and " if keep and max_bytes else "",
            f"{max_bytes / (1024 * 1024):.0f} MB" if max_bytes else "")
    return removed


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def request_capture_each_step(data, default=False):
    """Read the `capture_each_step` flag from the request; fall back to the
    daemon default."""
    if isinstance(data, dict) and "capture_each_step" in data:
        return bool(data["capture_each_step"])
    return bool(default)


LOCK_NAME = "daemon.lock"
LOCK_OFFSET = 1 << 20  # see acquire_queue_lock: far from the PID written at the start


class AlreadyRunning(RuntimeError):
    """Another daemon is already serving this queue."""


def acquire_queue_lock(queue_dir):
    """Lock the queue for ONE daemon. Returns the open file (do not close it:
    it is ownership of the lock) or raises AlreadyRunning.

    Two daemons on the same queue and the same serial port is a silent race:
    both see the same request, one moves the file out from under the other,
    and the bytes of the two batches interleave on the 9600 bps line. The
    result is not an error, it is text typed halfway -- the same damage class
    as the wrong ABNT2 usage.

    The lock is the OPERATING SYSTEM's, which is why there is no stale lock: if
    the daemon dies in any way (crash, kill, power cut), the handle closes and
    the region is freed on its own. A PID file would require checking whether
    the PID still lives, and on Windows `os.kill(pid, 0)` calls
    TerminateProcess -- the check would kill the process it is checking.
    """
    if not os.path.isdir(queue_dir):
        os.makedirs(queue_dir, exist_ok=True)
    path = os.path.join(queue_dir, LOCK_NAME)
    handle = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            # Lock one byte WAY AT THE END, far from the text: on Windows the
            # locked region is unreadable for everyone, and locking byte 0
            # would make `cat queue/daemon.lock` give "Permission denied" --
            # hiding precisely the PID the file exists to show.
            handle.seek(LOCK_OFFSET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise AlreadyRunning(
            "another daemon is already serving %s (lock: %s). Two daemons on "
            "the same queue contend for the same request and the same serial "
            "port; close the other before starting this one." % (queue_dir, path)) from exc
    handle.seek(0)
    handle.truncate()
    handle.write("%d\n" % os.getpid())
    handle.flush()
    return handle


def unverified_in_steps(steps):
    """[(index, [characters]), ...] for each type_text in the batch that
    carries a character whose ABNT2 mapping is inferred and never measured.

    Empty = the batch can be typed.
    """
    found = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("action") != "type_text":
            continue
        text = step.get("text")
        if not isinstance(text, str):
            continue
        chars = unverified_chars(text)
        if chars:
            found.append((i, chars))
    return found


def execute_steps(steps, ctx, request_stem, frames_dir=None,
                  capture_each_step=False):
    """Execute a batch. Never raises: each step becomes a result
    {'index', 'action', 'status', ...}.

    By default a step error does NOT stop the following ones. The exception is
    a `required` step (implicit in `expect`): on failure, the remaining steps
    are not executed and are left with status 'skipped'. That is what lets you
    chain "check the screen -> type" in a single request without risking
    typing in the wrong window if the check fails.

    Each step can also carry:
      - `verify`: a screen post-condition, checked AFTER the action. A failure
        aborts the batch (default), because an action that did not have the
        expected effect invalidates everything after it.
      - `frame`: turns the automatic capture of that step on/off; without it
        `capture_each_step` applies, for the write actions.

    A serial error discards the connection and retries the step once with a
    fresh connection. Returns (overall_ok, list_of_results)."""
    if frames_dir is None:
        frames_dir = os.path.join(QUEUE_DIR, "frames")

    # Refuse the WHOLE batch before the first key if any type_text has a
    # character with an unmeasured mapping. Stopping halfway is the worst
    # outcome: half a formula stays in a cell as text, and the next step keeps
    # typing on top of it.
    pending = unverified_in_steps(steps)
    if pending:
        detail = "; ".join(
            "step %d: %s" % (i, " ".join(repr(c) for c in chars))
            for i, chars in pending)
        logger.error("batch refused without typing anything -- unverified "
                     "ABNT2 character (%s)", detail)
        reason = ("batch refused before typing: a character with an inferred "
                  "ABNT2 mapping, never measured on the rig (%s). Run "
                  "probe_punctuation.py or rewrite the text." % detail)
        return False, [{
            "index": i,
            "action": step.get("action", "?") if isinstance(step, dict) else "?",
            "status": "skipped",
            "reason": reason,
        } for i, step in enumerate(steps)]

    results = []
    aborted_at = None
    try:
        for i, step in enumerate(steps):
            action = step.get("action", "?")
            if aborted_at is not None:
                results.append({
                    "index": i, "action": action, "status": "skipped",
                    "reason": f"batch aborted at step {aborted_at}",
                })
                continue
            default_frame = f"{request_stem}_step{i}.png"
            result = {"index": i, "action": action, "status": "ok"}
            must_abort = False
            try:
                extra = _run_step_with_serial_retry(step, ctx, default_frame, frames_dir)
                if extra:
                    result.update(extra)
            except Exception as exc:  # noqa: BLE001 - per-step resilience
                result["status"] = "error"
                result["error"] = f"{type(exc).__name__}: {exc}"
                logger.warning("step %d (%s) failed: %s", i, action, result["error"])
                must_abort = step_is_required(step)
            else:
                # Capture first, post-condition after: if the verify fails, the
                # PNG I will look at is the one of the state that failed it.
                if _wants_step_frame(step, capture_each_step):
                    try:
                        result["frame_path"] = ctx.capture(
                            os.path.join(frames_dir, default_frame))
                    except Exception as exc:  # noqa: BLE001
                        # Capture is evidence, not a result: a failure here does
                        # not invalidate an action that succeeded.
                        result["frame_error"] = f"{type(exc).__name__}: {exc}"
                        logger.warning(
                            "automatic capture of step %d failed (%s); continuing",
                            i, exc)
                spec = _verify_spec(step)
                if spec is not None:
                    try:
                        result["verify"] = _run_expect(spec, ctx)
                    except Exception as exc:  # noqa: BLE001
                        result["status"] = "error"
                        result["error"] = f"{type(exc).__name__}: {exc}"
                        result["verify_failed"] = True
                        logger.warning(
                            "post-condition of step %d (%s) was not satisfied: %s",
                            i, action, result["error"])
                        must_abort = bool(spec.get("required", True))
            if must_abort:
                result["aborted_batch"] = True
                aborted_at = i
                logger.error(
                    "step %d (%s) was required and failed: aborting the batch; "
                    "the following steps will NOT run", i, action)
            results.append(result)
    finally:
        ctx.release_capture()
    ok = all(r["status"] == "ok" for r in results)
    return ok, results


def _run_step_with_serial_retry(step, ctx, default_frame_name, frames_dir):
    try:
        return execute_step(step, ctx, default_frame_name, frames_dir)
    except PartialTypeError as exc:
        # NEVER re-run the whole step here: part of the text is already in the
        # destination field and resending everything concatenates (a correct
        # password becomes a wrong one). Resend only what is left.
        logger.warning(
            "serial error after %d/%d characters of the type_text (%s); "
            "reconnecting and sending only the rest",
            exc.typed, len(exc.text), exc.original)
        ctx.drop_controller()
        if not exc.remaining:
            return None
        # It can only be resumed when the text comes from the step's "text"
        # field. Other actions also type internally (goto types the cell
        # reference): there is nowhere to inject the rest, and re-running the
        # step would retype everything. In that case it fails explicitly
        # instead of duplicating.
        if step.get("action") != "type_text":
            logger.error(
                "serial error in the middle of the internal typing of '%s' after "
                "%d/%d characters; I will NOT re-run the step (it would "
                "duplicate the text). Check the screen before resending.",
                step.get("action"), exc.typed, len(exc.text))
            raise
        resumed = dict(step)
        resumed["text"] = exc.remaining
        try:
            return execute_step(resumed, ctx, default_frame_name, frames_dir)
        except serial.SerialException:
            ctx.drop_controller()
            raise
    except serial.SerialException as exc:
        logger.warning("serial error (%s); reconnecting and retrying the step", exc)
        ctx.drop_controller()
        try:
            return execute_step(step, ctx, default_frame_name, frames_dir)
        except serial.SerialException:
            ctx.drop_controller()
            raise


# ---------------------------------------------------------------------------
# file queue
# ---------------------------------------------------------------------------

def _write_json_atomic(path, payload):
    # ensure_ascii=False is safe here: the file is written in UTF-8 and the
    # only consumer is the operator reading via a JSON parser (which accepts
    # UTF-8 by definition); it keeps messages with accents/symbols readable
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def process_request_file(request_path, ctx, responses_dir, processed_dir,
                         processing_dir, failed_dir, frames_dir=None,
                         capture_each_step=False):
    """Process a request file and write the response with the same name.

    Maildir flow:
      requests/ --(atomic move)--> processing/ --(after execution)--> processed/
                                               --(error/invalid)----> failed/

    Returns False if the file seems to still be written (invalid and recent
    JSON, returned to requests/). Returns True in the other cases (consumed
    successfully or with an error response)."""
    name = os.path.basename(request_path)
    stem = os.path.splitext(name)[0]

    # Move to processing/ atomically -- prevents double-processing if the
    # watchdog event fires twice for the same file.
    processing_path = os.path.join(processing_dir, name)
    try:
        os.replace(request_path, processing_path)
    except OSError:
        logger.debug("request %s already moved or removed; ignoring", name)
        return True

    started = datetime.now().isoformat(timespec="seconds")

    # Order of the excepts matters: JSONDecodeError is a subclass of
    # ValueError, but gets the same tolerance window as an IO error (the file
    # is probably still being written). A plain ValueError (valid JSON with a
    # wrong schema, from parse_request) gets no tolerance.
    try:
        with open(processing_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        steps = parse_request(data)
    except (json.JSONDecodeError, OSError) as exc:
        if time.time() - _safe_mtime(processing_path) < PARSE_GRACE_SECONDS:
            # Probably still being written; return it to requests/ to try
            # again on the next scan or watchdog event.
            try:
                os.replace(processing_path, request_path)
            except OSError:
                pass
            return False
        return _consume_invalid_request(processing_path, name, started, exc,
                                        responses_dir, failed_dir)
    except ValueError as exc:
        return _consume_invalid_request(processing_path, name, started, exc,
                                        responses_dir, failed_dir)

    per_step_frames = request_capture_each_step(data, capture_each_step)
    logger.info("processing %s (%d steps%s)", name, len(steps),
                ", per-step capture" if per_step_frames else "")
    ok, results = execute_steps(steps, ctx, stem, frames_dir=frames_dir,
                                capture_each_step=per_step_frames)
    response = {
        "request": name,
        "ok": ok,
        "started_at": started,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "steps": results,
    }
    _finish_request(processing_path, processed_dir,
                    secret=has_secret_step(steps))
    _write_json_atomic(os.path.join(responses_dir, name), response)
    logger.info("%s finished ok=%s", name, ok)
    return True


def _consume_invalid_request(processing_path, name, started, exc,
                              responses_dir, failed_dir):
    """Move an invalid request to failed/ and write an error response."""
    logger.error("request %s invalid: %s", name, exc)
    response = {
        "request": name,
        "ok": False,
        "error": f"invalid request: {exc}",
        "started_at": started,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "steps": [],
    }
    _finish_request(processing_path, failed_dir)
    _write_json_atomic(os.path.join(responses_dir, name), response)
    return True


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _finish_request(request_path, processed_dir, secret=False):
    """Move the request to processed/ (or delete it, if the move fails).

    With secret=True it does NOT archive: it deletes. A request with a
    password inside, archived in processed/, leaves the password in cleartext
    on the project's disk for an indefinite time. Until 2026-11-08 this
    depended on me remembering to delete it by hand after each unlock -- and
    depending on my memory not to leak a password is not protection, it is
    luck.
    """
    if secret:
        try:
            os.remove(request_path)
            logger.info("request with a secret step deleted instead of archived")
        except OSError:
            logger.error("could NOT delete %s, which contains a secret: "
                         "delete it by hand", request_path)
        return
    try:
        os.replace(request_path, os.path.join(processed_dir, os.path.basename(request_path)))
    except OSError:
        try:
            os.remove(request_path)
        except OSError:
            logger.warning("could not remove %s", request_path)


def ensure_queue_dirs(queue_dir):
    requests_dir   = os.path.join(queue_dir, "requests")
    responses_dir  = os.path.join(queue_dir, "responses")
    processed_dir  = os.path.join(queue_dir, "processed")
    processing_dir = os.path.join(queue_dir, "processing")
    failed_dir     = os.path.join(queue_dir, "failed")
    frames_dir     = os.path.join(queue_dir, "frames")
    for d in (requests_dir, responses_dir, processed_dir,
              processing_dir, failed_dir, frames_dir):
        os.makedirs(d, exist_ok=True)
    return requests_dir, responses_dir, processed_dir, processing_dir, failed_dir, frames_dir


def pending_requests(requests_dir):
    """Pending requests, in alphabetical order (use prefixes 001_, 002_...)."""
    try:
        names = os.listdir(requests_dir)
    except OSError:
        return []
    return sorted(
        os.path.join(requests_dir, n)
        for n in names
        if n.lower().endswith(".json") and not n.startswith((".", "_"))
    )


FALLBACK_SCAN_INTERVAL = 5.0  # periodic safety scan (seconds)


def nudge_mouse(ctx):
    """Minimal mouse movement: 1px to the right and back.

    Used by the keep-alive. Relative on purpose -- it does not need to know
    where the cursor is and does not reposition it, so it does not ruin a
    hover nor change focus (there is no click). Never raises: the keep-alive
    must never bring down the loop.
    """
    try:
        controller = ctx.controller()
        controller.move_relative(1, 0)
        controller.move_relative(-1, 0)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("keep-alive failed (%s); continuing", exc)
        ctx.drop_controller()
        return False


def main_loop(ctx, queue_dir=QUEUE_DIR, poll_interval=POLL_INTERVAL,
              keep_alive_seconds=0, keep_alive_max_idle=KEEP_ALIVE_MAX_IDLE,
              capture_each_step=False, frames_keep=0,
              frames_max_bytes=DEFAULT_FRAMES_MAX_MB * 1024 * 1024):
    """Main loop: watches queue/requests until queue/stop appears.

    If watchdog is installed, it uses filesystem events (no active polling).
    Otherwise it polls every poll_interval seconds. In both cases a fallback
    scan runs every FALLBACK_SCAN_INTERVAL seconds to catch files that events
    may have missed (e.g. daemon restarted with pending requests).

    keep_alive_seconds > 0 turns the keep-alive on: every N IDLE seconds the
    daemon nudges the mouse 1px, so the screen does not re-lock (it locks in
    ~5 min with no activity and that already caused an accident -- see
    docs/SCREEN_UNLOCK.md). It stays INSIDE the loop on purpose: that way it
    never fires in the middle of a request's steps, unlike an external process
    that enqueues requests.

    keep_alive_max_idle bounds the damage: after that time with NO request, the
    keep-alive stops on its own and the screen re-locks. Keeping the machine
    unlocked indefinitely would mean turning off a protection with nobody
    around to notice.
    """
    (requests_dir, responses_dir, processed_dir,
     processing_dir, failed_dir, frames_dir) = ensure_queue_dirs(queue_dir)
    stop_path = os.path.join(queue_dir, "stop")

    event_queue = _stdlib_queue.Queue()
    observer = None

    if _WATCHDOG_OK:
        handler = _RequestWatcher(event_queue)
        observer = _Observer()
        observer.schedule(handler, requests_dir, recursive=False)
        observer.start()
        logger.info("daemon started with watchdog; watching %s", requests_dir)
    else:
        logger.info(
            "daemon started (polling every %.1fs); "
            "install 'watchdog' for instant events. Watching %s",
            poll_interval, requests_dir,
        )

    # Initial scan: catch requests that arrived while the daemon was down
    for path in pending_requests(requests_dir):
        event_queue.put(path)

    last_scan = time.monotonic()
    last_request = time.monotonic()
    last_nudge = time.monotonic()
    keep_alive_expired = False

    if keep_alive_seconds > 0:
        logger.info("keep-alive on: 1px of mouse every %ds idle, "
                    "stopping after %ds with no requests",
                    keep_alive_seconds, keep_alive_max_idle)

    def _process_event(path):
        if not (os.path.isfile(path) and path.lower().endswith(".json")):
            return
        try:
            process_request_file(path, ctx, responses_dir, processed_dir,
                                 processing_dir, failed_dir, frames_dir=frames_dir,
                                 capture_each_step=capture_each_step)
            prune_frames(frames_dir, keep=frames_keep,
                         max_bytes=frames_max_bytes)
        except Exception:  # noqa: BLE001 - the loop must never die
            logger.exception("unexpected error processing %s", path)
            _finish_request(path, failed_dir)

    try:
        while True:
            # Drain the event queue (watchdog or polling)
            while True:
                try:
                    path = event_queue.get_nowait()
                except _stdlib_queue.Empty:
                    break
                _process_event(path)
                # Reset both keep-alive clocks: there was real activity, so the
                # screen is alive and the idle deadline resets.
                last_request = last_nudge = time.monotonic()
                keep_alive_expired = False

            # Periodic fallback scan
            if time.monotonic() - last_scan >= FALLBACK_SCAN_INTERVAL:
                for path in pending_requests(requests_dir):
                    event_queue.put(path)
                last_scan = time.monotonic()

            # Keep-alive: only when idle (the queue was already drained above)
            # and only within the allowed idle window.
            if keep_alive_seconds > 0 and not keep_alive_expired:
                now = time.monotonic()
                if now - last_request >= keep_alive_max_idle:
                    keep_alive_expired = True
                    logger.info(
                        "keep-alive expired: %ds with no requests. The screen "
                        "will re-lock normally.", keep_alive_max_idle)
                elif now - last_nudge >= keep_alive_seconds:
                    if nudge_mouse(ctx):
                        logger.debug("keep-alive: mouse moved")
                    last_nudge = now

            if os.path.exists(stop_path):
                try:
                    os.remove(stop_path)
                except OSError:
                    pass
                logger.info("stop file found; shutting down.")
                return

            time.sleep(poll_interval if not _WATCHDOG_OK else 0.05)
    finally:
        if observer is not None:
            observer.stop()
            observer.join()


def setup_daemon_logging(verbose=False):
    """Log to a file (append). No console handler: the daemon runs via
    pythonw.exe, which has no useful stdout."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=LOG_PATH,
        filemode="a",
    )


def main():
    parser = argparse.ArgumentParser(description="command-queue daemon for the operator agent")
    parser.add_argument("--port", default=None, help="CH340 serial port (e.g. COM5). Auto-detects if omitted.")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--dry-run", action="store_true", help="does not open the serial port; only logs the HID frames")
    parser.add_argument("--queue-dir", default=QUEUE_DIR)
    parser.add_argument("--poll-interval", type=float, default=POLL_INTERVAL)
    parser.add_argument(
        "--keep-alive", nargs="?", type=int, const=KEEP_ALIVE_SECONDS, default=0,
        metavar="SECONDS",
        help="nudges the mouse 1px every N IDLE seconds so the screen does not "
             "re-lock (no value: %d). Off by default." % KEEP_ALIVE_SECONDS)
    parser.add_argument(
        "--keep-alive-max-idle", type=int, default=KEEP_ALIVE_MAX_IDLE,
        metavar="SECONDS",
        help="stops the keep-alive after N seconds with no request "
             "(default: %d), restoring the screen's automatic lock."
             % KEEP_ALIVE_MAX_IDLE)
    parser.add_argument(
        "--frames-max-mb", type=int, default=DEFAULT_FRAMES_MAX_MB,
        help=f"space cap for queue/frames/ in MB (default: "
             f"{DEFAULT_FRAMES_MAX_MB}). Past the cap, the oldest PNGs are "
             f"deleted after each request. 0 disables it. Frames moved to "
             f"queue/frames/{KEEP_SUBDIR}/ are never pruned.")
    parser.add_argument(
        "--frames-keep", type=int, default=0,
        help="alternative cap, by number of PNGs in queue/frames/. "
             "0 (default) = no count limit. If both caps are given, the "
             "tighter one wins.")
    parser.add_argument(
        "--frame-per-step", action="store_true",
        help="saves a PNG after each write action (click, type_text, "
             "press_key, key_combo, goto, scroll) of every request. Costs ~0.4s "
             "per action and serves as evidence when something goes wrong. Each "
             "request can override with \"capture_each_step\": true/false, and "
             "each step with \"frame\": true/false.")
    parser.add_argument(
        "--layout", default=hid_keycodes.get_layout(),
        choices=hid_keycodes.available_layouts(),
        help="the TARGET keyboard layout (the typed glyph depends on it). "
             "Default: %(default)s. The target must be in that layout.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_daemon_logging(verbose=args.verbose)
    hid_keycodes.set_layout(args.layout)
    logger.info("target keyboard layout: %s", hid_keycodes.get_layout())

    def controller_factory():
        controller = resolve_controller(
            port=args.port, baud=args.baud, dry_run=args.dry_run, fallback_dry_run=False
        )
        if controller is None:
            raise RuntimeError("CH9329/CH340 not found (connect the hardware or use --port/--dry-run)")
        return controller

    try:
        lock = acquire_queue_lock(args.queue_dir)
    except AlreadyRunning as exc:
        logger.error("%s", exc)
        return 1

    ctx = DaemonContext(controller_factory)
    try:
        main_loop(ctx, queue_dir=args.queue_dir, poll_interval=args.poll_interval,
                  keep_alive_seconds=args.keep_alive,
                  keep_alive_max_idle=args.keep_alive_max_idle,
                  capture_each_step=args.frame_per_step,
                  frames_keep=args.frames_keep,
                  frames_max_bytes=max(0, args.frames_max_mb) * 1024 * 1024)
    finally:
        ctx.close()
        lock.close()  # releases the queue for the next daemon
        logger.info("daemon finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
