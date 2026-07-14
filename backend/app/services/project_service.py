"""Project management service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, owner: User, data: ProjectCreate) -> Project:
        project = Project(owner_id=owner.id, **data.model_dump())
        self.session.add(project)
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def get(self, project_id: str, user: User) -> Project:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            raise NotFoundError("Project not found")
        if project.owner_id != user.id and user.role != UserRole.ADMIN:
            raise ForbiddenError("Access denied to this project")
        return project

    async def list_for_user(
        self, user: User, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[Project], int]:
        query = select(Project)
        count_query = select(func.count()).select_from(Project)
        if user.role != UserRole.ADMIN:
            query = query.where(Project.owner_id == user.id)
            count_query = count_query.where(Project.owner_id == user.id)
        total = (await self.session.execute(count_query)).scalar_one()
        result = await self.session.execute(
            query.order_by(Project.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def update(self, project_id: str, user: User, data: ProjectUpdate) -> Project:
        project = await self.get(project_id, user)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(project, key, value)
        await self.session.flush()
        await self.session.refresh(project)
        return project

    async def delete(self, project_id: str, user: User) -> None:
        project = await self.get(project_id, user)
        await self.session.delete(project)
        await self.session.flush()
