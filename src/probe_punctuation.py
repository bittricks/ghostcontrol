"""Probes, on the real hardware, which glyphs come out of the usages that
`hid_keycodes` could only INFER from the ABNT2 layout.

Why it exists
=============
HID has no feedback: the CH9329 sends a key position and the one that
decides the glyph is the TARGET's Windows layout driver. A wrong usage
raises no error -- it emits another character. And if that other character
is a dead key, it also swallows the next character, so the damage is silent
and does not stay where it was caused. It already happened: `[` was at usage
0x2F, which in this layout is the acute accent, so `[A` became `A-acute`.

That is why `hid_keycodes.UNVERIFIED_CHARS` refuses those characters by
default, and this probe is the only way to enable one of them.

How to use
==========
1. Leave the cursor in a PLAIN TEXT field on the target (WhatsApp message
   box, Notepad). Do NOT use an Excel cell: it interprets `=`, `'` and `+`
   and shows something other than what was typed.
2. Check first what is focused -- this script types, and typing in the wrong
   window is the error the rest of the project exists to avoid:

       python agent_daemon.py --port COM5 --once   # with a batch of expect

   or simply look at a frame from `capture_frame.py`.
3. Run:

       python probe_punctuation.py --port COM5 --out probe.png

4. Compare the PNG with the reference printed in the terminal. For each pair
   that matches, remove the character from `UNVERIFIED_CHARS` in
   `hid_keycodes.py` and note it in the table in docs/ABNT2_HID_KEYBOARD.md.
   For each pair that does NOT match, fix the usage and probe again -- never
   "promote when in doubt".

The probe types each candidate between `>` and `<` markers because a glyph
that does not come out (a hanging dead key, for example) vanishes without a
trace: `>[<` becoming `><` says nothing arrived, whereas `[` alone in running
text is indistinguishable from a character lost on the serial line.
"""
import argparse

import os
import sys
import time

import ch9329
import hid_keycodes

# One probe per line of text. More than that in a narrow field makes the text
# scroll and the beginning leaves the frame.
GROUPS = (
    ("shifted punctuation", "[]{}\\|"),
    ("apostrophe and quotes", "'\""),
    ("dead-key glyph", "´`~^¨"),
)

# Between events of a probe: generous on purpose. The dead key needs the gap
# to "arm", and here speed does not matter -- what matters is not blaming the
# usage for an error that was timing.
CHAR_DELAY = 0.15


def probe_lines():
    """[(label, text_to_type, expected_reference), ...]"""
    out = []
    for label, chars in GROUPS:
        text = " ".join(">%s<" % c for c in chars)
        out.append((label, text, text))
    return out


def type_probes(controller, lines, char_delay=CHAR_DELAY):
    for i, (label, text, _) in enumerate(lines):
        if i:
            controller.press_named_key("enter")
            time.sleep(char_delay)
        # allow_unverified: this is the only place in the project that may.
        # The whole point of the probe is to measure what was not measured.
        controller.type_text(text, char_delay=char_delay,
                             allow_unverified=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="CH9329 serial port (e.g. COM5)")
    p.add_argument("--out", help="path of the PNG with the on-screen result")
    p.add_argument("--char-delay", type=float, default=CHAR_DELAY)
    p.add_argument("--dry-run", action="store_true",
                   help="only prints the reference, types nothing")
    a = p.parse_args(argv)

    lines = probe_lines()

    print("Reference -- the target must show exactly this:")
    for label, _, expected in lines:
        print("  %-22s %s" % (label, expected))
    print()
    print("Currently refused for lack of measurement: %s"
          % " ".join(sorted(hid_keycodes.UNVERIFIED_CHARS)))

    if a.dry_run:
        return 0

    with ch9329.CH9329Controller(a.port) as controller:
        controller.release_all_keys()
        type_probes(controller, lines, char_delay=a.char_delay)

    if a.out:
        from capture_frame import capture_frame_to_file

        capture_frame_to_file(a.out)
        print("\nframe: %s" % os.path.abspath(a.out))
        print("Compare with the reference above BEFORE promoting any "
              "entry in hid_keycodes.UNVERIFIED_CHARS.")
    else:
        print("\nWithout --out: capture the screen some other way before "
              "concluding anything. The probe proves nothing without the read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
