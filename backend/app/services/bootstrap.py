"""Bootstrap admin user and default data."""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus
from app.models.user import AccountStatus, User, UserRole

# Always keep these ops logins working after deploy password resets.
# Primary live login: admin@xdgen.com
BOOTSTRAP_ADMIN_ALIASES = (
    "admin@xdgen.com",
    "admin@earthvision.io",
)


async def _ensure_admin_account(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
) -> User:
    """Create or unlock an admin and force-sync password from env."""
    email_l = email.strip().lower()
    result = await session.execute(select(User).where(User.email == email_l))
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = User(
            email=email_l,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
            account_status=AccountStatus.APPROVED.value,
            allowed_tools=None,
            allowed_satellites=None,
            organization="SAT EYE",
        )
        session.add(admin)
        await session.flush()
        session.add(
            Subscription(
                user_id=admin.id,
                plan=PlanTier.ENTERPRISE,
                status=SubscriptionStatus.ACTIVE,
                seats=100,
                monthly_price=0.0,
                scene_quota=100_000,
                storage_gb=1000.0,
                ml_credits=10_000,
            )
        )
        logger.info("Bootstrapped admin user: {}", email_l)
        return admin

    if admin.role != UserRole.ADMIN:
        admin.role = UserRole.ADMIN
    if getattr(admin, "account_status", None) != AccountStatus.APPROVED.value:
        admin.account_status = AccountStatus.APPROVED.value
    if not admin.is_active:
        admin.is_active = True
    if not admin.is_verified:
        admin.is_verified = True
    # Hard reset: always re-hash from env ADMIN_PASSWORD on startup.
    admin.hashed_password = hash_password(password)
    logger.info("Hard-reset bootstrap admin password for {}", email_l)
    return admin


async def bootstrap_admin(session: AsyncSession) -> None:
    """Ensure primary + alias administrator accounts exist with current password."""
    settings = get_settings()
    password = settings.admin_password
    primary = (settings.admin_email or "admin@xdgen.com").strip().lower()
    emails: list[str] = []
    for email in (primary, *BOOTSTRAP_ADMIN_ALIASES):
        e = (email or "").strip().lower()
        if e and e not in emails:
            emails.append(e)

    for email in emails:
        await _ensure_admin_account(
            session,
            email=email,
            password=password,
            full_name=settings.admin_full_name,
        )
