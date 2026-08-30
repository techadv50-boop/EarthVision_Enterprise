"""User authentication and management service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, get_password_hash, verify_password
from app.models.subscription import Subscription
from app.models.user import Role, User, user_roles
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
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        user_data: UserCreate,
        *,
        role_name: str = "user",
        approved: bool = True,
    ) -> User:
        status = "approved" if approved else "pending"
        user = User(
            email=user_data.email,
            username=user_data.username,
            hashed_password=get_password_hash(user_data.password),
            full_name=user_data.full_name,
            organization=user_data.organization,
            is_active=approved,
            access_status=status,
            is_superuser=approved and role_name == "admin",
        )
        self.db.add(user)
        await self.db.flush()

        wanted = "admin" if role_name == "admin" else "user"
        role_row = await self.db.execute(select(Role).where(Role.name == wanted))
        assigned = role_row.scalar_one_or_none()
        if assigned is None and wanted == "admin":
            role_row = await self.db.execute(select(Role).where(Role.name == "user"))
            assigned = role_row.scalar_one_or_none()
        if assigned is not None:
            await self.db.execute(user_roles.insert().values(user_id=user.id, role_id=assigned.id))
        subscription = Subscription(user_id=user.id, plan="free", status="active")
        self.db.add(subscription)
        await self.db.flush()
        loaded = await self.get_user_by_username(user.username)
        return loaded or user

    async def authenticate(self, username: str, password: str) -> User | None:
        ident = (username or "").strip()
        user = await self.get_user_by_username(ident)
        if user is None:
            user = await self.get_user_by_email(ident.lower())
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

        result = await self.db.execute(
            select(Subscription).where(Subscription.plan == "professional")
        )
        for sub in result.scalars().all():
            sub.plan = "pro"
        await self.db.flush()

        existing = await self.db.execute(select(User).where(User.username == "admin"))
        if existing.scalar_one_or_none() is None:
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
            analyst_role.permissions = [
                p for p in permissions if p.resource in ("projects", "imagery", "analytics")
            ]
            viewer_role.permissions = [p for p in permissions if p.action == "read"]

            user_role = Role(name="user", description="Citation user — New manuscript only")
            self.db.add_all([admin_role, analyst_role, viewer_role, user_role])
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

        await self.ensure_citation_roles()
        await self.ensure_operator_user()

    async def ensure_citation_roles(self) -> None:
        """Keep admin and user roles available after the first seed."""
        from app.models.user import Permission

        existing = {
            row.name: row
            for row in (await self.db.execute(select(Role))).scalars().all()
        }
        if "admin" not in existing:
            admin_role = Role(name="admin", description="Administrator — full Citation Assistant")
            perms = list((await self.db.execute(select(Permission))).scalars().all())
            admin_role.permissions = perms
            self.db.add(admin_role)
        if "user" not in existing:
            self.db.add(Role(name="user", description="Citation user — New manuscript only"))
        await self.db.flush()

    async def ensure_operator_user(self) -> None:
        """Create the XDGEN operator login if it is missing (does not overwrite an existing password)."""
        settings = get_settings()
        email = (settings.operator_email or "").strip().lower()
        if not email:
            return

        existing = await self.get_user_by_email(email)
        if existing is None:
            existing = await self.get_user_by_username(settings.operator_username or email)
        if existing is not None:
            return

        role_row = await self.db.execute(select(Role).where(Role.name == "admin"))
        admin_role = role_row.scalar_one_or_none()

        user = User(
            email=email,
            username=settings.operator_username or email,
            hashed_password=get_password_hash(settings.operator_password),
            full_name="XDGEN Citation Operator",
            organization="XDGEN",
            is_superuser=True,
            is_active=True,
        )
        if admin_role is not None:
            user.roles = [admin_role]
        self.db.add(user)
        await self.db.flush()
        self.db.add(Subscription(user_id=user.id, plan="pro", status="active"))
        await self.db.flush()

    async def reset_password_with_master(self, email: str, new_password: str) -> User | None:
        user = await self.get_user_by_email((email or "").strip().lower())
        if user is None:
            user = await self.get_user_by_username((email or "").strip())
        if user is None:
            return None
        user.hashed_password = get_password_hash(new_password)
        await self.db.flush()
        return user
