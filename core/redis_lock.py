import uuid
from contextlib import asynccontextmanager

from core.redis_client import redis_client


@asynccontextmanager
async def redis_lock(
    lock_key: str,
    lock_value: str | None = None,
    expire_seconds: int = 30,
):
    """
    Redis 분산 락 (async)

    - lock_key: 락 키 (예: quick_match_lock:{party_id})
    - lock_value: 락 소유자 식별값 (없으면 자동 생성)
    - expire_seconds: TTL (데드락 방지)
    """

    value = lock_value or str(uuid.uuid4())

    # NX: 이미 있으면 실패
    # EX: TTL 설정
    acquired = await redis_client.set(
        lock_key,
        value,
        nx=True,
        ex=expire_seconds,
    )

    if not acquired:
        raise RuntimeError("LOCK_NOT_ACQUIRED")

    try:
        yield value

    finally:
        # 내가 잡은 락만 해제 (중요!)
        current = await redis_client.get(lock_key)
        if current == value:
            await redis_client.delete(lock_key)