"""User ORM model."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.api_key import ApiKey
    from app.models.bookmark import Bookmark
    from app.models.project import Project
    from app.models.subscription import Subscription


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"
    BILLING = "billing"


class AccountStatus(str, enum.Enum):
    """Admin-controlled lifecycle for client accounts."""

    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    RESTRICTED = "restricted"


# Toolbox category ids clients can be granted (matches frontend toolbox catalog).
TOOLBOX_IDS: tuple[str, ...] = (
    "navigation",
    "layers",
    "image",
    "ai",
    "change",
    "maritime",
    "aviation",
    "terrain",
    "gis",
    "measure",
)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.VIEWER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # null = all toolboxes; list = only those toolbox ids
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    # null = all enabled satellites; list = satellite provider name keys
    allowed_satellites: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    # Stored as string for SQLite alter compatibility ("pending"|"approved"|…)
    account_status: Mapped[str] = mapped_column(
        String(32),
        default=AccountStatus.APPROVED.value,
        nullable=False,
    )

    projects: Mapped[list[Project]] = relationship(
        "Project", back_populates="owner", cascade="all, delete-orphan"
    )
    bookmarks: Mapped[list[Bookmark]] = relationship(
        "Bookmark", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    subscription: Mapped[Subscription | None] = relationship(
        "Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def status(self) -> AccountStatus:
        try:
            return AccountStatus(self.account_status)
        except ValueError:
            return AccountStatus.APPROVED

    def can_login(self) -> bool:
        if self.role == UserRole.ADMIN:
            return True
        if not self.is_active:
            return False
        return self.status in {AccountStatus.APPROVED, AccountStatus.RESTRICTED}

    def can_use_toolbox(self, toolbox_id: str) -> bool:
        if self.role == UserRole.ADMIN:
            return True
        if self.status in {AccountStatus.PENDING, AccountStatus.DECLINED}:
            return False
        if self.allowed_tools is None:
            return True
        return toolbox_id in self.allowed_tools

    def can_use_satellite(self, satellite_name: str) -> bool:
        if self.role == UserRole.ADMIN:
            return True
        if self.status in {AccountStatus.PENDING, AccountStatus.DECLINED}:
            return False
        if self.allowed_satellites is None:
            return True
        return satellite_name in self.allowed_satellites
