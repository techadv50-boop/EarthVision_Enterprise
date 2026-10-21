"""Plugin-first tool category tree and placements (Host Platform config)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Safe technical limit for nesting (logical "unlimited" for admins).
MAX_CATEGORY_DEPTH = 32


class ToolCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Administrator-defined category / subcategory node."""

    __tablename__ = "tool_categories"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tool_categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collapsed_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parent: Mapped[ToolCategory | None] = relationship(
        "ToolCategory",
        remote_side="ToolCategory.id",
        back_populates="children",
    )
    children: Mapped[list[ToolCategory]] = relationship(
        "ToolCategory",
        back_populates="parent",
    )
    placements: Mapped[list[ToolPlacement]] = relationship(
        "ToolPlacement",
        back_populates="category",
    )


class ToolPlacement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Where an installed plugin appears in the tree and which UI slot it opens in."""

    __tablename__ = "tool_placements"
    __table_args__ = (
        UniqueConstraint("plugin_id", name="uq_tool_placement_plugin"),
    )

    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    category_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tool_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Navigation vs execution are independent.
    execution_slot: Mapped[str] = mapped_column(
        String(64), nullable=False, default="right_analysis_panel"
    )
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Optional allowlist of user ids / roles; null = all authenticated users who may see active plugins
    visibility: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Imagery applicability declared at upload / placement (empty = not specified).
    # Keys from app.core.imagery_resolution.RESOLUTION_BANDS (e.g. lte_10m, lt_30m).
    applicable_resolutions: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    # Optional satellite provider keys (e.g. SENTINEL-2); empty/null = any satellite.
    applicable_satellites: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    category: Mapped[ToolCategory] = relationship("ToolCategory", back_populates="placements")


class ToolTreeRevision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Snapshot of the tool tree for export / restore / audit."""

    __tablename__ = "tool_tree_revisions"

    label: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
