"""Admin-managed folder repositories on relay.xdgen.com (separate from satellites)."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FolderRepository(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Relay folder archive — Bearer API key scoped to one folder."""

    __tablename__ = "folder_repositories"
    __table_args__ = (
        UniqueConstraint("repository_url", name="uq_folder_repositories_url"),
    )

    label: Mapped[str] = mapped_column(String(128), nullable=False)
    # Full repository address, e.g. https://relay.xdgen.com/api/v1/archives/Raza_uploads
    repository_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # Folder-scoped API key from the relay Repository card (never a Copernicus token).
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
