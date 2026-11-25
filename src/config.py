import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "capture_index": 0,
    "capture_backend": "dshow",
    "requested_width": 1920,
    "requested_height": 1080,
    "requested_fps": 30,
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read %s (%s). Using the default configuration.", CONFIG_PATH, exc)
            return dict(DEFAULT_CONFIG)
        if not isinstance(data, dict):
            logger.warning("%s does not contain a valid JSON object. Using the default configuration.", CONFIG_PATH)
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def queue_dir():
    """Daemon queue directory, OUTSIDE the cloud-synced tree.

    Same reason as the credential: queue/frames/ stores screen captures of
    the target (third parties' private conversations and data) plus the
    rest of the runtime; under the Desktop (Known Folder Move) all of that
    was uploaded to the cloud in cleartext. The .gitignore protects git,
    not a synced folder (OneDrive, Dropbox, …). Order:

      1. GHOSTCONTROL_QUEUE_DIR -- explicit override (full path);
      2. %LOCALAPPDATA%\\GhostControl\\queue -- LOCALAPPDATA doesn't sync;
      3. <project>/queue -- compatibility only (may be synced).

    SINGLE SOURCE: the daemon (consumer) and wake_/keep_alive_* (producers)
    all resolve it here. If they diverge, requests land in one place and the
    daemon watches another -- the queue stalls silently.
    """
    override = os.environ.get("GHOSTCONTROL_QUEUE_DIR")
    if override:
        return override
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "GhostControl", "queue")
    return os.path.join(os.path.dirname(__file__), "queue")
