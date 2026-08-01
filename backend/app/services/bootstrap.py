"""Bootstrap admin user and default data."""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus
from app.models.user import AccountStatus, User, UserRole


async def bootstrap_admin(session: AsyncSession) -> None:
    """Ensure the default administrator account exists."""
    settings = get_settings()
    result = await session.execute(select(User).where(User.email == settings.admin_email))
    admin = result.scalar_one_or_none()
    if admin is not None:
        # Keep legacy admin accounts fully unlocked after schema upgrades
        if getattr(admin, "account_status", None) != AccountStatus.APPROVED.value:
            admin.account_status = AccountStatus.APPROVED.value
            admin.is_active = True
            admin.is_verified = True
        logger.debug("Admin user already exists: {}", settings.admin_email)
        return

    admin = User(
        email=settings.admin_email,
        hashed_password=hash_password(settings.admin_password),
        full_name=settings.admin_full_name,
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
        account_status=AccountStatus.APPROVED.value,
        allowed_tools=None,
        allowed_satellites=None,
        organization="EarthVision Technologies",
    )
    session.add(admin)
    await session.flush()

    subscription = Subscription(
        user_id=admin.id,
        plan=PlanTier.ENTERPRISE,
        status=SubscriptionStatus.ACTIVE,
        seats=100,
        monthly_price=0.0,
        scene_quota=100_000,
        storage_gb=1000.0,
        ml_credits=10_000,
    )
    session.add(subscription)
    logger.info("Bootstrapped admin user: {}", settings.admin_email)
