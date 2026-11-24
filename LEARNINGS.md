# Learnings

This project drives one computer from another through real hardware — a
USB-HID bridge that types, an HDMI capture card that sees. There is no API
on the target, no return channel, no exceptions when something goes wrong.
A keystroke sent to the wrong window is simply gone.

That constraint taught a specific discipline: **never act on a screen you
haven't verified, and never trust a success you haven't confirmed.** These
are the lessons that shaped the engine, each one paid for by a bug. Most
are generalizable beyond this project.

---

## Verification — a success you didn't confirm isn't one

**"It returned OK" proves nothing.** A send action once returned success and
sent nothing — the Enter key landed outside the input because focus had
quietly moved. The layer that reports success rarely knows whether the
effect happened. Only reading the screen back proves it. Every write action
in this project now has a post-condition that re-reads the screen.

**A pre-condition and a post-condition catch different failures.** Checking
the screen *before* an action stops you from typing into the wrong window.
It does *not* catch the case where the screen was right, the keystroke was
accepted by the hardware, and still nothing happened on the machine. Only a
*post*-condition catches that. You need both.

**One reading doesn't prove a state.** We twice declared a screen locked
when it was already unlocked, each time from a single OCR read of a stale
frame. The rule became: require two samples that agree, and return
`INDETERMINATE` when they don't — because "the screen is mid-transition" is
the correct answer, not a coin flip between the two.

**A reading at t=0 is a lottery, not a check.** An early version checked the
screen once, at the instant after acting. On a capture card that serves
stale frames, that is the one timing guaranteed to fail. The fix wasn't a
fixed sleep (see below) — it was polling with re-reads.

**A label in the content is not a verifiable post-condition.** "Is the
expected word somewhere on screen" is weak: the word often appears for
reasons unrelated to the state you're checking. Verify a signal that is
*only* true in the state you want.

---

## The capture is one frame behind — the finding that cost the most

This is the headline. Our capture pipeline lagged by **exactly one
capture**: each frame read showed the screen as it was when the *previous*
capture happened.

We found it the slow way, after inventing the wrong explanation first. The
symptom was "the screenshot shows the previous state." We decided that meant
"not enough time" and added a sleep. We were wrong, and here's the
measurement that proved it: put text on screen, clear it, wait **I**
seconds, take **one** capture.

| wait | captures still showing the cleared-away text |
|---|---|
| 0.5 s | 4/4 |
| 1.0 s | 4/4 |
| 2.0 s | 4/4 |
| 4.0 s | 4/4 |

**16 of 16 stale, even at four seconds.** Waiting never helped. And in the
same batch, the *next* capture — taken with no wait at all, ~25 ms later —
was correct 6 of 6 times.

The lesson wasn't about the hardware. It was that **we had the right
observation and invented the mechanism.** "Shows the previous state" became
"needs more time" without anyone varying the time to test it. The hypothesis
only died when we measured four seconds — and it predicted four seconds
would work.

The fix: discard one full read before the one you keep. Cost ~25 ms;
stale rate went to 0/16. Three corollaries:

- **We'd already tuned the wrong knob once.** Months earlier we'd raised the
  number of frame *grabs* and the symptom persisted — because `grab()`
  doesn't force a new frame to decode. Only a full `read()` advances the
  pipeline.
- **An impossible result is an instrument defect, not a discovery.** While
  chasing this, an early scoring compared each frame against a *previous*
  frame that could also be stale, and produced a non-monotonic result (more
  waiting → *more* staleness). That's physically impossible, which was the
  signal that the measurement, not the world, was wrong. Switching to an
  absolute measure fixed it. Relative comparison inherits the error on both
  sides.
- **We fixed one path and nearly called it done.** The discard-read fix went
  into the code path that saves screenshots, and left the path that feeds
  *verification* untouched for a day — i.e. the path that decides whether to
  type. The real fix was deleting the duplicate read logic so both paths
  share one function. A bug born of duplication is fixed by removing the
  duplication, not by patching both copies.

Separately: **"wait after switching windows" is a real and different
problem.** A freshly focused window can take ~1 s to paint; capture it too
soon and you get the window frame with black content. That one *is* solved
by waiting — which is why it's dangerous: the same symptom (wrong content on
screen) has two causes, and conflating them is what produced the wrong
mechanism above.

---

## Classifying the screen — measure, don't infer

**There is no OCR config that works for everything.** Reading dark-on-light
needs the opposite preprocessing from light-on-dark; a lone short word needs
a different page-segmentation mode than a paragraph. The engine tries
several and reasons about the results, rather than hunting for one magic
setting.

**Validating against the sample you chose isn't validation.** A pixel gate
passed on nine hand-picked frames, then misclassified on the rig the next
day — in the dangerous direction. The counter-examples were sitting in a
hundred-odd frames already on disk, one loop away. The sample you pick
carries the shape of the hypothesis you're testing. An axis can be not just
wrong but *inverted* and still pass on that sample. Sweep all the data you
have before declaring a threshold validated, and demand margin on both
sides, not just separation.

**When a discriminator fails intermittently, it's usually measuring too
little evidence — not that the threshold is wrong.** A screen-state check
depended on OCR reading a five-letter placeholder that was faint and
low-contrast; two frames of the *identical* state, pixel-for-pixel equal to
four decimals, read the word in one and not the other. The fix wasn't a
better threshold — it was finding a stronger signal (a large white glyph,
24× better separated) and using it as an *additional* cue, never a
replacement.

**Evidence becomes evidence the moment you cite it.** We validated a
classifier against an on-disk corpus of frames in the morning, then that
afternoon ran enough new captures to blow past a size cap, and the automatic
pruning deleted the oldest files first — the exact corpus we'd just relied
on. The protection existed and was documented; we just never moved the files
into the protected folder. The time to protect material is the moment you
write "I validated against these," not later.

---

## Typing on real hardware

**Validate every character before sending.** A USB-HID usage ID that's wrong
doesn't raise an error — it emits a *different* glyph. And if that glyph is a
dead key (an accent), it silently swallows the next character too. Run every
character through the encoder before the first keystroke and refuse the whole
batch if any comes back unmapped. (See `hid_keycodes` and the layout engine.)

**Count proves nothing was swallowed; it doesn't catch a swap.** When
verifying what the HID actually typed, the character count catches the
silent dead-key damage — but two accents swapped for each other produce the
*same* count. When two hypotheses produce the same measurement, that
measurement decided nothing between them. Read the glyphs too, and with
enough instrument: at a small font an accent is a handful of pixels and two
accents are indistinguishable; magnify before you conclude.

**There's a hard speed floor, and it's physics.** Each keystroke on this
bridge is two 14-byte serial frames. At 9600 8N1 that's ~29 ms of line time
per keystroke, and that's the floor — asking for less just blocks the
driver's write. Measured: a requested 0.05 s yields 49.8 ms per keystroke,
0.15 s yields 148.8 ms. Know your floor before you "optimize" toward it.

**Read the hardware state instead of guessing it.** A correct password was
once rejected, and the obvious suspect was a stuck modifier (a held lock key
silently inverts the case of everything). There was no way to *check* — so we
added one: the bridge can report the target's keyboard lock LEDs. The
hypothesis died by measurement, not by burning one of three password
attempts on a guess. When the cost of guessing is high, instrument.

---

## Fail-closed as a discipline

**When evidence is absent, the restrictive branch must run.** A gate that
decides whether it's safe to type should ask "is there proof this is safe?"
— never "does this look unsafe?". The default branch is the one that runs
when you don't know, and it's the most-executed branch in a new situation.
It has to fall on the cheap side: losing a batch costs a minute; typing
blind can cost far more.

**An optional guard is not a guard.** A screen-state check existed that would
refuse to type in the wrong state — but it was an opt-in flag, and the one
batch that mattered didn't set it. The guard wasn't missing; it was in the
wrong place — hung on an optional step instead of bound to the data it
protects. It now lives on the typing action itself and runs every time.

**Refuse what you can't do, cleanly, instead of doing it wrong.** A
character the active keyboard layout can't produce is refused — never emitted
as some other glyph. For a user whose script needs an input method the
target doesn't have, the honest behavior is to refuse and say so, not to
type garbage that looks like success.

---

## A few operational scars

- **Color bars don't mean "powered off."** SMPTE bars from a capture dongle
  mean *no HDMI signal*, which looks nothing like a black screen. Classify it
  as its own state.
- **Write queue/IPC files in explicit UTF-8.** The platform default encoding
  will mangle non-ASCII on some machines and not others — a bug that travels.
- **A config file can assert two incompatible things and pass for months.**
  Trust what you measure against the real system over what a file claims.
- **Two interpreter processes in the task list are not two daemons.** Confirm
  identity (a lock file, a PID) before concluding you have a conflict.
- **An impossible or non-monotonic result is a defect in the instrument.**
  Stop collecting data and fix the measurement first.
