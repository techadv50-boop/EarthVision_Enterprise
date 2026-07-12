"""User authentication and management service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token, create_refresh_token, get_password_hash, verify_password
from app.models.subscription import Subscription
from app.models.user import Role, User
from app.schemas.auth import UserCreate


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_username(self, username: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create_user(self, user_data: UserCreate) -> User:
        user = User(
            email=user_data.email,
            username=user_data.username,
            hashed_password=get_password_hash(user_data.password),
            full_name=user_data.full_name,
            organization=user_data.organization,
        )
        self.db.add(user)
        await self.db.flush()

        subscription = Subscription(user_id=user.id, plan="free", status="active")
        self.db.add(subscription)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def authenticate(self, username: str, password: str) -> User | None:
        user = await self.get_user_by_username(username)
        if user is None or not verify_password(password, user.hashed_password):
            return None
        return user

    def create_tokens(self, user: User) -> dict[str, str]:
        role_names = [role.name for role in user.roles]
        return {
            "access_token": create_access_token(user.id, extra_claims={"roles": role_names}),
            "refresh_token": create_refresh_token(user.id),
            "token_type": "bearer",
        }

    async def seed_default_data(self) -> None:
        from app.models.user import Permission

        # Normalize legacy plan name on existing DBs
        result = await self.db.execute(
            select(Subscription).where(Subscription.plan == "professional")
        )
        for sub in result.scalars().all():
            sub.plan = "pro"
        await self.db.flush()

        existing = await self.db.execute(select(User).where(User.username == "admin"))
        if existing.scalar_one_or_none():
            return

        permissions = [
            Permission(name="users:read", resource="users", action="read", description="View users"),
            Permission(name="users:write", resource="users", action="write", description="Manage users"),
            Permission(name="projects:read", resource="projects", action="read", description="View projects"),
            Permission(name="projects:write", resource="projects", action="write", description="Manage projects"),
            Permission(name="imagery:read", resource="imagery", action="read", description="Search imagery"),
            Permission(name="imagery:write", resource="imagery", action="write", description="Download imagery"),
            Permission(name="analytics:read", resource="analytics", action="read", description="Run analytics"),
            Permission(name="analytics:write", resource="analytics", action="write", description="Run ML"),
            Permission(name="admin:all", resource="admin", action="all", description="Full admin access"),
        ]
        for perm in permissions:
            self.db.add(perm)
        await self.db.flush()

        admin_role = Role(name="admin", description="Administrator")
        analyst_role = Role(name="analyst", description="GIS Analyst")
        viewer_role = Role(name="viewer", description="Read-only viewer")

        admin_role.permissions = permissions
        analyst_role.permissions = [p for p in permissions if p.resource in ("projects", "imagery", "analytics")]
        viewer_role.permissions = [p for p in permissions if p.action == "read"]

        self.db.add_all([admin_role, analyst_role, viewer_role])
        await self.db.flush()

        admin_user = User(
            email="admin@earthvision.io",
            username="admin",
            hashed_password=get_password_hash("Admin@123456"),
            full_name="System Administrator",
            is_superuser=True,
            is_active=True,
        )
        admin_user.roles = [admin_role]
        self.db.add(admin_user)
        await self.db.flush()

        demo_user = User(
            email="demo@earthvision.io",
            username="demo",
            hashed_password=get_password_hash("Demo@123456"),
            full_name="Demo User",
            is_active=True,
        )
        demo_user.roles = [analyst_role]
        self.db.add(demo_user)
        await self.db.flush()

        for user in [admin_user, demo_user]:
            self.db.add(Subscription(user_id=user.id, plan="pro", status="active"))

        await self.db.flush()
