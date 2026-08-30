"""Tests for environment-aware application settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from heliotelligence.config.settings import Settings


DATABASE_URL = "postgresql://test:test@localhost:5432/test"


def test_app_env_accepts_explicit_field_name() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        app_env="staging",
        secret_key="staging-secret",
        _env_file=None,
    )

    assert settings.app_env == "staging"
    assert settings.is_staging
    assert not settings.is_production


def test_legacy_environment_alias_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("SECRET_KEY", "production-secret")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.is_production


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY must be configured"):
        Settings(
            database_url=DATABASE_URL,
            app_env="production",
            _env_file=None,
        )


def test_cors_origins_are_normalised() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        cors_origins="http://localhost:5173, https://staging.example.com,",
        _env_file=None,
    )

    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "https://staging.example.com",
    ]
