from typing import AsyncGenerator
import redis.asyncio as aioredis
from app.core.config import get_settings

settings= get_settings()

# ---------------------------------------------------------------------------
# Pool (module-level singleton)
# ---------------------------------------------------------------------------
# We create ONE connection pool for the entire application lifetime.
# Never create a new Redis connection per request — that's a connection
# leak waiting to happen (each connection is a TCP socket to Redis).
#
# decode_responses=True: Redis returns bytes by default. With this flag,
# strings come back as str — saves you .decode("utf-8") everywhere.
#
# max_connections: caps the pool size. Default is unbounded, which means
# a traffic spike can open thousands of connections to Redis and crash it.
# 20 is a safe starting point for a single-instance app.
_redis_pool: aioredis.ConnectionPool | None = None


def get_redis_pool() -> aioredis.ConnectionPool:
    """Return the module-level connection pool, creating it if needed.

    Called once during app lifespan startup. See main.py.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
        )
    return _redis_pool


async def close_redis_pool() -> None:
    """Gracefully drain and close the pool on app shutdown.

    Called in main.py lifespan teardown. Without this, you get
    'Event loop is closed' warnings and potential data loss on
    in-flight pipeline commands.
    """
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


# ---------------------------------------------------------------------------
# Dependency: get_redis
# ---------------------------------------------------------------------------
# Yields a Redis client backed by the shared pool.
# The client is a thin wrapper — it does NOT hold a connection until
# you actually issue a command. 
#
# Usage in a router or service:
#   @router.post("/logout")
#   async def logout(
#       redis: aioredis.Redis = Depends(get_redis),
#       ...
#   ):
#       await redis.setex(f"blacklist:{jti}", ttl, "1")
async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    pool = get_redis_pool()
    client = aioredis.Redis(connection_pool=pool)
    try:
        yield client
    finally:
        # aclose() returns the connection to the pool (doesn't destroy it).
        await client.aclose()


# ---------------------------------------------------------------------------
# Utility helpers (used by services directly, not via Depends)
# ---------------------------------------------------------------------------
# These are thin helpers for the most common auth patterns.
# Services import these rather than duplicating the key-naming logic.

class RedisKeys:
    """Centralised key schema.

    Keeps Redis keyspace documented and typo-free.
    Change a key format here and it changes everywhere.
    """

    @staticmethod
    def blacklist(jti: str) -> str:
        """Blacklisted access token. Value: '1'. TTL = token expiry."""
        return f"blacklist:access:{jti}"

    @staticmethod
    def refresh_token(token_id: str) -> str:
        """Maps refresh token ID → user_id. TTL = refresh expiry."""
        return f"refresh:{token_id}"

    @staticmethod
    def rate_limit(ip: str, window: str) -> str:
        """Request counter for rate limiting. Key: ip + time window."""
        return f"ratelimit:{ip}:{window}"

    @staticmethod
    def user_cache(user_id: str) -> str:
        """Cached serialised user object. TTL = short (60–300 s)."""
        return f"cache:user:{user_id}"