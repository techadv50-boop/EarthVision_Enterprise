"""Subscription and billing service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus
from app.models.user import User
from app.schemas.subscription import PlanInfo

PLAN_CATALOG: dict[PlanTier, PlanInfo] = {
    PlanTier.FREE: PlanInfo(
        plan=PlanTier.FREE,
        name="Free",
        monthly_price=0.0,
        scene_quota=100,
        storage_gb=5.0,
        ml_credits=10,
        seats=1,
        features=[
            "Interactive 3D globe",
            "Sentinel-2 catalog search",
            "Basic indices (NDVI, NDWI)",
            "Community support",
        ],
    ),
    PlanTier.PROFESSIONAL: PlanInfo(
        plan=PlanTier.PROFESSIONAL,
        name="Professional",
        monthly_price=99.0,
        scene_quota=5_000,
        storage_gb=200.0,
        ml_credits=500,
        seats=5,
        features=[
            "All Free features",
            "Sentinel-1/2, Landsat, MODIS",
            "Full analytics suite",
            "Random Forest & SVM",
            "PDF/Excel reports",
            "API access",
            "Email support",
        ],
    ),
    PlanTier.ENTERPRISE: PlanInfo(
        plan=PlanTier.ENTERPRISE,
        name="Enterprise",
        monthly_price=999.0,
        scene_quota=100_000,
        storage_gb=5_000.0,
        ml_credits=10_000,
        seats=100,
        features=[
            "All Professional features",
            "Deep learning models",
            "Unlimited AOI analysis",
            "SSO & RBAC",
            "Dedicated support",
            "On-prem deployment option",
            "SLA 99.9%",
        ],
    ),
}


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(self, user: User) -> Subscription:
        result = await self.session.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        if subscription is None:
            raise NotFoundError("Subscription not found")
        return subscription

    def list_plans(self) -> list[PlanInfo]:
        return list(PLAN_CATALOG.values())

    async def upgrade(self, user: User, plan: PlanTier) -> Subscription:
        subscription = await self.get_for_user(user)
        info = PLAN_CATALOG[plan]
        subscription.plan = plan
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.monthly_price = info.monthly_price
        subscription.scene_quota = info.scene_quota
        subscription.storage_gb = info.storage_gb
        subscription.ml_credits = info.ml_credits
        subscription.seats = info.seats
        subscription.current_period_start = datetime.now(UTC)
        subscription.current_period_end = datetime.now(UTC) + timedelta(days=30)
        subscription.cancel_at_period_end = False
        await self.session.flush()
        await self.session.refresh(subscription)
        return subscription

    async def cancel(self, user: User) -> Subscription:
        subscription = await self.get_for_user(user)
        subscription.cancel_at_period_end = True
        await self.session.flush()
        await self.session.refresh(subscription)
        return subscription
