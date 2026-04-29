import secrets
import hashlib
import uuid

from sqlalchemy import select, update, func
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Response, status
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models.refresh_token import RefreshToken
from models.user import User, UserReferrer
from core.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

COOKIE_SECURE = settings.COOKIE_SECURE
COOKIE_SAMESITE = settings.COOKIE_SAMESITE

ACCESS_TOKEN_COOKIE_NAME = "access_token"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="올바른 access token이 아닙니다.",
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 access token입니다.",
        )


def set_access_token_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_access_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )


def create_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_refresh_token_expiry(expires_delta: Optional[timedelta] = None) -> datetime:
    return datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )


async def issue_tokens_and_save(
    response: Response,
    db: AsyncSession,
    user: User,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> None:
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token()

    refresh_token_row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        family_id=uuid.uuid4(),
        parent_token_id=None,
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=get_refresh_token_expiry(),
        revoked_at=None,
        revoke_reason=None,
        created_at=datetime.now(timezone.utc),
    )

    db.add(refresh_token_row)
    user.last_login_at = datetime.now(timezone.utc)

    await db.commit()

    set_access_token_cookie(response, access_token)
    set_refresh_token_cookie(response, refresh_token)


def revoke_refresh_token(token_row: RefreshToken, reason: str) -> None:
    token_row.revoked_at = datetime.now(timezone.utc)
    token_row.revoke_reason = reason


def set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )


def clear_refresh_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )


async def rotate_refresh_token(
    db: AsyncSession,
    old_token_row: RefreshToken,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> str:
    revoke_refresh_token(old_token_row, "rotated")

    new_refresh_token = create_refresh_token()

    new_token_row = RefreshToken(
        user_id=old_token_row.user_id,
        token_hash=hash_refresh_token(new_refresh_token),
        family_id=old_token_row.family_id,
        parent_token_id=old_token_row.id,
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=get_refresh_token_expiry(),
        revoked_at=None,
        revoke_reason=None,
        created_at=datetime.now(timezone.utc),
    )

    db.add(new_token_row)
    await db.commit()

    return new_refresh_token


async def revoke_token_family(
    db: AsyncSession,
    family_id: uuid.UUID,
    reason: str,
) -> None:
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(
            revoked_at=datetime.now(timezone.utc),
            revoke_reason=reason,
        )
    )
    await db.commit()


async def handle_refresh_token_reuse(
    db: AsyncSession,
    token_row: RefreshToken,
) -> None:
    await revoke_token_family(
        db=db,
        family_id=token_row.family_id,
        reason="token_reuse_detected",
    )


MAX_REFERRERS = 5


async def get_my_referrers_service(
    db: AsyncSession,
    user_id: UUID,
) -> list[User]:
    result = await db.execute(
        select(UserReferrer)
        .options(selectinload(UserReferrer.referrer))
        .where(UserReferrer.user_id == user_id)
        .order_by(UserReferrer.created_at.desc(), UserReferrer.id.desc())
    )

    rows = result.scalars().all()
    return [row.referrer for row in rows if row.referrer]


async def add_user_referrers_service(
    db: AsyncSession,
    *,
    user_id: UUID,
    referrer_nicknames: list[str],
    commit: bool = True,
) -> list[User]:
    cleaned = [item.strip() for item in referrer_nicknames if item and item.strip()]
    cleaned = list(dict.fromkeys(cleaned))

    if not cleaned:
        return await get_my_referrers_service(db=db, user_id=user_id)

    current_rows_result = await db.execute(
        select(UserReferrer)
        .options(selectinload(UserReferrer.referrer))
        .where(UserReferrer.user_id == user_id)
    )
    current_rows = current_rows_result.scalars().all()

    current_referrers = [
        row.referrer
        for row in current_rows
        if row.referrer
    ]

    current_count = len(current_referrers)

    if current_count >= MAX_REFERRERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="추천인은 최대 5명까지 등록할 수 있습니다.",
        )

    current_nicknames = {
        user.nickname
        for user in current_referrers
        if user and user.nickname
    }

    new_nicknames = [
        nickname
        for nickname in cleaned
        if nickname not in current_nicknames
    ]

    if not new_nicknames:
        return await get_my_referrers_service(db=db, user_id=user_id)

    if len(new_nicknames) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="추천인은 한 번에 1명만 추가할 수 있습니다.",
        )

    nickname = new_nicknames[0]

    referrer_result = await db.execute(
        select(User).where(
            User.nickname == nickname,
            User.is_active.is_(True),
        )
    )
    referrer_user = referrer_result.scalar_one_or_none()

    if not referrer_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="존재하지 않는 추천인이거나 탈퇴한 사용자입니다.",
        )

    if referrer_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="자기 자신은 추천인으로 등록할 수 없습니다.",
        )

    existing_result = await db.execute(
        select(UserReferrer).where(
            UserReferrer.user_id == user_id,
            UserReferrer.referrer_id == referrer_user.id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        return await get_my_referrers_service(db=db, user_id=user_id)

    db.add(
        UserReferrer(
            user_id=user_id,
            referrer_id=referrer_user.id,
        )
    )

    new_count = current_count + 1

    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            referrer_count=new_count,
            referrer_id=referrer_user.id,
        )
    )

    if commit:
        await db.commit()

    return await get_my_referrers_service(db=db, user_id=user_id)