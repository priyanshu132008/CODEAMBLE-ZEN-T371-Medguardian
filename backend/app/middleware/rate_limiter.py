"""In-memory sliding-window rate limiter for MedGuardian.

A pragmatic single-process guard for the live demo. Designed to run as
ASGI middleware so every request (auth, /api/upload, /api/claim/*,
calendar, etc.) is counted in one place.

Design choices, and why:

* Sliding window (log-based) over fixed window
    A fixed 60-second window allows a malicious or buggy client to send
    2N requests in a 1-second burst (N at second 59, N at second 60).
    The log keeps per-request timestamps and prunes anything older than
    the window, so the count is genuinely "in the last 60 seconds."

* Key on (actor, route_class), not just IP
    Many endpoints sit behind Supabase Auth. Once we know the user id /
    email, it is a far more stable key than an IP that may be shared by
    hundreds of users on a mobile carrier CGNAT. The middleware prefers
    the authenticated principal when available and falls back to the
    peer IP otherwise.

* Trust X-Forwarded-For when present
    MedGuardian is typically deployed behind Railway/Render/Vercel. The
    peer address is the load balancer's, so without honouring the
    forwarded header every request looks like it came from one IP and
    the limiter trips immediately. We take the *first* entry in the
    comma-separated list (the original client per RFC 7239), falling
    back to the peer if the header is missing or empty.

* Process-local state
    Single-worker uvicorn keeps the dict consistent. With N workers the
    effective limit becomes ``limit * N``, which is acceptable for the
    demo but a future multi-worker setup should swap this for Redis or a
    shared KV. The ``RateLimiter`` class is the seam: replace the
    storage backend without touching call sites.

* Per-route limits
    ``/api/upload``, ``/api/claim/generate``, ``/api/claim/pdf`` and
    other LLM-bound endpoints get a tighter quota (10/min) than general
    reads (30/min). The mapping is in ``_HEAVY_ROUTE_PREFIXES`` below
    and matched against the URL path prefix.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


_LOG = logging.getLogger("medguardian.rate_limit")

# Quotas, in requests per window. The window itself is 60 seconds and is
# shared between buckets so the rules read naturally.
_GENERAL_LIMIT = int(os.getenv("MEDGUARDIAN_RATE_LIMIT_GENERAL", "30"))
_HEAVY_LIMIT = int(os.getenv("MEDGUARDIAN_RATE_LIMIT_HEAVY", "10"))
_WINDOW_SECONDS = int(os.getenv("MEDGUARDIAN_RATE_LIMIT_WINDOW", "60"))

# Path prefixes that count as "heavy" — they hit upstream LLMs / OCR /
# PDF rendering and are the abuse surface during a live demo.
# Kept conservative on purpose; the routes not listed here get the
# general quota.
_HEAVY_ROUTE_PREFIXES: Tuple[str, ...] = (
    "/api/upload",  # Agent 1 + Agent 2 (OCR + safety LLM)
    "/api/claim/generate",  # Agent 5 (LLM dossier)
    "/api/claim/pdf",  # PDF rendering
    "/api/teach-back",  # Agent 3 teach-back LLM
    "/api/voice/",  # STT / TTS
    "/api/coordinate",  # Agent 4 dispatch (LLM)
)

# Endpoints that should NEVER be limited — health probes, CORS preflights,
# and auth/login (locking the login endpoint invites credential-stuffing
# abuse of a different shape, which we want to handle separately).
_EXEMPT_PREFIXES: Tuple[str, ...] = (
    "/health",
    "/healthz",
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/auth/login",
    "/api/auth/signup",
    "/api/auth/google",
)


def _is_exempt(path: str) -> bool:
    """Return True when ``path`` is on the never-limit allow-list.

    The root path ``/`` is matched only as an exact equality, not as a
    prefix — otherwise ``startswith("/")`` would exempt every request.
    """
    for prefix in _EXEMPT_PREFIXES:
        if prefix == "/":
            # Exact match only — the bare root is the OpenAPI/landing
            # page; we don't want to exempt everything.
            if path == "/":
                return True
            continue
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _is_heavy(path: str) -> bool:
    return any(path.startswith(p) for p in _HEAVY_ROUTE_PREFIXES)


def _client_key(request: Request) -> str:
    """Return the rate-limit bucket key for this request.

    Preference order:
      1. ``request.state.user_id`` if an auth dependency set it.
      2. ``X-Forwarded-For`` first hop (typical reverse-proxy header).
      3. ``request.client.host`` (peer address).

    Prefixing with ``u:`` / ``ip:`` keeps the buckets disjoint if a user
    id happens to collide with an IP literal (e.g. "127.0.0.1").
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"u:{user_id}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return f"ip:{first}"

    client = request.client
    if client and client.host:
        return f"ip:{client.host}"

    # Anonymous and unattributable — bucket them together so they cannot
    # bypass limits by stripping headers. The bucket name documents the
    # fallback so log analysis stays readable.
    return "ip:unknown"


class RateLimiter(BaseHTTPMiddleware):
    """Sliding-window rate limiter middleware.

    Storage is a dict ``{(actor, route_class): deque[float]}``. Each
    deque holds monotonic timestamps of recent requests in the current
    window. On every call we:

      1. Prune timestamps older than ``_WINDOW_SECONDS``.
      2. If the remaining count is at-or-over the limit, reject with 429.
      3. Otherwise append ``time.monotonic()`` and continue.

    A periodic janitor (``gc``) drops empty deques so the dict doesn't
    grow unboundedly under heavy rotation of distinct actors (e.g.
    spoofed IPs). It's cheap enough to run on every call.
    """

    def __init__(
        self,
        app,
        *,
        general_limit: int = _GENERAL_LIMIT,
        heavy_limit: int = _HEAVY_LIMIT,
        window_seconds: int = _WINDOW_SECONDS,
    ) -> None:
        super().__init__(app)
        self._general_limit = general_limit
        self._heavy_limit = heavy_limit
        self._window = window_seconds
        # type: Dict[Tuple[str, str], Deque[float]]
        self._buckets: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    # -- internals -----------------------------------------------------

    def _limit_for(self, route_class: str) -> int:
        return self._heavy_limit if route_class == "heavy" else self._general_limit

    def _prune(self, bucket: Deque[float], now: float) -> None:
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def _gc(self) -> None:
        """Drop empty buckets so the dict size is bounded by active actors.

        Called from inside ``dispatch`` so we don't need a background
        timer; the cost is O(active buckets) on every request, which is
        fine for the demo's traffic profile.
        """
        dead = [k for k, b in self._buckets.items() if not b]
        for k in dead:
            del self._buckets[k]

    def _reset(self) -> None:
        """Clear all buckets. Used by tests; never call from app code."""
        self._buckets.clear()

    # -- middleware entry point ---------------------------------------

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if _is_exempt(path):
            return await call_next(request)

        route_class = "heavy" if _is_heavy(path) else "general"
        limit = self._limit_for(route_class)

        now = time.monotonic()
        actor = _client_key(request)
        key = (actor, route_class)
        bucket = self._buckets[key]

        self._prune(bucket, now)

        if len(bucket) >= limit:
            # Compute Retry-After: seconds until the oldest timestamp
            # ages out of the window. Cap at the window length so a
            # caller that ignores the hint and keeps spamming doesn't
            # poison subsequent windows with phantom re-uses.
            oldest = bucket[0]
            retry_after = max(1, int(self._window - (now - oldest)) + 1)
            retry_after = min(retry_after, self._window)

            _LOG.warning(
                "rate_limit_exceeded actor=%s route_class=%s path=%s "
                "limit=%d window=%ds retry_after=%ds",
                actor,
                route_class,
                path,
                limit,
                self._window,
                retry_after,
            )

            # Best-effort: also stamp the actor onto request.state so
            # downstream handlers / structured logs can attribute the
            # 429 to the same actor without re-deriving it.
            request.state.rate_limited = True
            request.state.rate_limit_retry_after = retry_after

            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Too many requests. Heavy endpoints allow "
                        f"{self._heavy_limit}/{self._window}s; general "
                        f"endpoints allow {self._general_limit}/{self._window}s. "
                        f"Retry after {retry_after}s."
                    ),
                    "route_class": route_class,
                    "limit": limit,
                    "window_seconds": self._window,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    # RFC 6585 semantics — let caches know this is a
                    # transient, throttle-specific response.
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + retry_after)),
                },
            )

        bucket.append(now)
        # Surface the budget on the response so well-behaved clients can
        # back off proactively instead of waiting for a 429.
        response = await call_next(request)
        remaining = max(0, limit - len(bucket))
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(self._window)
        response.headers["X-RateLimit-Route"] = route_class

        # Opportunistic GC — keeps the dict bounded without a timer.
        if len(self._buckets) > 1024:
            self._gc()

        return response


__all__ = ["RateLimiter"]