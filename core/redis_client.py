import redis.asyncio as aioredis
from core.config import settings

# ✅ Fix: 동기 redis → 비동기 redis.asyncio로 교체
# FastAPI async 환경에서 동기 redis는 event loop를 블로킹함
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
