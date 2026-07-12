"""Seed EarthVision database with demo users, roles, and a sample project.

Usage (from repo root):
  set PYTHONPATH=backend
  python scripts/seed.py

Idempotent: skips creation when admin already exists (AuthService.seed_default_data).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.database.session import AsyncSessionLocal, init_db  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from sqlalchemy import select  # noqa: E402


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        auth = AuthService(session)
        await auth.seed_default_data()

        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin is None:
            print("ERROR: admin user was not created")
            return

        projects = await session.execute(
            select(Project).where(Project.owner_id == admin.id, Project.name == "Demo EO Workspace")
        )
        if projects.scalar_one_or_none() is None:
            session.add(
                Project(
                    owner_id=admin.id,
                    name="Demo EO Workspace",
                    description="Seeded project for Earth Observation demos (SF Bay / AOI workflows).",
                )
            )
            print("Created demo project: Demo EO Workspace")
        else:
            print("Demo project already exists")

        await session.commit()
        print("Seed complete.")
        print("  admin / Admin@123456")
        print("  demo / Demo@123456")


if __name__ == "__main__":
    asyncio.run(main())
