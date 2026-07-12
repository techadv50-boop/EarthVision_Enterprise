"""Initial schema baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-12

NOTE: In development, ``app.database.session.init_db`` still uses
``Base.metadata.create_all``. This revision documents the expected schema
and supports production upgrades (e.g. oauth_state columns). Run
``alembic upgrade head`` when managing schema via migrations.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lightweight additive migration for existing create_all DBs.
    # Full table creation is handled by create_all in development.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "copernicus_tokens" in tables:
        cols = {c["name"] for c in inspector.get_columns("copernicus_tokens")}
        if "oauth_state" not in cols:
            op.add_column(
                "copernicus_tokens",
                sa.Column("oauth_state", sa.String(length=128), nullable=True),
            )
        if "oauth_state_expires_at" not in cols:
            op.add_column(
                "copernicus_tokens",
                sa.Column("oauth_state_expires_at", sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "copernicus_tokens" not in tables:
        return
    cols = {c["name"] for c in inspector.get_columns("copernicus_tokens")}
    if "oauth_state_expires_at" in cols:
        op.drop_column("copernicus_tokens", "oauth_state_expires_at")
    if "oauth_state" in cols:
        op.drop_column("copernicus_tokens", "oauth_state")
