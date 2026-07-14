"""User domain service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")
        if not user.is_active:
            raise UnauthorizedError("Account is deactivated")
        return user

    async def create(self, data: UserCreate) -> User:
        existing = await self.get_by_email(data.email)
        if existing is not None:
            raise ConflictError("Email already registered")
        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            organization=data.organization,
            allowed_tools=data.allowed_tools,
            is_active=True,
            is_verified=False,
        )
        self.session.add(user)
        await self.session.flush()
        subscription = Subscription(
            user_id=user.id,
            plan=PlanTier.FREE,
            status=SubscriptionStatus.ACTIVE,
            seats=1,
            monthly_price=0.0,
            scene_quota=100,
            storage_gb=5.0,
            ml_credits=10,
        )
        self.session.add(subscription)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update(self, user_id: str, data: UserUpdate) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(user, key, value)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def list_users(
        self, *, page: int = 1, page_size: int = 20, role: UserRole | None = None
    ) -> tuple[list[User], int]:
        query = select(User)
        count_query = select(func.count()).select_from(User)
        if role is not None:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)
        total = (await self.session.execute(count_query)).scalar_one()
        result = await self.session.execute(
            query.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise UnauthorizedError("Current password is incorrect")
        user.hashed_password = hash_password(new_password)
        await self.session.flush()
