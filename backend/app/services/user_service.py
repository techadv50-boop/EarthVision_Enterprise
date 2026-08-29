"""User domain service."""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from app.core.security import hash_password, verify_password
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus
from app.models.user import AccountStatus, User, UserRole
from app.schemas.user import AccountDecisionRequest, UserCreate, UserUpdate


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
        if user.role != UserRole.ADMIN:
            status = user.status
            if status == AccountStatus.PENDING:
                raise UnauthorizedError(
                    "Account is pending admin approval. You will be able to sign in after an "
                    "administrator approves your account."
                )
            if status == AccountStatus.DECLINED:
                raise UnauthorizedError(
                    "Account access was declined by an administrator. Contact support if you "
                    "believe this is a mistake."
                )
            if not user.is_active:
                raise UnauthorizedError("Account is deactivated")
            if status not in {AccountStatus.APPROVED, AccountStatus.RESTRICTED}:
                raise UnauthorizedError("Account is not permitted to sign in")
        elif not user.is_active:
            raise UnauthorizedError("Account is deactivated")
        return user

    async def create(
        self, data: UserCreate, *, public_registration: bool = False
    ) -> User:
        existing = await self.get_by_email(data.email)
        if existing is not None:
            raise ConflictError("Email already registered")

        if public_registration:
            # Self-serve sign-up waits for admin approval / service assignment.
            role = UserRole.VIEWER
            status = AccountStatus.PENDING
            is_active = False
            is_verified = False
            allowed_tools: list[str] | None = []
            allowed_satellites: list[str] | None = []
        else:
            role = data.role
            status = data.account_status or AccountStatus.APPROVED
            is_active = bool(data.is_active)
            is_verified = status in {AccountStatus.APPROVED, AccountStatus.RESTRICTED}
            allowed_tools = data.allowed_tools
            allowed_satellites = data.allowed_satellites
            if status == AccountStatus.PENDING:
                is_active = False
            elif status == AccountStatus.DECLINED:
                is_active = False
            elif status in {AccountStatus.APPROVED, AccountStatus.RESTRICTED}:
                is_active = True

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=role,
            organization=data.organization,
            allowed_tools=allowed_tools,
            allowed_satellites=allowed_satellites,
            account_status=status.value if isinstance(status, AccountStatus) else str(status),
            is_active=is_active,
            is_verified=is_verified,
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
        if "account_status" in updates and updates["account_status"] is not None:
            status = updates["account_status"]
            if isinstance(status, AccountStatus):
                updates["account_status"] = status.value
                status_enum = status
            else:
                status_enum = AccountStatus(str(status))
                updates["account_status"] = status_enum.value
            if status_enum == AccountStatus.APPROVED:
                updates.setdefault("is_active", True)
                updates.setdefault("is_verified", True)
            elif status_enum == AccountStatus.RESTRICTED:
                updates.setdefault("is_active", True)
                updates.setdefault("is_verified", True)
            elif status_enum in {AccountStatus.PENDING, AccountStatus.DECLINED}:
                updates.setdefault("is_active", False)
                if status_enum == AccountStatus.DECLINED:
                    updates.setdefault("is_verified", False)
        for key, value in updates.items():
            # Never null out required columns via partial updates
            if key == "role" and value is None:
                continue
            setattr(user, key, value)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def decide(self, user_id: str, data: AccountDecisionRequest) -> User:
        """Approve, decline, or restrict a client account with optional service grants."""
        if data.status not in {
            AccountStatus.APPROVED,
            AccountStatus.DECLINED,
            AccountStatus.RESTRICTED,
        }:
            raise ValidationError("Decision must be approved, declined, or restricted")

        user = await self.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role == UserRole.ADMIN:
            raise ValidationError("Cannot change approval status for an administrator")

        provided = data.model_dump(exclude_unset=True)
        if data.status == AccountStatus.APPROVED:
            tools = provided.get("allowed_tools", None)
            sats = provided.get("allowed_satellites", None)
        elif data.status == AccountStatus.DECLINED:
            tools = []
            sats = []
        else:  # restricted
            tools = provided.get(
                "allowed_tools",
                user.allowed_tools if user.allowed_tools is not None else [],
            )
            sats = provided.get(
                "allowed_satellites",
                user.allowed_satellites if user.allowed_satellites is not None else [],
            )

        payload_data: dict = {
            "account_status": data.status,
            "allowed_tools": tools,
            "allowed_satellites": sats,
        }
        if data.role is not None:
            payload_data["role"] = data.role
        return await self.update(user_id, UserUpdate(**payload_data))

    async def list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        role: UserRole | None = None,
        status: AccountStatus | None = None,
    ) -> tuple[list[User], int]:
        query = select(User)
        count_query = select(func.count()).select_from(User)
        if role is not None:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)
        if status is not None:
            status_value = status.value if isinstance(status, AccountStatus) else str(status)
            query = query.where(User.account_status == status_value)
            count_query = count_query.where(User.account_status == status_value)
        total = (await self.session.execute(count_query)).scalar_one()
        # Pending first, then restricted, then approved, then declined
        status_order = case(
            (User.account_status == AccountStatus.PENDING.value, 0),
            (User.account_status == AccountStatus.RESTRICTED.value, 1),
            (User.account_status == AccountStatus.APPROVED.value, 2),
            (User.account_status == AccountStatus.DECLINED.value, 3),
            else_=4,
        )
        result = await self.session.execute(
            query.order_by(status_order, User.created_at.desc())
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
