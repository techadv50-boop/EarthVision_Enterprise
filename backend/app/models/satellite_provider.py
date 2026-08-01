"""Admin-managed satellite / catalog provider definitions."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SatelliteProvider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Global satellite option available to all client accounts when enabled."""

    __tablename__ = "satellite_providers"
    __table_args__ = (UniqueConstraint("name", name="uq_satellite_providers_name"),)

    # Stable key used by the UI / catalog request (e.g. SENTINEL-2)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Client-facing label
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    # OData / STAC collection identifier used in catalog queries
    collection_id: Mapped[str] = mapped_column(String(128), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_password: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
