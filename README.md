<!-- Public-repo README. PT version: README.pt-BR.md -->

# VeriKVM

**An agentless software KVM that operates your own machine like a human.**

It performs real tasks on your second machine: it **reads the screen,
understands what state it's in, then types and clicks** — on hardware the
target sees as a real physical keyboard and mouse. Nothing is installed on
the target.

And unlike every other software KVM, it **verifies the screen before every
action and refuses to act in the wrong window** — so a task never lands in
the lock screen or the wrong app.

> **For your own machines.** Two machines of yours, two cables, and you.
> See [SECURITY.md](SECURITY.md) for the scope and threat model.

🌐 **English** · [Português](README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh.md) · [Français](README.fr.md) · [Русский](README.ru.md)

MIT · built on a CH9329 USB-HID bridge + an HDMI capture card

---

## What you can automate

VeriKVM saves you the hours you'd spend babysitting a second computer. You
write small JSON tasks (or reuse the examples), and it carries out the
everyday and at-work desktop work people automate most — always acting only
when the screen is the one the task expects:

- **Reply to chats and messages** — WhatsApp Web, Telegram, Slack, Teams:
  spot a new message, type the answer, hit send.
- **Keep a machine awake and active** — stop it sleeping, locking or going
  idle during long jobs, without changing power settings.
- **Answer and triage email** — open the client, read what's on screen, type
  the reply, file the message.
- **Edit spreadsheets** — open Excel or Google Sheets, enter rows, trigger a
  recalculation, save.
- **Fill forms and do data entry** — repetitive typing into web or desktop
  apps that have no API.
- **Drive apps that reject bots and macros** — because the input is real
  USB-HID, software that blocks scripts still accepts it.
- **Run unattended batches overnight** — queue a list of tasks; it verifies
  every screen first, so nothing fires in the wrong window.
- **Operate a second or headless PC remotely** — no agent, driver or
  remote-desktop software installed on that machine.

In short: **agentless desktop automation (RPA) for a second computer**, with
screen verification so a task never types into the wrong place.

## Why this one

Every other software KVM forwards your keystrokes blindly — it has no idea
which window has focus, a re-locked screen eats your input, and it reports
"sent OK" even when nothing happened. VeriKVM closes the loop the way a
person at the keyboard does:

1. **Reads the screen.** Captures the HDMI feed and classifies what's really
   on screen — desktop, the right app, a lock screen, a dialog.
2. **Decides the state.** If the screen isn't what the task expects, it
   refuses the whole batch instead of typing into the wrong place.
3. **Acts on real hardware.** Types and clicks through the CH9329, then reads
   the screen back to confirm the action actually landed.

This is the one thing the hardware-KVM and software-KVM crowds both skip,
because they forward input and never have to trust a screenshot.

## What it is — and isn't

**It is** an OS-level automation and remote-control tool for a machine whose
OS is running. No agent, no driver, no remote-desktop software on the target
— it looks like a human at the keyboard.

**It is not** a hardware KVM. There is **no power control, no BIOS/UEFI
access, no virtual media.** If you need pre-boot control, use a Pi-based
IP-KVM (PiKVM, TinyPilot). See [HARDWARE.md](HARDWARE.md) for the honest
limits.

## Features

- **Fail-closed verification** — classifies the screen before each action,
  refuses the wrong state, and confirms every action by reading back.
- **Real HID input** — a CH9329 bridge the target can't distinguish from a
  physical keyboard and mouse. Agentless.
- **International keyboards** — pluggable layouts (US, ABNT2, more). A
  character the active layout can't produce is refused, never emitted as the
  wrong glyph.
- **Measured, not guessed** — a [hardware guide](HARDWARE.md) with the quirks
  we measured, and an [engineering log](LEARNINGS.md) of what broke and why.

## How it connects

```
[ TARGET ] --HDMI out--> [ capture dongle ] --USB--> [ CONTROLLER ]
[ TARGET ] <--USB HID--- [ CH9329 + CH340 ] <--USB-- [ CONTROLLER ]
```

Two machines, two cables. The controller writes JSON task files; the daemon
executes them on the target and reads the screen back. See
[HARDWARE.md](HARDWARE.md) for the parts list (~US$15–25).

## Getting started

```bash
git clone https://github.com/bittricks/verikvm
cd verikvm
pip install -r requirements.txt

# start the daemon (auto-detects the serial port; --layout sets the
# target's keyboard layout, default abnt2)
python src/agent_daemon.py --layout us
```

Full setup, wiring and calibration are in [`docs/`](docs/).

## Status

The verification core is covered by a test suite (400+ tests), including an
architecture-boundary test that keeps the engine free of app-specific code.

## Security

This controls a machine of yours with a credential of yours. It opens **no
network port by default** — it talks to the hardware, not the network. Read
[SECURITY.md](SECURITY.md) before exposing anything, and to report a
vulnerability.

## License

MIT — see [LICENSE](LICENSE).

## Support

VeriKVM is a volunteer project. If it saved you a weekend, you can chip in
on-chain. **Send each asset only on the network listed — a wrong network
means the funds are lost.**

**Bitcoin**
```
bc1qp8auny76nc73x5kepej2dsyl54x06nvxgrwjy6
```

**Ethereum & EVM** — ETH, USDC, USDT on Ethereum, Base, Arbitrum, Optimism, Polygon, BNB Chain
```
0x935D040a03cb94B3cD1736b1f0813A6A0Ab0BE72
```

**Solana** — SOL and SPL tokens
```
24LvX1XQ7xF6SGeRwx3NmbPMAaaqHF2FJp7rEM9GMjpS
```

**Tron** — TRX and TRC-20 (e.g. USDT-TRC20)
```
TRxSPc5tNmgHvr4t9bPtnG6U7iApKedX8n
```

**Monero** — XMR
```
86oP1vf2TucfxGQDkXyBJeJnf5yeC7uzperQsnFdmS3EYHP4zYt3DdeYyP12Qo69w6AEuGYfMTSeKZHDrC8fzECm2c8GRii
```

**What donations support:** continued maintenance, the hardware we test
against, and the docs. **What not to expect:** guaranteed features or
timelines — this is a volunteer project, and no outcome is promised.
