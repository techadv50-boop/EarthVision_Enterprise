"""Cached satellite scene metadata."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class CachedScene(Base):
    __tablename__ = "cached_scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    collection: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    acquisition_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cloud_cover: Mapped[Optional[float]] = mapped_column(Float)
    footprint_geojson: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    preview_path: Mapped[Optional[str]] = mapped_column(String(500))
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
