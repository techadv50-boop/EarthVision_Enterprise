"""Application configuration using Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SAT EYE runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "SAT EYE"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    secret_key: str = Field(
        default="earthvision-dev-secret-change-in-production-32chars!!",
        min_length=32,
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://frontend:5173",
        ]
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./earthvision.db"
    database_echo: bool = False
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # JWT
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # Redis / Cache
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    imagery_cache_dir: Path = Path("../cache")
    imagery_dir: Path = Path("../imagery")
    uploads_dir: Path = Path("../uploads")
    logs_dir: Path = Path("../logs")

    # Copernicus Data Space Ecosystem
    copernicus_token_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    copernicus_catalog_url: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"
    copernicus_download_url: str = "https://download.dataspace.copernicus.eu/odata/v1"
    copernicus_client_id: str = "cdse-public"
    copernicus_username: str = ""
    copernicus_password: str = ""

    # Cesium / Maps
    cesium_ion_token: str = ""
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    # Admin bootstrap
    admin_email: str = "admin@earthvision.io"
    admin_password: str = "Alihussain"
    admin_full_name: str = "System Administrator"

    # Billing (stub endpoints for commercial integration)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def ensure_directories(self) -> None:
        """Create runtime directories if they do not exist."""
        for path in (
            self.imagery_cache_dir,
            self.imagery_dir,
            self.uploads_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    settings = Settings()
    settings.ensure_directories()
    return settings
