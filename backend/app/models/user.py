"""User, Role, and Permission models with RBAC."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

user_journals = Table(
    "user_journals",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("journal_id", Integer, ForeignKey("journals.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    roles: Mapped[List["Role"]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))

    users: Mapped[List["User"]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[List[Permission]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    organization: Mapped[Optional[str]] = mapped_column(String(255))
    access_status: Mapped[str] = mapped_column(String(32), default="approved")
    openai_api_key: Mapped[str] = mapped_column(Text, default="")
    openai_model: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")
    gpt_review_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    service_privileges: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    roles: Mapped[List[Role]] = relationship(secondary=user_roles, back_populates="users")
    allowed_journals: Mapped[List["Journal"]] = relationship(  # noqa: F821
        "Journal",
        secondary=user_journals,
        lazy="selectin",
    )
    projects: Mapped[List["Project"]] = relationship(back_populates="owner")  # noqa: F821
    bookmarks: Mapped[List["Bookmark"]] = relationship(back_populates="user")  # noqa: F821
    aois: Mapped[List["AreaOfInterest"]] = relationship(back_populates="user")  # noqa: F821
    subscription: Mapped[Optional["Subscription"]] = relationship(back_populates="user")  # noqa: F821
    api_keys: Mapped[List["APIKey"]] = relationship(back_populates="user")  # noqa: F821
    copernicus_token: Mapped[Optional["CopernicusToken"]] = relationship(  # noqa: F821
        back_populates="user", uselist=False
    )
    analysis_jobs: Mapped[List["AnalysisJob"]] = relationship(back_populates="user")  # noqa: F821

    def has_permission(self, resource: str, action: str) -> bool:
        if self.is_superuser:
            return True
        for role in self.roles:
            for perm in role.permissions:
                if perm.resource == resource and perm.action == action:
                    return True
        return False

    def has_role(self, role_name: str) -> bool:
        return any(role.name == role_name for role in self.roles)

    def is_full_admin(self) -> bool:
        """Operator account: every desk."""
        return bool(self.is_superuser or self.has_role("admin"))

    def resolved_privileges(self) -> dict:
        from app.core.privileges import (
            full_privileges,
            normalize_privileges,
            privileges_from_desks,
        )

        if self.is_full_admin():
            return full_privileges()
        if self.service_privileges is not None:
            return normalize_privileges(self.service_privileges)
        desks = [
            desk
            for desk in ("citation", "authors", "review", "galley")
            if self.has_role(f"admin_{desk}")
        ]
        return privileges_from_desks(desks)

    def has_service(self, service: str) -> bool:
        return service in self.resolved_privileges().get("services", [])

    def has_review_branch(self, branch: str) -> bool:
        return branch in self.resolved_privileges().get("review_branches", [])

    def has_author_wing(self, wing: str) -> bool:
        return wing in self.resolved_privileges().get("author_wings", [])

    def sees_all_journals(self) -> bool:
        return bool(self.resolved_privileges().get("all_journals"))

    def can_manage_users(self) -> bool:
        return self.is_full_admin() or self.has_role("admin_users")

    def has_desk(self, desk: str) -> bool:
        if self.is_full_admin():
            return True
        if desk == "users":
            return self.has_role("admin_users")
        return self.has_service(desk)

    def admin_desks(self) -> list[str]:
        from app.core.desks import DESKS

        if self.is_full_admin():
            return list(DESKS)
        granted = []
        for desk in DESKS:
            if desk == "users":
                if self.has_role("admin_users"):
                    granted.append(desk)
            elif self.has_service(desk):
                granted.append(desk)
        return granted

    def is_citation_admin(self) -> bool:
        """Archive crawl, add-journal, and search — operator only."""
        return self.is_full_admin()

    def portal_status(self) -> str:
        status = (self.access_status or "approved").strip().lower()
        if status not in ("pending", "approved", "restricted"):
            return "approved" if self.is_active else "restricted"
        return status

    def can_access_portal(self) -> bool:
        return bool(self.is_active) and self.portal_status() == "approved"
