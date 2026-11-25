# Hardware guide

Everything you need is **two cables between two machines**: a USB-HID bridge
that types and clicks, and an HDMI capture device that sees the screen.
Nothing is installed on the target — it sees a real keyboard, mouse and
monitor.

This guide is the honest version: what to buy, what the cheap parts get
wrong, and the quirks we **measured** instead of trusting the datasheet.

> **What this hardware cannot do.** It is not a hardware KVM. There is no
> power control, no BIOS/UEFI access, no virtual media, no "reinstall the
> OS remotely." The target's OS must be running. If you need pre-boot
> control, you want a Pi-based IP-KVM (PiKVM, TinyPilot), not this.

---

## What to buy

| Part | Minimum | Notes |
|---|---|---|
| **HID bridge** | CH9329 module (with a CH340 USB-serial) | ~US$3–6. Presents as a real USB keyboard+mouse. |
| **Capture** | MS2109 USB dongle (1080p60) | ~US$8–15. MS2130 if you want USB 3.0. |
| **HDMI cable** | target HDMI-out → capture | a splitter only if the target also drives a real monitor |
| **USB** | capture → controller, bridge → controller | two USB ports on the controller |

Total: roughly **US$15–25**. The controller is any PC you already have.

---

## The HID bridge — what types and clicks

### CH9329 (the default, and what we use)

A UART-to-USB-HID bridge. The target sees a composite USB keyboard+mouse;
it cannot tell it from physical hardware. You drive it over a serial port
(a companion CH340 gives you USB-serial), sending framed commands.

- **Serial:** 9600 baud, 8N1 by default.
- **Quirk — the protocol is barely documented in English.** The datasheet
  is Chinese-only; the command framing in `ch9329.py` was reconstructed and
  verified against real hardware.
- **Quirk — there is a real speed floor (measured).** Each keystroke is two
  14-byte frames (28 bytes). At 9600 8N1 that is **~29 ms of line time per
  keystroke**, and that is the floor — asking for less just makes the
  driver's write block. Measured on our rig: a requested `char_delay` of
  0.05 s yields **49.8 ms/keystroke**, and 0.15 s yields **148.8 ms**. Don't
  expect sub-30 ms typing out of this chip; it's physics, not tuning.

### Alternatives

| Chip / board | Trade-off |
|---|---|
| **CH9350L** | Sibling of the CH9329, near-identical protocol. Supported by some drivers behind a flag. |
| **CH9328** | UART-to-HID but **keyboard only** — no mouse. Has an Adafruit breakout. |
| **Arduino Leonardo / Micro** (ATmega32U4) | Native USB, you write the firmware. Full control, more work. |
| **Raspberry Pi Pico** (RP2040) | Native USB, cheap, flexible; can also bridge Bluetooth→USB-HID. Needs C/CircuitPython. |

The CH9329 wins on being a cheap external bridge that works with **any** host
that has a UART — no firmware to flash.

---

## The capture — what sees the screen

### MS2109 (the default)

A USB 2.0 UVC dongle, 1080p60. Shows up as a standard webcam, so OpenCV /
any UVC stack reads it with no driver.

- **Quirk — mono audio** on many MS2109 dongles. Irrelevant here (we only
  use video), but don't buy it for audio.
- **Quirk — it bypasses HDCP** on some units. Convenient for us; also why
  the "improved" MS2130 can be a downgrade (below).

### MS2130 (the USB 3.0 option)

- **The "4K" label is marketing.** 4K is the *input* resolution; the USB
  *output* still tops out at 1080p60.
- **It does NOT bypass HDCP** the way the MS2109 does — this broke HDCP
  sources for some users who "upgraded."
- **It falls back to MS2109 behavior** when it drops to a USB 2.0 port.

**Recommendation:** for 1080p60, the MS2109 is the safe default. Reach for
the MS2130 only if you specifically need USB 3.0 and your source isn't
HDCP-protected.

---

## The quirk nobody else documents: the capture is one frame behind

This is the finding that cost us the most and that you will not read in any
datasheet or competing project — because the others forward keystrokes
blindly and never had to trust a screenshot.

**The capture pipeline lags by exactly one capture.** Each frame you read
shows the screen as it was when the *previous* capture happened.

Measured on the rig: put text on screen, clear it, wait **I** seconds, take
**one** capture.

| wait I | captures still showing the old (cleared) screen |
|---|---|
| 0.5 s | 4/4 |
| 1.0 s | 4/4 |
| 2.0 s | 4/4 |
| 4.0 s | 4/4 |

**16 of 16 were stale — even waiting four seconds.** Waiting never fixes it.
The frame grabs (`cap.grab()`) don't fix it either, because they don't force
a new frame to be decoded.

**What fixes it:** discard one full `cap.read()` before the one you keep.
Cost: **~25 ms**. After the fix, the same experiment is **0 of 16** stale.

If you build your own capture loop on these dongles, do the same, or your
"after" screenshot will quietly be the "before." (In this project it's
`DISCARD_READS` in `capture_frame.py`.)

---

## Wiring, in short

```
[ TARGET ] --HDMI out--> [ capture dongle ] --USB--> [ CONTROLLER ]
[ TARGET ] <--USB HID--- [ CH9329 + CH340 ] <--USB-- [ CONTROLLER ]
```

- The CH9329's **USB side** plugs into the **target** (that's the "keyboard").
- The CH9329's **serial side** (via CH340) plugs into the **controller**.
- The capture's HDMI side takes the **target's** video out; its USB side goes
  to the **controller**.
- If the target also needs a real monitor, put a cheap HDMI splitter on its
  output.

---

## Honest limits, again

- OS must be up; no pre-boot, no power control.
- One target per bridge+capture pair.
- Resolution assumptions (coordinates, OCR regions) are tuned for 1080p; other
  resolutions need recalibration.
- These are cheap consumer dongles with firmware variants; two units with the
  same label can behave slightly differently. Measure, don't assume — which is
  the whole point of this project.
