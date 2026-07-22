"""Cookie resolution: override → firefox-family → chromium → no-auth."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from tokenmaxxr import cookies
from tokenmaxxr.cookies import resolve


def _make_firefox_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE moz_cookies ("
        "id INTEGER PRIMARY KEY, name TEXT, value TEXT, host_key TEXT, "
        "path TEXT, expiry INTEGER, is_secure INTEGER, is_httponly INTEGER)"
    )
    conn.executemany(
        "INSERT INTO moz_cookies "
        "(name, value, host_key, path, expiry, is_secure, is_httponly) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_override_wins(tmp_path: Path):
    db = tmp_path / "cookies.sqlite"
    _make_firefox_db(
        db,
        [
            ("sid", "abc", ".app.cline.bot", "/", 0, 1, 0),
            ("other", "x", ".example.com", "/", 0, 0, 0),
        ],
    )
    jar, src = resolve("app.cline.bot", override=str(db))
    assert src is not None and src.kind == "override"
    assert any(c.name == "sid" and c.value == "abc" for c in jar)


def test_env_override(monkeypatch, tmp_path: Path):
    db = tmp_path / "env-cookies.sqlite"
    _make_firefox_db(db, [("sid", "v", ".app.cline.bot", "/", 0, 1, 0)])
    monkeypatch.setenv("TOKENMAXXR_COOKIE_APP_CLINE_BOT", str(db))
    jar, src = resolve("app.cline.bot")
    assert src is not None
    assert any(c.name == "sid" for c in jar)


def test_missing_everywhere(tmp_path: Path, monkeypatch):
    # Point all firefox globs into an empty dir so nothing is discovered.
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(
        cookies,
        "FIREFOX_GLOBS",
        [str(empty / "*" / "cookies.sqlite")],
    )
    jar, src = resolve("app.cline.bot")
    assert jar is None
    assert src is None


def test_firefox_glob(monkeypatch, tmp_path: Path):
    profile = tmp_path / "firefox" / "abc.default"
    profile.mkdir(parents=True)
    db = profile / "cookies.sqlite"
    _make_firefox_db(db, [("sid", "v", ".app.cline.bot", "/", 0, 1, 0)])
    monkeypatch.setattr(
        cookies,
        "FIREFOX_GLOBS",
        [str(tmp_path / "firefox" / "*" / "cookies.sqlite")],
    )
    jar, src = resolve("app.cline.bot")
    assert src is not None and src.kind == "firefox"
    assert any(c.name == "sid" for c in jar)


def test_no_cookie_values_in_diagnostics(tmp_path: Path):
    db = tmp_path / "cookies.sqlite"
    _make_firefox_db(db, [("supersecret", "TOPSECRET", ".app.cline.bot", "/", 0, 1, 0)])
    sources = cookies.discover_sources("app.cline.bot")
    # No source detail should ever contain the secret value.
    blob = " ".join(repr(s) for s in sources)
    assert "TOPSECRET" not in blob
