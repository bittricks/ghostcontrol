# -*- coding: utf-8 -*-
"""Credential loading — the most security-sensitive code path.

What these tests protect: the unlock password must load from the local
environment, a gitignored .env, or the OS keyring — never from the repo —
and must never leak into a log line, a repr, or a traceback.
"""
import os

import pytest

import credentials as cr


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(cr.ENV_USERNAME, raising=False)
    monkeypatch.delenv(cr.ENV_PASSWORD, raising=False)


# --- resolution order --------------------------------------------------

def test_environment_variables_win(monkeypatch):
    monkeypatch.setenv(cr.ENV_USERNAME, "alice")
    monkeypatch.setenv(cr.ENV_PASSWORD, "s3cret")
    c = cr.load_credentials(env_file="does-not-exist", allow_keyring=False)
    assert (c.username, c.password, c.source) == ("alice", "s3cret", "env")


def test_env_file_used_when_environment_is_empty(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        'VERIKVM_USERNAME="bob"\n'
        "VERIKVM_PASSWORD = 'p@ss word'\n", encoding="utf-8")
    c = cr.load_credentials(env_file=str(env), allow_keyring=False)
    assert c.username == "bob"
    assert c.password == "p@ss word"   # quotes stripped, spaces kept
    assert c.source == "env-file"


def test_environment_overrides_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("VERIKVM_PASSWORD=from-file\n", encoding="utf-8")
    monkeypatch.setenv(cr.ENV_PASSWORD, "from-env")
    c = cr.load_credentials(env_file=str(env), allow_keyring=False)
    assert c.password == "from-env"
    assert c.source == "env"


def test_keyring_is_the_last_resort(monkeypatch):
    monkeypatch.setenv(cr.ENV_USERNAME, "carol")
    fake = type("K", (), {"get_password": staticmethod(
        lambda service, user: "kr-pass" if user == "carol" else None)})
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    c = cr.load_credentials(env_file="none", allow_keyring=True)
    assert c.password == "kr-pass"
    assert c.source == "keyring"


# --- the "prompt at runtime" path --------------------------------------

def test_nothing_set_leaves_password_none(tmp_path):
    """No env, no file, no keyring -> password None, so the caller prompts
    instead of assuming. This is the fail-closed default."""
    c = cr.load_credentials(env_file=str(tmp_path / "nope"), allow_keyring=False)
    assert c.password is None
    assert c.has_password is False
    assert c.source is None


def test_blank_password_in_env_file_means_prompt(tmp_path):
    env = tmp_path / ".env"
    env.write_text("VERIKVM_USERNAME=dave\nVERIKVM_PASSWORD=\n", encoding="utf-8")
    c = cr.load_credentials(env_file=str(env), allow_keyring=False)
    assert c.username == "dave"
    assert c.password is None          # blank is not a password


def test_missing_env_file_does_not_crash(tmp_path):
    c = cr.load_credentials(env_file=str(tmp_path / "absent"), allow_keyring=False)
    assert c.source is None


# --- the password must never leak --------------------------------------

def test_repr_never_contains_the_password():
    c = cr.Credentials("eve", "TOP-SECRET-123", "env")
    assert "TOP-SECRET-123" not in repr(c)
    assert "redacted" in repr(c)


def test_redact_hides_the_value_but_not_the_length():
    assert cr.redact("abcd") == "<redacted:4 chars>"
    assert cr.redact("") == "<none>"
    assert cr.redact(None) == "<none>"
    assert "secret" not in cr.redact("secret")


def test_env_file_parser_ignores_comments_and_blanks(tmp_path):
    env = tmp_path / ".env"
    env.write_text("\n# only comments\n   \nNOT_A_PAIR\n", encoding="utf-8")
    assert cr._parse_env_file(str(env)) == {}
