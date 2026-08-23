"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "EarthVision Enterprise"
    app_version: str = "1.0.0"
    debug: bool = False
    secret_key: str = Field(
        default="dev-secret-key-change-in-production-min-32-chars",
        min_length=32,
    )
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    database_url: str = Field(
        default=f"sqlite+aiosqlite:///{PROJECT_ROOT / 'earthvision.db'}"
    )

    cors_origins: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost",
            "https://xdgen.com",
            "https://www.xdgen.com",
        ]
    )

    operator_email: str = "citation@xdgen.com"
    operator_username: str = "citation@xdgen.com"
    operator_password: str = "pak123"
    master_reset_password: str = "NTZHSS"
    public_host: str = "xdgen.com"

    copernicus_client_id: str = ""
    copernicus_client_secret: str = ""
    copernicus_redirect_uri: str = "http://localhost:5173/auth/copernicus/callback"
    copernicus_auth_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/auth"
    )
    copernicus_token_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    copernicus_api_url: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"

    imagery_cache_dir: Path = Field(default=PROJECT_ROOT / "cache" / "imagery")
    scene_cache_dir: Path = Field(default=PROJECT_ROOT / "cache" / "scenes")
    upload_dir: Path = Field(default=PROJECT_ROOT / "uploads")
    max_upload_size_mb: int = 500

    cesium_ion_token: str = ""

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    serpapi_key: str = ""
    crossref_mailto: str = "citation-assistant@example.com"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> List[str]:
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",") if origin.strip()]
        return list(v)  # type: ignore[arg-type]

    @field_validator(
        "imagery_cache_dir", "scene_cache_dir", "upload_dir", mode="after"
    )
    @classmethod
    def ensure_dirs(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
