import os

import config


def test_load_config_returns_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "missing.json"))
    assert config.load_config() == config.DEFAULT_CONFIG


def test_load_config_merges_with_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"capture_index": 3}')
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    result = config.load_config()

    assert result["capture_index"] == 3
    assert result["requested_width"] == config.DEFAULT_CONFIG["requested_width"]


def test_load_config_falls_back_on_malformed_json(tmp_path, monkeypatch, caplog):
    path = tmp_path / "config.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    with caplog.at_level("WARNING"):
        result = config.load_config()

    assert result == config.DEFAULT_CONFIG
    assert "could not read" in caplog.text.lower()


def test_load_config_falls_back_when_json_is_not_an_object(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    assert config.load_config() == config.DEFAULT_CONFIG


def test_save_config_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    config.save_config({"capture_index": 7})

    assert config.load_config()["capture_index"] == 7


# ---------------------------------------------------------------------------
# queue_dir: the queue lives OUTSIDE the OneDrive-synced tree.
# .gitignore does not stop the upload; frames/ holds captures of the target's
# screen.
# ---------------------------------------------------------------------------

def test_queue_dir_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("GHOSTCONTROL_QUEUE_DIR", r"X:\queue")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    assert config.queue_dir() == r"X:\queue"


def test_queue_dir_goes_to_localappdata(monkeypatch):
    monkeypatch.delenv("GHOSTCONTROL_QUEUE_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    assert config.queue_dir() == os.path.join(
        r"C:\Users\x\AppData\Local", "GhostControl", "queue")


def test_queue_dir_falls_back_to_project_without_localappdata(monkeypatch):
    monkeypatch.delenv("GHOSTCONTROL_QUEUE_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert config.queue_dir() == os.path.join(
        os.path.dirname(config.__file__), "queue")


def test_queue_dir_default_on_windows_stays_out_of_onedrive(monkeypatch):
    # The real case: LOCALAPPDATA set. The resolved path must not contain
    # 'OneDrive' -- that's the regression this change exists to prevent.
    monkeypatch.delenv("GHOSTCONTROL_QUEUE_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    assert "OneDrive" not in config.queue_dir()
