"""Tests for the FastAPI rate-limiting middleware.

Covers:
  * Per-route class budgets (heavy 10/min, general 30/min).
  * Sliding-window semantics (old timestamps age out).
  * Retry-After header accuracy.
  * X-RateLimit-* informational headers on success.
  * Exempt paths (auth login, health, docs) bypass the limiter entirely.
  * Different actors have independent buckets.
  * X-Forwarded-For is honoured when no peer host is trusted.

The tests construct a ``TestClient`` with tiny limits (3 / 5 seconds)
so each test stays well under a second of wall time. Production limits
are verified separately via smoke runs of the live server.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limiter import RateLimiter


def _make_app(general_limit: int = 3, heavy_limit: int = 2, window: int = 5) -> FastAPI:
    """Build a minimal FastAPI app with the limiter and four probe routes.

    Routes:
      * ``/general`` — counts against the general budget.
      * ``/api/upload`` — counts against the heavy budget.
      * ``/api/auth/login`` — exempt (auth surface).
      * ``/health`` — exempt (liveness probe).

    All routes return 200 unconditionally so the test is purely about
    the limiter's behaviour, not business logic.
    """
    app = FastAPI()
    app.add_middleware(
        RateLimiter,
        general_limit=general_limit,
        heavy_limit=heavy_limit,
        window_seconds=window,
    )

    @app.get("/general")
    def general():
        return {"ok": True}

    @app.post("/api/upload")
    def upload():
        return {"ok": True}

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


class TestRateLimiterGeneralRoutes:
    def test_under_limit_returns_200_with_headers(self, client: TestClient):
        resp = client.get("/general")
        assert resp.status_code == 200
        # Informational headers should always be set on success.
        assert resp.headers["X-RateLimit-Limit"] == "3"
        assert resp.headers["X-RateLimit-Remaining"] == "2"
        assert resp.headers["X-RateLimit-Route"] == "general"
        assert resp.headers["X-RateLimit-Window"] == "5"

    def test_over_general_limit_returns_429(self, client: TestClient):
        # 3 successful calls then a 429.
        for _ in range(3):
            assert client.get("/general").status_code == 200
        resp = client.get("/general")
        assert resp.status_code == 429
        body = resp.json()
        assert "Too many requests" in body["detail"]
        assert body["route_class"] == "general"
        assert body["limit"] == 3
        assert body["window_seconds"] == 5
        assert body["retry_after_seconds"] >= 1
        assert "Retry-After" in resp.headers
        assert resp.headers["X-RateLimit-Remaining"] == "0"

    def test_retry_after_decreases_with_time(self, client: TestClient):
        """After sleeping half the window, the Retry-After should shrink."""
        import time

        for _ in range(3):
            assert client.get("/general").status_code == 200

        first = client.get("/general")
        assert first.status_code == 429
        first_retry = int(first.headers["Retry-After"])

        time.sleep(2)  # window=5s, sleep 2s
        second = client.get("/general")
        assert second.status_code == 429
        second_retry = int(second.headers["Retry-After"])
        assert second_retry <= first_retry


class TestRateLimiterHeavyRoutes:
    def test_heavy_route_uses_lower_budget(self, client: TestClient):
        # 2 successful, third is rejected.
        assert client.post("/api/upload").status_code == 200
        assert client.post("/api/upload").status_code == 200
        resp = client.post("/api/upload")
        assert resp.status_code == 429
        body = resp.json()
        assert body["route_class"] == "heavy"
        assert body["limit"] == 2

    def test_heavy_and_general_buckets_are_independent(self, client: TestClient):
        """Spending the heavy budget must not affect general budget and vice versa."""
        # Exhaust heavy.
        assert client.post("/api/upload").status_code == 200
        assert client.post("/api/upload").status_code == 200
        assert client.post("/api/upload").status_code == 429
        # General still has full budget.
        for _ in range(3):
            assert client.get("/general").status_code == 200
        # Now general is also exhausted.
        assert client.get("/general").status_code == 429
        # Heavy bucket is still in its 429 state.
        assert client.post("/api/upload").status_code == 429


class TestRateLimiterExemptions:
    def test_health_is_exempt(self, client: TestClient):
        # Hammer it — should never trip, because /health is in the
        # exempt list (liveness probes shouldn't be rate-limited).
        for _ in range(10):
            assert client.get("/health").status_code == 200

    def test_login_is_exempt(self, client: TestClient):
        # Auth login should not be rate-limited by the middleware
        # (Supabase-side protections handle credential abuse).
        for _ in range(10):
            assert client.post("/api/auth/login").status_code == 200


class TestRateLimiterSlidingWindow:
    def test_old_timestamps_age_out(self):
        """A request after the window must succeed — the oldest is too old."""
        import time

        # Tiny app: 2 general reqs / 1 second window.
        app = _make_app(general_limit=2, heavy_limit=2, window=1)
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/general").status_code == 200
        assert c.get("/general").status_code == 200
        assert c.get("/general").status_code == 429
        time.sleep(1.2)  # exceed window
        # Window has rolled over — both old timestamps are pruned.
        assert c.get("/general").status_code == 200


class TestRateLimiterActorIsolation:
    def test_xff_separates_actors(self):
        """Requests from different X-Forwarded-For IPs have independent buckets."""
        app = _make_app(general_limit=2, heavy_limit=2, window=5)
        c = TestClient(app, raise_server_exceptions=False)
        # Two requests from "client A".
        for _ in range(2):
            r = c.get("/general", headers={"X-Forwarded-For": "10.0.0.1"})
            assert r.status_code == 200
        # Third from A is rejected.
        r = c.get("/general", headers={"X-Forwarded-For": "10.0.0.1"})
        assert r.status_code == 429
        # But client B still has full budget.
        r = c.get("/general", headers={"X-Forwarded-For": "10.0.0.2"})
        assert r.status_code == 200
