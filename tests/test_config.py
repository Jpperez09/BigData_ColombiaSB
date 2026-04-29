"""Tests for utils.config — no real Supabase calls, no real .env required."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from utils.config import Settings


def test_settings_loads_from_env_file(tmp_path, monkeypatch):
    """Settings reads values from an .env file in the current directory."""
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=https://abc123.supabase.co\n"
        "SUPABASE_SERVICE_KEY=secret_key\n"
        "LOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # Remove any env vars that would take priority over the .env file
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings()

    assert settings.SUPABASE_URL == "https://abc123.supabase.co"
    assert settings.SUPABASE_SERVICE_KEY == "secret_key"
    assert settings.LOG_LEVEL == "DEBUG"


def test_invalid_supabase_url_rejected(monkeypatch):
    """SUPABASE_URL with http:// (not https) must raise ValidationError."""
    monkeypatch.setenv("SUPABASE_URL", "http://malo.com")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "SUPABASE_URL" in str(exc_info.value)


def test_invalid_log_level_rejected(monkeypatch):
    """LOG_LEVEL=VERBOSE is not in the allowed set and must raise ValidationError."""
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "LOG_LEVEL" in str(exc_info.value)
