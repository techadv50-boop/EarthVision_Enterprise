"""Subscription schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.subscription import PlanTier, SubscriptionStatus


class SubscriptionResponse(BaseModel):
    id: str
    plan: PlanTier
    status: SubscriptionStatus
    seats: int
    monthly_price: float
    scene_quota: int
    scenes_used: int
    storage_gb: float
    storage_used_gb: float
    ml_credits: int
    ml_credits_used: int
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool

    model_config = {"from_attributes": True}


class PlanUpgradeRequest(BaseModel):
    plan: PlanTier


class PlanInfo(BaseModel):
    plan: PlanTier
    name: str
    monthly_price: float
    scene_quota: int
    storage_gb: float
    ml_credits: int
    seats: int
    features: list[str]


class ApiKeyCreate(BaseModel):
    name: str
    description: str | None = None
    scopes: str = "read,write"
    expires_days: int | None = None


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    description: str | None
    is_active: bool
    scopes: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    # Only returned on creation
    raw_key: str | None = None

    model_config = {"from_attributes": True}
