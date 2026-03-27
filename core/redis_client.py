import redis
from core.config import settings

# ✅ Fix: 개별 os.getenv 대신 config.py의 REDIS_URL로 통일
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
