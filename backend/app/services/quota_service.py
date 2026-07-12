"""Subscription quota enforcement."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.analysis import AnalysisJob
from app.models.scene import CachedScene
from app.models.subscription import Subscription
from app.models.user import User

# Mirrors billing.PLANS limits (kept here to avoid router <-> service import cycles).
PLAN_LIMITS = {
    "free": {"max_scenes_per_month": 100, "max_storage_gb": 5, "max_api_calls_per_day": 1000},
    "pro": {"max_scenes_per_month": 2000, "max_storage_gb": 100, "max_api_calls_per_day": 20000},
    "professional": {  # legacy alias
        "max_scenes_per_month": 2000,
        "max_storage_gb": 100,
        "max_api_calls_per_day": 20000,
    },
    "enterprise": {
        "max_scenes_per_month": 50000,
        "max_storage_gb": 2000,
        "max_api_calls_per_day": 500000,
    },
}

# Analysis jobs count toward a soft monthly cap derived from plan scenes limit.
ANALYSIS_QUOTA_RATIO = 2


class QuotaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_subscription(self, user_id: int) -> Subscription:
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user_id, plan="free", status="active")
            self.db.add(sub)
            await self.db.flush()
        elif sub.plan == "professional":
            sub.plan = "pro"
            await self.db.flush()
        return sub

    def _plan_limits(self, sub: Subscription) -> dict:
        plan = PLAN_LIMITS.get(sub.plan, PLAN_LIMITS["free"])
        max_scenes = sub.max_scenes_per_month or plan["max_scenes_per_month"]
        return {
            "max_scenes_per_month": max_scenes,
            "max_storage_gb": sub.max_storage_gb or plan["max_storage_gb"],
            "max_api_calls_per_day": sub.max_api_calls_per_day or plan["max_api_calls_per_day"],
            "max_analysis_per_month": max_scenes * ANALYSIS_QUOTA_RATIO,
        }

    @staticmethod
    def _period_start() -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def check_scene_download(self, user_id: int) -> None:
        sub = await self.get_or_create_subscription(user_id)
        if sub.status not in ("active", "trialing"):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Subscription status '{sub.status}' does not allow downloads",
            )
        limits = self._plan_limits(sub)
        period_start = self._period_start()
        result = await self.db.execute(
            select(func.count())
            .select_from(CachedScene)
            .where(
                CachedScene.user_id == user_id,
                CachedScene.cached_at >= period_start,
            )
        )
        count = int(result.scalar_one() or 0)
        if count >= limits["max_scenes_per_month"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Monthly scene download quota exceeded "
                    f"({count}/{limits['max_scenes_per_month']} for plan '{sub.plan}')"
                ),
            )

    async def check_analysis(self, user_id: int) -> None:
        sub = await self.get_or_create_subscription(user_id)
        if sub.status not in ("active", "trialing"):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Subscription status '{sub.status}' does not allow analysis",
            )
        limits = self._plan_limits(sub)
        period_start = self._period_start()
        result = await self.db.execute(
            select(func.count())
            .select_from(AnalysisJob)
            .where(
                AnalysisJob.user_id == user_id,
                AnalysisJob.created_at >= period_start,
            )
        )
        count = int(result.scalar_one() or 0)
        if count >= limits["max_analysis_per_month"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Monthly analysis quota exceeded "
                    f"({count}/{limits['max_analysis_per_month']} for plan '{sub.plan}')"
                ),
            )


async def enforce_scene_quota(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await QuotaService(db).check_scene_download(current_user.id)


async def enforce_analysis_quota(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await QuotaService(db).check_analysis(current_user.id)
