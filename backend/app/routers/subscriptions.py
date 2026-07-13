"""Subscription and API key routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.common import MessageResponse
from app.schemas.subscription import (
    ApiKeyCreate,
    ApiKeyResponse,
    PlanInfo,
    PlanUpgradeRequest,
    SubscriptionResponse,
)
from app.services.api_key_service import ApiKeyService
from app.services.subscription_service import SubscriptionService

router = APIRouter(tags=["Billing"])


@router.get("/subscriptions/me", response_model=SubscriptionResponse)
async def my_subscription(db: DbSession, user: CurrentUser) -> SubscriptionResponse:
    service = SubscriptionService(db)
    sub = await service.get_for_user(user)
    return SubscriptionResponse.model_validate(sub)


@router.get("/subscriptions/plans", response_model=list[PlanInfo])
async def list_plans(db: DbSession) -> list[PlanInfo]:
    service = SubscriptionService(db)
    return service.list_plans()


@router.post("/subscriptions/upgrade", response_model=SubscriptionResponse)
async def upgrade_plan(
    data: PlanUpgradeRequest, db: DbSession, user: CurrentUser
) -> SubscriptionResponse:
    service = SubscriptionService(db)
    sub = await service.upgrade(user, data.plan)
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/cancel", response_model=SubscriptionResponse)
async def cancel_plan(db: DbSession, user: CurrentUser) -> SubscriptionResponse:
    service = SubscriptionService(db)
    sub = await service.cancel(user)
    return SubscriptionResponse.model_validate(sub)


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(db: DbSession, user: CurrentUser) -> list[ApiKeyResponse]:
    service = ApiKeyService(db)
    keys = await service.list_for_user(user)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    data: ApiKeyCreate, db: DbSession, user: CurrentUser
) -> ApiKeyResponse:
    service = ApiKeyService(db)
    key, raw = await service.create(user, data)
    resp = ApiKeyResponse.model_validate(key)
    resp.raw_key = raw
    return resp


@router.delete("/api-keys/{key_id}", response_model=MessageResponse)
async def revoke_api_key(key_id: str, db: DbSession, user: CurrentUser) -> MessageResponse:
    service = ApiKeyService(db)
    await service.revoke(key_id, user)
    return MessageResponse(message="API key revoked")
