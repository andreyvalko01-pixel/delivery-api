"""Обмеження частоти запитів.

Якщо доступний Redis — лічильник спільний для всіх воркерів API.
Якщо ні (локально, тести) — рахуємо в пам'яті процесу.
"""

import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings

WINDOW = 60  # секунд


class MemoryBackend:
    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def hit(self, key: str) -> int:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > WINDOW:
            q.popleft()
        q.append(now)
        return len(q)


class RedisBackend:
    def __init__(self, url: str):
        import redis

        self.client = redis.Redis.from_url(url, socket_connect_timeout=0.5)
        self.client.ping()

    def hit(self, key: str) -> int:
        bucket = f"rl:{key}:{int(time.time() // WINDOW)}"
        pipe = self.client.pipeline()
        pipe.incr(bucket)
        pipe.expire(bucket, WINDOW * 2)
        return pipe.execute()[0]


def make_backend():
    try:
        return RedisBackend(settings.redis_url)
    except Exception:
        return MemoryBackend()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int | None = None, backend=None):
        super().__init__(app)
        self.limit = limit or settings.rate_limit_per_minute
        self.backend = backend or make_backend()

    async def dispatch(self, request: Request, call_next):
        # документацію і healthcheck не обмежуємо
        if request.url.path.startswith(("/docs", "/openapi", "/health")):
            return await call_next(request)

        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0]
        count = self.backend.hit(ip)
        if count > self.limit:
            return JSONResponse(
                {"detail": "Забагато запитів, спробуйте за хвилину"},
                status_code=429,
                headers={"Retry-After": str(WINDOW)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.limit - count))
        return response
