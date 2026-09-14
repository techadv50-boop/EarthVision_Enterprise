"""Admin-managed district/city shapefile layers for SatPass Predict."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AoiLayer(Base):
    __tablename__ = "satpass_aoi_layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    name_field: Mapped[Optional[str]] = mapped_column(String(80))
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
