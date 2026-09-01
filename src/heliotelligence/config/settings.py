"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Database
    database_url: str
    # Set automatically from sslmode in the URL — do not set manually in .env
    database_ssl: bool = False

    # App
    # APP_ENV is canonical. ENVIRONMENT remains a compatibility alias so an
    # older deployment cannot silently fall back to development.
    app_env: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"),
    )
    log_level: str = "INFO"
    secret_key: str = "change-me-in-production"
    run_scheduler: bool = True
    cors_origins: str = (
        "http://localhost:5173,"
        "https://heliotelligence.web.app,"
        "https://heliotelligence.firebaseapp.com,"
        "https://app.heliotelligence.com"
    )

    # Site config
    site_config_path: Path = Path("config/sites.yaml")

    # Solcast
    solcast_api_key: str = ""
    solcast_poll_interval_minutes: int = 60

    # SCADA CSV watcher
    scada_csv_poll_interval_minutes: int = 5

    # Physics pipeline
    physics_pipeline_interval_minutes: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a normalised list."""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_staging(self) -> bool:
        return self.app_env == "staging"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def normalise_database_url(self) -> "Settings":
        """Normalise scheme and extract sslmode for asyncpg compatibility.

        asyncpg does not accept sslmode= as a query parameter (libpq convention).
        We strip it from the URL and store it as database_ssl so db/session.py
        can pass connect_args={"ssl": True} to create_async_engine.
        """
        url = self.database_url

        # 1. Normalise scheme to postgresql+asyncpg://
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break

        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use postgresql+asyncpg://, postgresql://, or "
                "postgres:// scheme"
            )

        # 2. Strip sslmode from query string; set database_ssl flag
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        sslmode = params.pop("sslmode", [None])[0]

        ssl_required = sslmode in ("require", "verify-ca", "verify-full")
        clean_query = urlencode({key: value[0] for key, value in params.items()})
        clean_url = urlunparse(parsed._replace(query=clean_query))

        # Use object.__setattr__ because pydantic models are frozen after init
        object.__setattr__(self, "database_url", clean_url)
        object.__setattr__(self, "database_ssl", ssl_required)
        return self

    @model_validator(mode="after")
    def validate_deployed_environment(self) -> "Settings":
        """Fail fast on unsafe staging/production defaults."""
        if self.app_env in {"staging", "production"} and (
            self.secret_key == "change-me-in-production"
        ):
            raise ValueError(
                f"SECRET_KEY must be configured when APP_ENV={self.app_env}"
            )
        return self


settings = Settings()
