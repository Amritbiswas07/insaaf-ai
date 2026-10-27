"""Polite async HTTP client: global rate limit, robots.txt, retries with backoff."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from insaaf.logs import log


class RateLimiter:
    """Spaces requests at least `1/rate` seconds apart across all tasks."""

    def __init__(self, rate_per_s: float) -> None:
        self._interval = 1.0 / rate_per_s if rate_per_s > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


class RobotsDisallowed(Exception):
    pass


class RetryableHTTPError(Exception):
    def __init__(self, status: int, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RetryableHTTPError | httpx.TransportError)


class PoliteClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        rate_per_s: float,
        max_retries: int = 4,
        respect_robots: bool = True,
        headers: dict[str, str] | None = None,
        timeout_s: float = 45.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._ua = user_agent
        self._limiter = RateLimiter(rate_per_s)
        self._max_retries = max_retries
        self._respect_robots = respect_robots
        self._robots: RobotFileParser | None = None
        self._robots_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, **(headers or {})},
            timeout=timeout_s,
            follow_redirects=True,
            http2=False,
        )

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _load_robots(self) -> RobotFileParser:
        async with self._robots_lock:
            if self._robots is None:
                rp = RobotFileParser()
                try:
                    resp = await self._client.get(f"{self.base_url}/robots.txt")
                    rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
                except httpx.HTTPError as exc:
                    log.warning("robots.fetch_failed", error=str(exc))
                    rp.parse([])
                self._robots = rp
            return self._robots

    async def allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        rp = await self._load_robots()
        return rp.can_fetch(self._ua, url)

    async def request(self, method: str, path_or_url: str, **kwargs: object) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        if not await self.allowed(url):
            raise RobotsDisallowed(url)

        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential_jitter(initial=2, max=60),
            stop=stop_after_attempt(self._max_retries),
            reraise=True,
        ):
            with attempt:
                await self._limiter.wait()
                resp = await self._client.request(method, url, **kwargs)  # type: ignore[arg-type]
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else None
                    if delay:
                        await asyncio.sleep(min(delay, 120))
                    log.warning("http.retry", url=url, status=resp.status_code)
                    raise RetryableHTTPError(resp.status_code, delay)
                resp.raise_for_status()
                return resp
        raise AssertionError("unreachable")

    async def get_text(self, path_or_url: str, **kwargs: object) -> str:
        return (await self.request("GET", path_or_url, **kwargs)).text
