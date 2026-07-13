"""Satellite scene cache ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Scene(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "scenes"

    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    collection: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sensing_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    footprint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="discovered", nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
