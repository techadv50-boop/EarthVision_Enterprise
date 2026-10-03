"""Galley composition journals, proofs, and settings (JSON documents)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.models.user import User


class GalleyJournal(Base):
    __tablename__ = "galley_journals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class GalleyProof(Base):
    __tablename__ = "galley_proofs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    owner: Mapped[User] = relationship()


class GalleySetting(Base):
    __tablename__ = "galley_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
