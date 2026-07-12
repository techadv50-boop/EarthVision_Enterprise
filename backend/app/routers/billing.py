"""Billing and subscription checkout routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.subscription import Subscription
from app.models.user import User

router = APIRouter(prefix="/billing", tags=["Billing"])

PLANS = {
    "free": {
        "name": "Free",
        "price_usd": 0,
        "max_scenes_per_month": 100,
        "max_storage_gb": 5,
        "max_api_calls_per_day": 1000,
        "features": ["Mock imagery search", "Basic indices", "1 project"],
    },
    "pro": {
        "name": "Pro",
        "price_usd": 49,
        "max_scenes_per_month": 2000,
        "max_storage_gb": 100,
        "max_api_calls_per_day": 20000,
        "features": [
            "CDSE imagery download",
            "ML classification",
            "Change detection",
            "Priority support",
        ],
        "stripe_price_env": "STRIPE_PRICE_PRO",
    },
    "enterprise": {
        "name": "Enterprise",
        "price_usd": 299,
        "max_scenes_per_month": 50000,
        "max_storage_gb": 2000,
        "max_api_calls_per_day": 500000,
        "features": [
            "Unlimited projects",
            "SSO / API keys",
            "Dedicated support",
            "Custom SLA",
        ],
        "stripe_price_env": "STRIPE_PRICE_ENTERPRISE",
    },
}


class CheckoutRequest(BaseModel):
    plan: str = Field(description="pro or enterprise")
    success_url: str = Field(default="http://localhost:5173/billing/success")
    cancel_url: str = Field(default="http://localhost:5173/billing/cancel")


class CheckoutResponse(BaseModel):
    checkout_url: Optional[str] = None
    session_id: Optional[str] = None
    plan: str
    message: str
    plans: Optional[dict] = None


def _apply_plan_limits(sub: Subscription, plan_key: str) -> None:
    plan = PLANS.get(plan_key, PLANS["free"])
    sub.plan = plan_key
    sub.max_scenes_per_month = plan["max_scenes_per_month"]
    sub.max_storage_gb = plan["max_storage_gb"]
    sub.max_api_calls_per_day = plan["max_api_calls_per_day"]


async def _get_or_create_subscription(db: AsyncSession, user_id: int) -> Subscription:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = Subscription(user_id=user_id, plan="free", status="active")
        db.add(sub)
        await db.flush()
    return sub


async def _find_subscription_by_stripe(
    db: AsyncSession,
    *,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Optional[Subscription]:
    if user_id is not None:
        result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        sub = result.scalar_one_or_none()
        if sub:
            return sub
    if subscription_id:
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            return sub
    if customer_id:
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        )
        return result.scalar_one_or_none()
    return None


@router.get("/plans")
async def list_plans(
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    return {"plans": PLANS, "current_user_id": current_user.id if current_user else None}


@router.get("/status")
async def billing_status(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()
    if sub and sub.plan == "professional":
        sub.plan = "pro"
        await db.flush()
    plan_key = sub.plan if sub else "free"
    return {
        "plan": plan_key,
        "status": sub.status if sub else "active",
        "limits": PLANS.get(plan_key, PLANS["free"]),
        "stripe_customer_id": sub.stripe_customer_id if sub else None,
        "stripe_configured": bool(get_settings().stripe_secret_key),
    }


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = get_settings()
    plan_key = request.plan.lower()
    if plan_key not in ("pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Plan must be 'pro' or 'enterprise'")

    plan = PLANS[plan_key]

    if not settings.stripe_secret_key:
        return CheckoutResponse(
            checkout_url=None,
            session_id=None,
            plan=plan_key,
            message="Stripe is not configured. Returning plan information only.",
            plans={plan_key: plan},
        )

    try:
        import os

        import stripe

        stripe.api_key = settings.stripe_secret_key

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == current_user.id)
        )
        sub = result.scalar_one_or_none()

        customer_id = sub.stripe_customer_id if sub else None
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.full_name or current_user.username,
                metadata={"user_id": str(current_user.id)},
            )
            customer_id = customer.id
            if sub:
                sub.stripe_customer_id = customer_id
                await db.flush()

        price_id = os.environ.get(plan.get("stripe_price_env", ""), "")
        line_items: list[dict]
        if price_id:
            line_items = [{"price": price_id, "quantity": 1}]
        else:
            line_items = [
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": f"EarthVision {plan['name']}"},
                        "unit_amount": int(plan["price_usd"] * 100),
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ]

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=line_items,
            success_url=request.success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.cancel_url,
            metadata={"user_id": str(current_user.id), "plan": plan_key},
        )

        return CheckoutResponse(
            checkout_url=session.url,
            session_id=session.id,
            plan=plan_key,
            message="Checkout session created",
        )
    except ImportError:
        return CheckoutResponse(
            checkout_url=None,
            session_id=None,
            plan=plan_key,
            message="stripe package not installed. Returning plan information only.",
            plans={plan_key: plan},
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Stripe checkout failed: {exc}")


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_signature: Annotated[Optional[str], Header(alias="Stripe-Signature")] = None,
):
    """Verify Stripe signature and sync Subscription on checkout / subscription events."""
    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        return {
            "received": False,
            "error": "Stripe is not configured (stripe_secret_key / stripe_webhook_secret)",
        }

    try:
        import stripe
    except ImportError:
        return {"received": False, "error": "stripe package not installed"}

    stripe.api_key = settings.stripe_secret_key
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature or "",
            secret=settings.stripe_webhook_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {exc}")

    event_type = event["type"]
    data_object = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            metadata = data_object.get("metadata") or {}
            user_id_raw = metadata.get("user_id")
            plan_key = (metadata.get("plan") or "pro").lower()
            if plan_key not in PLANS:
                plan_key = "pro"
            if not user_id_raw:
                logger.warning("checkout.session.completed missing user_id metadata")
                return {"received": True, "handled": False}

            sub = await _get_or_create_subscription(db, int(user_id_raw))
            _apply_plan_limits(sub, plan_key)
            sub.status = "active"
            sub.stripe_customer_id = data_object.get("customer") or sub.stripe_customer_id
            sub.stripe_subscription_id = (
                data_object.get("subscription") or sub.stripe_subscription_id
            )
            await db.flush()

        elif event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            customer_id = data_object.get("customer")
            subscription_id = data_object.get("id")
            metadata = data_object.get("metadata") or {}
            user_id = int(metadata["user_id"]) if metadata.get("user_id") else None
            plan_key = (metadata.get("plan") or "").lower()

            sub = await _find_subscription_by_stripe(
                db,
                customer_id=customer_id,
                subscription_id=subscription_id,
                user_id=user_id,
            )
            if sub is None and user_id is not None:
                sub = await _get_or_create_subscription(db, user_id)

            if sub is None:
                logger.warning(f"No subscription row for Stripe event {event_type}")
                return {"received": True, "handled": False}

            stripe_status = data_object.get("status", "active")
            if event_type == "customer.subscription.deleted":
                sub.status = "canceled"
                sub.plan = "free"
                _apply_plan_limits(sub, "free")
            else:
                status_map = {
                    "active": "active",
                    "trialing": "trialing",
                    "past_due": "past_due",
                    "canceled": "canceled",
                    "unpaid": "unpaid",
                    "incomplete": "incomplete",
                    "incomplete_expired": "canceled",
                }
                sub.status = status_map.get(stripe_status, stripe_status)
                if plan_key in PLANS:
                    _apply_plan_limits(sub, plan_key)
                sub.stripe_customer_id = customer_id or sub.stripe_customer_id
                sub.stripe_subscription_id = subscription_id or sub.stripe_subscription_id

            period_start = data_object.get("current_period_start")
            period_end = data_object.get("current_period_end")
            if period_start:
                sub.current_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)
            if period_end:
                sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
            await db.flush()

        else:
            logger.debug(f"Unhandled Stripe event type: {event_type}")
            return {"received": True, "handled": False}

        return {"received": True, "handled": True, "type": event_type}
    except Exception as exc:
        logger.exception(f"Stripe webhook handler error: {exc}")
        raise HTTPException(status_code=500, detail=f"Webhook handler failed: {exc}")
