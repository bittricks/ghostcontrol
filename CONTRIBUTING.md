# Contributing to VeriKVM

Thanks for considering a contribution. This project has one strong opinion,
and it shapes everything: **it never acts on a screen it hasn't verified, and
never trusts a success it hasn't confirmed.** Keep that in mind and you'll
fit right in.

## Ground rules

- **Fail-closed.** When the code can't be sure, it does nothing. A change that
  makes an uncertain path *act* instead of *refuse* will be sent back. Losing
  a batch costs a minute; typing blind costs more.
- **Own-machine only.** VeriKVM is for controlling your own machines. We won't
  accept features whose only purpose is to evade a platform's defenses —
  anti-detection, timing obfuscation, automation-hiding. See
  [SECURITY.md](SECURITY.md).
- **Measure, don't assume.** This project is a long argument for measuring.
  If you claim a timing, a threshold, or a hardware behavior, show the number.

## Setup

```bash
git clone https://github.com/bittricks/verikvm
cd verikvm
python -m venv .venv && . .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pytest
```

You can develop most of the engine **without hardware**: the test suite uses
fakes for the serial controller and the capture device. You only need a
CH9329 and a capture dongle to test against a real target.

## Before you open a PR

- **Run the tests.** `pytest` should be green. New behavior needs a test.
- **Respect the architecture boundary.** The engine core must not import
  app-specific code; `tests/test_arquitetura.py` enforces this and will fail
  if you cross it. If you're adding a feature, it's almost always in the core
  or in a tool beside it — not reaching into application code.
- **No secrets, ever.** No credentials, no real screen captures, no personal
  paths. A secret scanner runs on the repo; keep your own commits clean too.
- **Keep the measured docs honest.** If you change hardware behavior, update
  [HARDWARE.md](HARDWARE.md) with what you measured, not what you expect.

## A good first contribution: a keyboard layout

The HID engine types by key *position*; the glyph depends on the target's
layout. Adding a layout is self-contained and genuinely useful:

1. Build a `{char: (usage_id, needs_shift)}` table for your layout, plus its
   dead-key tables if it has them (see the ABNT2 layout for the pattern).
2. Register it with `register_layout("<name>", ...)` in `hid_keycodes.py`.
3. Add a test in `tests/test_layouts.py`: the glyphs that differ from US, and
   a check that characters the layout can't produce are **refused**, not
   mistyped.
4. If you can, verify a few characters against real hardware and note it.

## Reporting bugs

Open an issue with: your OS, your hardware (bridge + capture chip), what you
expected, what happened, and — if it's a timing or screen-reading bug — a
captured frame or the measured numbers. For **security** issues, don't open a
public issue; see [SECURITY.md](SECURITY.md).

## Commit style

Clear, present-tense subject lines that say what the change does and why it
matters. The git history is part of the documentation here.
