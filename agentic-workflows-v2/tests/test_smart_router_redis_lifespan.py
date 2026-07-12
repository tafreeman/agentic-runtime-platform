"""Tests for wiring the Redis-backed SmartModelRouter into the app lifespan.

FIX #4 — the Redis circuit-breaker CAS persistence (``redis_state.py`` +
``SmartModelRouter.create_with_redis``) was unit-tested but never instantiated
on a real app path, and the lifespan shutdown never drained the router's
background CAS save tasks. These tests prove the wiring end-to-end:

(a) With ``REDIS_URL`` configured, ``_install_smart_router`` builds a
    Redis-backed router and installs it as the process-wide singleton that
    ``get_smart_router()`` returns (so consumers use the Redis store).
(b) The FastAPI lifespan shutdown calls ``aclose()`` on the installed router,
    draining outstanding fire-and-forget Redis CAS save tasks.
(c) When Redis is unavailable (unset URL, connection failure, or a store that
    cannot connect), startup falls back to the in-process router and never
    raises (graceful degradation).

All Redis interactions use fakeredis — no live Redis server is required.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_v2.models.redis_state import RedisCircuitBreakerStore
from agentic_v2.models.smart_router import (
    SmartModelRouter,
    get_smart_router,
)

try:
    import fakeredis

    _FAKEREDIS_AVAILABLE = True
except ImportError:
    _FAKEREDIS_AVAILABLE = False
    fakeredis = None  # type: ignore[assignment]

skip_no_fakeredis = pytest.mark.skipif(
    not _FAKEREDIS_AVAILABLE,
    reason="fakeredis not installed",
)


async def _make_fake_store(
    prefix: str = "test:lifespan:",
    ttl_seconds: int = 3600,
    *,
    connected: bool = True,
) -> RedisCircuitBreakerStore:
    """Create a RedisCircuitBreakerStore backed by fakeredis.

    When ``connected`` is False the store is returned in a disconnected state
    (``is_connected`` is False, no client), simulating a failed connection.
    """
    store = RedisCircuitBreakerStore(
        redis_url="redis://fake",
        prefix=prefix,
        ttl_seconds=ttl_seconds,
    )
    if not connected:
        store._connected = False
        store._client = None
        return store

    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    store._client = fake_client
    store._connected = True
    from agentic_v2.models.redis_state import _CAS_LUA_SCRIPT

    store._cas_sha = await fake_client.script_load(_CAS_LUA_SCRIPT)
    return store


def _make_settings(redis_url: str | None):
    """Build a Settings object with a specific redis_url (other fields default)."""
    from agentic_v2.settings import Settings

    return Settings(redis_url=redis_url)


# ---------------------------------------------------------------------------
# (a) REDIS_URL configured → router uses the Redis store and is installed
# ---------------------------------------------------------------------------


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_install_router_uses_redis_store_when_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_install_smart_router builds a Redis-backed router when REDIS_URL is set."""
    from agentic_v2.server import lifespan as lifespan_mod

    fake_store = await _make_fake_store()

    captured: dict[str, object] = {}

    async def fake_create_with_redis(
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = 3600,
        **kwargs: object,
    ) -> SmartModelRouter:
        captured["redis_url"] = redis_url
        captured["prefix"] = prefix
        captured["ttl_seconds"] = ttl_seconds
        return SmartModelRouter(_redis_store=fake_store, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        SmartModelRouter, "create_with_redis", staticmethod(fake_create_with_redis)
    )

    settings = _make_settings("redis://localhost:6379/0")
    router = await lifespan_mod._install_smart_router(settings)

    # The returned router is Redis-backed and connected.
    assert router._redis_store is fake_store
    assert router._redis_store.is_connected is True
    # create_with_redis received the settings' URL/prefix/ttl.
    assert captured["redis_url"] == "redis://localhost:6379/0"
    assert captured["prefix"] == settings.redis_circuit_breaker_prefix
    assert captured["ttl_seconds"] == settings.redis_circuit_breaker_ttl

    # It was installed as the process-wide singleton, so every consumer that
    # resolves via get_smart_router() now uses the Redis-backed router.
    assert get_smart_router() is router

    await router.aclose()


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_installed_redis_router_persists_via_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The installed Redis router actually persists circuit-breaker state via CAS.

    Proves the redis_state.py CAS path is no longer dead code: recording
    a success on the installed router queues a background save that
    writes the model's stats into the (fake) Redis store.
    """
    from agentic_v2.server import lifespan as lifespan_mod

    fake_store = await _make_fake_store(prefix="test:cas:")

    async def fake_create_with_redis(
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = 3600,
        **kwargs: object,
    ) -> SmartModelRouter:
        return SmartModelRouter(_redis_store=fake_store, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        SmartModelRouter, "create_with_redis", staticmethod(fake_create_with_redis)
    )

    settings = _make_settings("redis://localhost:6379/0")
    router = await lifespan_mod._install_smart_router(settings)
    router._available_models.add("ollama:phi4")

    # Record a success → fire-and-forget CAS save task is scheduled.
    router.record_success("ollama:phi4", latency_ms=42.0)
    await router.aclose()  # drain the background save

    # The stats are now in the (fake) Redis store under the model key.
    stored = await fake_store.get("ollama:phi4")
    assert stored is not None, "circuit-breaker stats must be persisted to Redis"
    assert stored.get("success_count", 0) >= 1


# ---------------------------------------------------------------------------
# (b) shutdown calls aclose() / drains background tasks
# ---------------------------------------------------------------------------


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_lifespan_shutdown_drains_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The FastAPI lifespan shutdown awaits the installed router's aclose().

    Drives the real ``lifespan(app)`` context manager with a sentinel router
    whose aclose() is observable, and asserts it is called on shutdown.
    """
    from agentic_v2.server import app as app_mod
    from agentic_v2.server import lifespan as lifespan_mod

    aclose_calls: list[str] = []

    class _SentinelRouter(SmartModelRouter):
        async def aclose(self) -> None:
            aclose_calls.append("closed")
            await super().aclose()

    sentinel = _SentinelRouter()

    # Replace router installation with our sentinel; stub the other startup
    # side-effects so the lifespan body runs without external dependencies.
    async def fake_install(settings: object) -> SmartModelRouter:
        return sentinel

    monkeypatch.setattr(lifespan_mod, "_install_smart_router", fake_install)
    monkeypatch.setattr(lifespan_mod, "_validate_selected_adapter", lambda: None)
    monkeypatch.setattr(lifespan_mod, "_probe_llm_providers", lambda: None)
    monkeypatch.setattr(
        lifespan_mod, "_initialize_sanitization_state", lambda app: None
    )

    async def _noop_init_store() -> None:
        return None

    monkeypatch.setattr(app_mod.websocket.manager, "initialize_store", _noop_init_store)

    # build_audit_logger is awaited in the lifespan; make it cheap/safe.
    async def _fake_build_audit_logger(_settings: object):
        from agentic_v2.server.audit_log import AuditLogger, NullAuditStore

        return AuditLogger(NullAuditStore(), enabled=False)

    monkeypatch.setattr(lifespan_mod, "build_audit_logger", _fake_build_audit_logger)

    app = app_mod.create_app()

    async with app_mod.lifespan(app):
        # Startup completed: the sentinel router is installed on app.state.
        assert app.state.smart_router is sentinel
        assert aclose_calls == [], "aclose must not be called during startup"

    # Exiting the context manager runs the shutdown block.
    assert aclose_calls == ["closed"], "shutdown must call router.aclose()"


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_aclose_drains_pending_redis_save_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aclose() on the installed Redis router empties _background_tasks.

    Mirrors the shutdown drain contract: an in-flight CAS save task is queued,
    then aclose() (called by the lifespan) awaits it to completion.
    """
    from agentic_v2.server import lifespan as lifespan_mod

    fake_store = await _make_fake_store(prefix="test:drain:")

    # Gate the save so the background task is provably in-flight before drain.
    save_started = asyncio.Event()
    drain_allowed = asyncio.Event()
    original_save = fake_store.save_stats_cas

    async def gated_save(*args: object, **kwargs: object) -> object:
        save_started.set()
        await drain_allowed.wait()
        return await original_save(*args, **kwargs)

    fake_store.save_stats_cas = gated_save  # type: ignore[method-assign]

    async def fake_create_with_redis(
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = 3600,
        **kwargs: object,
    ) -> SmartModelRouter:
        return SmartModelRouter(_redis_store=fake_store, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        SmartModelRouter, "create_with_redis", staticmethod(fake_create_with_redis)
    )

    settings = _make_settings("redis://localhost:6379/0")
    router = await lifespan_mod._install_smart_router(settings)
    router._available_models.add("ollama:phi4")

    router.record_success("ollama:phi4", latency_ms=10.0)

    await save_started.wait()
    assert len(router._background_tasks) > 0, "a CAS save task must be in-flight"

    drain_allowed.set()
    await router.aclose()

    assert len(router._background_tasks) == 0, "aclose must drain background tasks"


# ---------------------------------------------------------------------------
# (c) Redis unavailable → fall back to in-process without raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unset_redis_url_uses_in_process_router() -> None:
    """No REDIS_URL → the in-process router is returned, never Redis-backed."""
    from agentic_v2.server import lifespan as lifespan_mod

    settings = _make_settings(None)
    router = await lifespan_mod._install_smart_router(settings)

    assert router is get_smart_router()
    assert router._redis_store is None


@pytest.mark.asyncio
async def test_redis_connect_failure_falls_back_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_with_redis raising must not crash startup — fall back in-process."""
    from agentic_v2.server import lifespan as lifespan_mod

    async def boom_create_with_redis(
        *args: object, **kwargs: object
    ) -> SmartModelRouter:
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(
        SmartModelRouter, "create_with_redis", staticmethod(boom_create_with_redis)
    )

    settings = _make_settings("redis://localhost:6379/0")

    # Must not raise.
    router = await lifespan_mod._install_smart_router(settings)

    # Fell back to the in-process router (no Redis store).
    assert router is get_smart_router()
    assert router._redis_store is None


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_redis_store_not_connected_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A router whose store could not connect falls back to the in-process one.

    ``create_with_redis`` degrades internally rather than raising when the
    connection fails, returning a router with a disconnected store. The wiring
    must detect ``is_connected is False`` and keep the in-process router.
    """
    from agentic_v2.server import lifespan as lifespan_mod

    disconnected_store = await _make_fake_store(connected=False)

    async def fake_create_with_redis(
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = 3600,
        **kwargs: object,
    ) -> SmartModelRouter:
        return SmartModelRouter(_redis_store=disconnected_store, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        SmartModelRouter, "create_with_redis", staticmethod(fake_create_with_redis)
    )

    settings = _make_settings("redis://localhost:6379/0")
    router = await lifespan_mod._install_smart_router(settings)

    # The installed router is the in-process one, NOT the disconnected-store one.
    assert router is get_smart_router()
    assert router._redis_store is None


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_settings_redis_url_from_env_drives_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REDIS_URL read from the environment via get_settings() drives the wiring.

    Confirms the optional REDIS_URL setting (pydantic-settings, default
    None) is the real switch — setting the env var routes through the
    Redis path.
    """
    from agentic_v2.server import lifespan as lifespan_mod
    from agentic_v2.settings import get_settings

    fake_store = await _make_fake_store(prefix="test:env:")

    async def fake_create_with_redis(
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = 3600,
        **kwargs: object,
    ) -> SmartModelRouter:
        return SmartModelRouter(_redis_store=fake_store, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        SmartModelRouter, "create_with_redis", staticmethod(fake_create_with_redis)
    )

    # Default (no env): redis_url is None → in-process.
    assert get_settings().redis_url is None

    # Set the env var; the autouse settings-cache reset fixture cleared the
    # lru_cache, but it was just repopulated above — clear it again so the new
    # value is read.
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/2")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.redis_url == "redis://localhost:6379/2"

    router = await lifespan_mod._install_smart_router(settings)
    assert router._redis_store is fake_store
    assert get_smart_router() is router

    await router.aclose()
