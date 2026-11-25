# -*- coding: utf-8 -*-
"""Load the target's unlock credentials — locally, and never committed.

The password that unlocks the target is the most sensitive thing this
project touches. This module loads it with least-leak rules.

Resolution order (first hit wins):
  1. Environment variables   -- GHOSTCONTROL_USERNAME / GHOSTCONTROL_PASSWORD
  2. A .env file (gitignored) -- KEY=VALUE, in the working directory
  3. The OS secret store      -- via `keyring`, if installed
  4. Nothing                  -- the caller prompts at runtime

Guarantees:
  - The password is NEVER written to the repository tree by this module,
    and NEVER logged. `redact()` exists so callers don't leak it either;
    the Credentials repr hides it too, so it won't surface in a traceback.
  - The OS keyring (option 3) keeps the password off disk entirely and is
    the most secure of the three. A .env file is a convenience.

Why not a committed config file: a credential in the repo tree is one
`git add .` away from being public, and on a machine with a cloud-synced
folder (OneDrive, Dropbox, iCloud) a file inside a synced folder is
uploaded in cleartext even when .gitignore excludes it from git. Keep
secrets in the environment, the keyring, or a .env you never sync.
"""
import os

ENV_USERNAME = "GHOSTCONTROL_USERNAME"
ENV_PASSWORD = "GHOSTCONTROL_PASSWORD"
KEYRING_SERVICE = "ghostcontrol"
DEFAULT_ENV_FILE = ".env"


def redact(secret):
    """A log-safe stand-in for a secret: never the value itself.

    Use this anywhere a credential might reach a log line or an error."""
    if not secret:
        return "<none>"
    return "<redacted:%d chars>" % len(secret)


class Credentials:
    """username + password, with the password kept out of repr/log output."""

    __slots__ = ("username", "password", "source")

    def __init__(self, username, password, source):
        self.username = username
        self.password = password
        self.source = source          # where the password came from, or None

    @property
    def has_password(self):
        return bool(self.password)

    def __repr__(self):
        # The password must never land in a repr -- reprs end up in logs
        # and tracebacks.
        return "Credentials(username=%r, password=%s, source=%r)" % (
            self.username, redact(self.password), self.source)


def _parse_env_file(path):
    """Minimal KEY=VALUE parser: ignores blank lines and # comments, strips
    surrounding single/double quotes. No shell expansion -- a secret is a
    literal, never code. Missing file -> empty dict, never an error."""
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                values[key] = val
    except OSError:
        return {}
    return values


def _from_keyring(username):
    try:
        import keyring  # optional dependency
    except Exception:
        return None
    if not username:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, username)
    except Exception:
        return None


def load_credentials(env_file=DEFAULT_ENV_FILE, allow_keyring=True):
    """Resolve the target credentials. The password may be None.

    Order: environment variables, then the .env file, then the OS keyring.
    The returned Credentials names its source; a None password means
    nothing provided one, and the caller should prompt rather than assume.
    """
    username = os.environ.get(ENV_USERNAME)
    password = os.environ.get(ENV_PASSWORD)
    source = "env" if password is not None else None

    if username is None or password is None:
        file_values = _parse_env_file(env_file)
        if username is None:
            username = file_values.get(ENV_USERNAME)
        if password is None:
            fp = file_values.get(ENV_PASSWORD)
            if fp:                    # a blank value in .env means "prompt"
                password, source = fp, "env-file"

    if password is None and allow_keyring:
        kp = _from_keyring(username)
        if kp:
            password, source = kp, "keyring"

    return Credentials(username, password, source)
