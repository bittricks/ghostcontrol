# Security

## Scope: your own machines

GhostControl is built to control **a second machine that belongs to you**, with
**your own credentials**, over two cables you plugged in yourself. That is
the entire intended use, and it's what makes the design legitimate: the owner
operating their own equipment has nothing to hide from and no one to evade.

The software cannot verify that the two machines are yours — that is on the
operator. What the project *can* do, and does, is refuse to ship anything
that only serves misuse, keep the framing explicit, and fail closed.

## Threat model

**What GhostControl is.** An agentless, OS-level automation and remote-control
tool. Input goes through a CH9329 USB-HID bridge; the screen comes back over
an HDMI capture card. The target runs no agent, driver, or remote-desktop
software.

**Attack surface by default: the local hardware, not the network.** The
reference setup is a file queue on the controller plus two USB cables. It
**opens no listening network port**. There is nothing remote to authenticate
to and nothing to break into over a network — because there is no network
service. If you add one (a web UI, a TCP API), authentication and transport
security become *your* responsibility; this project ships none because it
exposes none.

**What it deliberately does not do.**
- No power control, no BIOS/UEFI, no virtual media — the target's OS must be
  up. It is not a hardware KVM.
- **No anti-detection, no automation-evasion, no timing obfuscation.** Typing
  speed is a reliability knob (the serial line has a floor), never a tool to
  disguise automation from a platform. Operating your own machine doesn't
  require hiding from it.
- No capture of the target's screen is transmitted anywhere. Frames stay
  local and are for the controller's own verification.

## Credentials

- **Never commit a credential.** The repository ignores credential files,
  the frame/queue directories, and logs by default.
- **Store secrets outside the project tree.** Prefer the OS secret store
  (via `keyring`) or an environment variable over a plaintext file. On
  machines with cloud-synced folders (OneDrive, Dropbox, iCloud), a file
  inside a synced folder is uploaded in cleartext even when `.gitignore`
  excludes it from git — keep secrets out of synced trees.
- **How it loads (`credentials.py`).** In order: the `GHOSTCONTROL_USERNAME` /
  `GHOSTCONTROL_PASSWORD` environment variables, then a gitignored `.env` file
  (copy `.env.example`), then the OS keyring. The password is never written
  to the repo and never logged — `redact()` keeps it out of log lines, and
  the `Credentials` repr hides it from tracebacks.
- **Storing the login password is optional.** Typing it at unlock time is a
  valid mode; the stored-credential path is a convenience, not a requirement.
  Leave the password blank in `.env` to be prompted instead.
- A password-typing action is gated: it verifies it is on the login screen
  before typing, refuses any other state, and does not leave the request on
  disk afterward.

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue.

Use GitHub's **private vulnerability reporting**: on the repository, open
**Security → Report a vulnerability**. It keeps the report confidential
until a fix ships and needs no email address — which suits a project
maintained pseudonymously. (Enable it once under the repo's Security
settings.)

We'll acknowledge within a reasonable window and keep you updated as we
investigate. There are no guaranteed timelines — this is a volunteer
project — but reports are taken seriously.

## Supported versions

Until a `1.0` release, only the latest commit on the default branch is
supported. Pin a commit if you need stability.
