"""SSRF hardening tests — P1 #13.

Coverage:
  a. Default is ON (fresh Settings with env unset).
  b. Flag respected: explicit false disables private-IP blocking but metadata
     hosts are STILL blocked.
  c. IP literals: private, loopback, link-local, metadata, IPv6 loopback,
     IPv4-mapped IPv6 all blocked; public IP allowed.
  d. DNS resolution: hostname resolving to 127.0.0.1 is blocked (monkeypatched
     socket.getaddrinfo — no real DNS).  ``localhost`` blocked.
  e. DNS failure → blocked (fail-closed).
  f. Redirect re-validation (aiohttp): public URL 302→private IP → blocked.
     (httpx / langchain path): public URL 302→private IP → blocked.
  g. Redirect loop bound: > 5 redirects → failure, no infinite loop.
  h. Relative-Location redirect resolves against current URL and is re-validated.

All tests are offline — no real network calls.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    """Run a coroutine in a fresh event loop (avoids nest-asyncio dependency)."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _force_block_private_ips_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Pin the SSRF private-IP guard ON for this module, independent of ambient env.

    The runtime default (``settings.agentic_block_private_ips``) is ON, but a
    developer ``.env`` — loaded into the test session at import time via
    ``load_dotenv`` — may set ``AGENTIC_BLOCK_PRIVATE_IPS=0`` so local dev can
    reach localhost LLM endpoints. These tests assert the guard's *behaviour* and
    must not silently pass or fail on that ambient value, so we force the flag to
    ``"1"`` (an ``os.environ`` write, which outranks the ``.env`` file in
    pydantic-settings) and reset the cached ``Settings`` around every test.

    Tests that deliberately exercise the flag-off path either pass
    ``block_private=False`` directly to the guard (no settings read) or set the
    env var themselves inside the test body, which — running after this fixture —
    takes precedence.
    """
    import agentic_v2.settings as settings_mod

    monkeypatch.setenv("AGENTIC_BLOCK_PRIVATE_IPS", "1")
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# a. Default is ON
# ---------------------------------------------------------------------------


def test_block_private_ips_default_is_true(monkeypatch):
    """agentic_block_private_ips defaults to True when env var is absent."""
    monkeypatch.delenv("AGENTIC_BLOCK_PRIVATE_IPS", raising=False)

    import agentic_v2.settings as settings_mod

    settings_mod.get_settings.cache_clear()
    try:
        s = settings_mod.Settings()
        assert s.agentic_block_private_ips is True
    finally:
        settings_mod.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# b. Flag respected
# ---------------------------------------------------------------------------


class TestFlagRespected:
    """When blocking is disabled, private IPs are allowed but metadata stays blocked."""

    def test_private_ip_allowed_when_flag_off(self):
        from agentic_v2.security.url_guard import validate_url

        # With blocking disabled, RFC-1918 addresses pass
        result = validate_url("http://10.0.0.1/path", block_private=False)
        assert result is None

    def test_loopback_allowed_when_flag_off(self):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url("http://127.0.0.1/", block_private=False)
        assert result is None

    def test_metadata_still_blocked_when_flag_off(self):
        from agentic_v2.security.url_guard import validate_url

        # metadata hosts are ALWAYS blocked regardless of the flag
        result = validate_url("http://169.254.169.254/latest/meta-data/", block_private=False)
        assert result is not None
        assert "metadata" in result.lower() or "blocked" in result.lower()

    def test_metadata_google_blocked_when_flag_off(self):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url("http://metadata.google.internal/computeMetadata/v1/", block_private=False)
        assert result is not None

    def test_fd00_ec2_metadata_blocked_when_flag_off(self):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url("http://[fd00:ec2::254]/latest/meta-data/", block_private=False)
        assert result is not None

    def test_alibaba_metadata_blocked_when_flag_off(self):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url("http://100.100.100.200/latest/meta-data/", block_private=False)
        assert result is not None

    def test_dns_name_resolving_to_metadata_blocked_when_flag_off(self, monkeypatch):
        """A DNS name pointing at a metadata IP is blocked even with the flag off.

        Without resolving, ``http://evil.example/`` -> 169.254.169.254 would
        bypass the always-on metadata block on paths that do not pin at
        connect time (the httpx/langchain path).
        """
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                (socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("169.254.169.254", 0))
            ]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://innocent-looking.example/", block_private=False)
        assert result is not None
        assert "metadata" in result.lower()

    def test_dns_failure_allowed_when_flag_off(self, monkeypatch):
        """With the flag off, the metadata resolution screen is best-effort.

        Resolution failure must NOT block (the operator explicitly disabled
        the guard; an unresolvable host fails at request time anyway).
        """
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise socket_mod.gaierror("name resolution failed")

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://unresolvable.example/", block_private=False)
        assert result is None

    def test_public_dns_name_allowed_when_flag_off(self, monkeypatch):
        """A DNS name resolving to a public address passes with the flag off."""
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                (socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))
            ]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://public.example/", block_private=False)
        assert result is None


# ---------------------------------------------------------------------------
# c. IP literals
# ---------------------------------------------------------------------------


class TestIpLiterals:
    """IP literal addresses are evaluated without DNS."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/",
            "http://172.16.0.1/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
        ],
    )
    def test_blocked_ip_literals(self, url: str):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url(url, block_private=True)
        assert result is not None, f"Expected {url} to be blocked but it was allowed"

    def test_public_ip_allowed(self):
        """93.184.216.34 is example.com's IP — must not be blocked."""
        from agentic_v2.security.url_guard import validate_url

        # With blocking on, a public IP literal must pass
        result = validate_url("http://93.184.216.34/", block_private=True)
        assert result is None

    def test_ftp_scheme_blocked_regardless(self):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url("ftp://example.com/file", block_private=False)
        assert result is not None
        assert "scheme" in result.lower()


# ---------------------------------------------------------------------------
# d. DNS resolution
# ---------------------------------------------------------------------------


class TestDnsResolution:
    """DNS names that resolve to private addresses must be blocked."""

    def test_hostname_resolving_to_loopback_blocked(self, monkeypatch):
        """A hostname that resolves to 127.0.0.1 is blocked."""
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://internal.corp/", block_private=True)
        assert result is not None
        assert "blocked" in result.lower()

    def test_localhost_blocked(self, monkeypatch):
        """'localhost' as a hostname is blocked when flag is on."""
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://localhost/", block_private=True)
        assert result is not None

    def test_hostname_resolving_to_private_rfc1918_blocked(self, monkeypatch):
        """A hostname that resolves to 10.0.0.1 is blocked."""
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://evil.example.com/", block_private=True)
        assert result is not None

    def test_public_hostname_allowed(self, monkeypatch):
        """A hostname resolving to a public IP passes."""
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            # 93.184.216.34 = example.com
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = validate_url("http://example.com/", block_private=True)
        assert result is None


# ---------------------------------------------------------------------------
# e. DNS failure → fail-closed
# ---------------------------------------------------------------------------


class TestDnsFailure:
    """Unresolvable hosts are blocked (fail-closed)."""

    def test_dns_failure_blocked(self, monkeypatch):
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def raise_gaierror(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise socket_mod.gaierror("Name or service not known")

        monkeypatch.setattr(socket_mod, "getaddrinfo", raise_gaierror)

        result = validate_url("http://unresolvable.invalid/", block_private=True)
        assert result is not None
        assert "blocked" in result.lower() or "fail" in result.lower() or "resolve" in result.lower()

    def test_dns_failure_not_blocked_when_flag_off(self, monkeypatch):
        """When blocking is disabled, DNS resolution is skipped entirely."""
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def raise_gaierror(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise socket_mod.gaierror("Name or service not known")

        monkeypatch.setattr(socket_mod, "getaddrinfo", raise_gaierror)

        # With flag off, DNS is never called → allowed
        result = validate_url("http://unresolvable.invalid/", block_private=False)
        assert result is None


# ---------------------------------------------------------------------------
# f. Redirect re-validation — aiohttp (HttpTool)
# ---------------------------------------------------------------------------


class TestRedirectRevalidationAiohttp:
    """HttpTool must re-validate each redirect hop."""

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_blocked(self, monkeypatch):
        """Public URL that 302s to 127.0.0.1 is rejected."""
        import socket as socket_mod

        import aiohttp

        from agentic_v2.tools.builtin.http_ops import HttpTool

        # DNS for the initial public host resolves to a public IP
        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            if host == "public.example.com":
                return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
            raise socket_mod.gaierror(f"unexpected host: {host}")

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        # Patch aiohttp.ClientSession.request to return a 302 on the first call
        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "http://127.0.0.1/secret"}

        redirect_response.release = MagicMock()  # release() is sync in aiohttp 3.x

        async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            return redirect_response

        monkeypatch.setattr(aiohttp.ClientSession, "request", fake_request)

        tool = HttpTool()
        result = await tool.execute(url="http://public.example.com/page")
        assert not result.success
        assert result.error is not None
        assert "blocked" in result.error.lower() or "private" in result.error.lower() or "loopback" in result.error.lower()

    @pytest.mark.asyncio
    async def test_redirect_to_metadata_ip_blocked(self, monkeypatch):
        """Redirect to cloud metadata IP is blocked even with flag off."""
        import socket as socket_mod

        import aiohttp

        from agentic_v2.tools.builtin.http_ops import HttpTool

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)
        # Turn off the blocking flag — metadata should STILL be blocked
        monkeypatch.setenv("AGENTIC_BLOCK_PRIVATE_IPS", "0")
        import agentic_v2.settings as settings_mod
        settings_mod.get_settings.cache_clear()

        redirect_response = MagicMock()
        redirect_response.status = 302
        redirect_response.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        redirect_response.release = MagicMock()  # release() is sync in aiohttp 3.x

        async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            return redirect_response

        monkeypatch.setattr(aiohttp.ClientSession, "request", fake_request)

        try:
            tool = HttpTool()
            result = await tool.execute(url="http://public.example.com/page")
            assert not result.success
            assert result.error is not None
        finally:
            settings_mod.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# f (continued). Redirect re-validation — httpx (langchain http_get)
# ---------------------------------------------------------------------------


class TestRedirectRevalidationHttpx:
    """langchain http_get must re-validate each redirect hop."""

    def test_redirect_to_private_ip_blocked(self, monkeypatch):
        """Public URL that 302s to a private IP is rejected."""
        import socket as socket_mod

        # DNS: public.example.com → public IP
        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            if host == "public.example.com":
                return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
            raise socket_mod.gaierror(f"unexpected host: {host}")

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        import httpx

        # First call returns a redirect; second call should never happen
        call_count = 0

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 302
            resp.headers = {"location": "http://10.0.0.1/internal"}
            resp.text = ""
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import http_get

        result = http_get.invoke({"url": "http://public.example.com/"})
        assert "ERROR" in result
        assert call_count == 1  # only the first hop was attempted

    def test_clean_request_succeeds(self, monkeypatch):
        """A request with no redirects to bad hosts succeeds."""
        import socket as socket_mod

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        import httpx

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = "Hello from example.com"
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import http_get

        result = http_get.invoke({"url": "http://example.com/"})
        assert "ERROR" not in result
        assert "Hello" in result

    def test_dns_name_request_is_ip_pinned(self, monkeypatch):
        """The validated address is the one dialled (DNS-rebinding defence).

        The request URL must carry the pinned IP while the original hostname
        travels in the Host header and (https) the sni_hostname extension.
        """
        import socket as socket_mod

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        import httpx

        seen: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            seen["extensions"] = kwargs.get("extensions")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = "pinned"
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import _http_get_with_redirect_guard

        resp = _http_get_with_redirect_guard("https://public.example.com/data")
        assert resp.text == "pinned"
        assert seen["url"] == "https://93.184.216.34/data"
        assert seen["headers"]["Host"] == "public.example.com"
        assert seen["extensions"] == {"sni_hostname": "public.example.com"}

    def test_ip_literal_request_not_pinned(self, monkeypatch):
        """IP-literal hosts involve no DNS — the URL is passed through as-is."""
        import httpx

        seen: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = "ok"
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import _http_get_with_redirect_guard

        _http_get_with_redirect_guard("http://93.184.216.34/")
        assert seen["url"] == "http://93.184.216.34/"
        assert seen["headers"] is None


# ---------------------------------------------------------------------------
# g. Redirect loop bound
# ---------------------------------------------------------------------------


class TestRedirectLoopBound:
    """More than 5 redirects must fail, not loop forever."""

    @pytest.mark.asyncio
    async def test_aiohttp_redirect_limit_exceeded(self, monkeypatch):
        """HttpTool stops after 5 redirects and returns an error."""
        import socket as socket_mod

        import aiohttp

        from agentic_v2.tools.builtin.http_ops import HttpTool

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        hop_counter = {"n": 0}

        async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            hop_counter["n"] += 1
            resp = MagicMock()
            resp.status = 302
            resp.headers = {"Location": f"http://public{hop_counter['n']}.example.com/"}

            resp.release = MagicMock()  # release() is sync in aiohttp 3.x
            return resp

        monkeypatch.setattr(aiohttp.ClientSession, "request", fake_request)

        tool = HttpTool()
        result = await tool.execute(url="http://public.example.com/start")
        assert not result.success
        assert result.error is not None
        # Confirm we stopped — at most 6 hops (initial + 5 redirects)
        assert hop_counter["n"] <= 6

    def test_httpx_redirect_limit_exceeded(self, monkeypatch):
        """langchain http_get stops after 5 redirects and returns an error."""
        import socket as socket_mod

        import httpx

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        hop_counter = {"n": 0}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            hop_counter["n"] += 1
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 302
            resp.headers = {"location": f"http://hop{hop_counter['n']}.example.com/"}
            resp.text = ""
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import http_get

        result = http_get.invoke({"url": "http://start.example.com/"})
        assert "ERROR" in result
        assert "limit" in result.lower() or "redirect" in result.lower()
        assert hop_counter["n"] <= 6


# ---------------------------------------------------------------------------
# MEDIUM-2. Redirect method preservation (RFC 7538/9110)
# ---------------------------------------------------------------------------


def _aiohttp_ok_response() -> Any:
    """Build a MagicMock standing in for a 200 aiohttp text response."""
    from unittest.mock import AsyncMock

    resp = MagicMock()
    resp.status = 200
    resp.headers = {"Content-Type": "text/plain"}
    resp.text = AsyncMock(return_value="ok")
    resp.release = MagicMock()  # release() is sync in aiohttp 3.x

    async def _aenter() -> Any:
        return resp

    async def _aexit(*_args: Any) -> None:
        return None

    resp.__aenter__ = MagicMock(side_effect=_aenter)
    resp.__aexit__ = MagicMock(side_effect=_aexit)
    return resp


class TestRedirectMethodPreservation:
    """307/308 preserve the original method + body; 301/302/303 become GET."""

    @pytest.mark.asyncio
    async def test_307_preserves_post_and_body(self, monkeypatch):
        """A 307 redirect re-issues the original POST with its body intact."""
        import socket as socket_mod

        import aiohttp

        from agentic_v2.tools.builtin.http_ops import HttpTool

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                (socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))
            ]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        hops: list[dict[str, Any]] = []

        async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            hops.append({"method": method, "url": url, "json": kwargs.get("json")})
            if len(hops) == 1:
                resp = MagicMock()
                resp.status = 307
                resp.headers = {"Location": "http://target.example.com/final"}
                resp.release = MagicMock()
                return resp
            return _aiohttp_ok_response()

        monkeypatch.setattr(aiohttp.ClientSession, "request", fake_request)

        tool = HttpTool()
        result = await tool.execute(
            url="http://origin.example.com/start",
            method="POST",
            body={"k": "v"},
        )
        assert result.success
        # Two hops: original POST, then the 307-preserved POST with same body.
        assert len(hops) == 2
        assert hops[0]["method"] == "POST"
        assert hops[1]["method"] == "POST"
        assert hops[1]["json"] == {"k": "v"}

    @pytest.mark.asyncio
    async def test_302_becomes_get_and_drops_body(self, monkeypatch):
        """A 302 redirect degrades the original POST to a bodyless GET."""
        import socket as socket_mod

        import aiohttp

        from agentic_v2.tools.builtin.http_ops import HttpTool

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                (socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))
            ]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        hops: list[dict[str, Any]] = []

        async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            hops.append({"method": method, "url": url, "json": kwargs.get("json")})
            if len(hops) == 1:
                resp = MagicMock()
                resp.status = 302
                resp.headers = {"Location": "http://target.example.com/final"}
                resp.release = MagicMock()
                return resp
            return _aiohttp_ok_response()

        monkeypatch.setattr(aiohttp.ClientSession, "request", fake_request)

        tool = HttpTool()
        result = await tool.execute(
            url="http://origin.example.com/start",
            method="POST",
            body={"k": "v"},
        )
        assert result.success
        assert len(hops) == 2
        assert hops[0]["method"] == "POST"
        # 302 → GET, body dropped.
        assert hops[1]["method"] == "GET"
        assert hops[1]["json"] is None


# ---------------------------------------------------------------------------
# h. Relative redirect resolution
# ---------------------------------------------------------------------------


class TestRelativeRedirectResolution:
    """Relative Location headers must be resolved against the current URL."""

    @pytest.mark.asyncio
    async def test_relative_redirect_to_private_blocked_aiohttp(self, monkeypatch):
        """A relative redirect that ultimately targets a private host is blocked."""
        import socket as socket_mod

        import aiohttp

        from agentic_v2.tools.builtin.http_ops import HttpTool

        call_urls: list[str] = []

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            # public.example.com → public; 127.0.0.1 is a literal, not DNS
            if host == "public.example.com":
                return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
            raise socket_mod.gaierror(f"unexpected: {host}")

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
            call_urls.append(url)
            resp = MagicMock()
            resp.status = 302
            # Relative redirect — resolves against http://public.example.com/page
            resp.headers = {"Location": "//127.0.0.1/secret"}

            resp.release = MagicMock()  # release() is sync in aiohttp 3.x
            return resp

        monkeypatch.setattr(aiohttp.ClientSession, "request", fake_request)

        tool = HttpTool()
        result = await tool.execute(url="http://public.example.com/page")
        assert not result.success
        # The redirect target 127.0.0.1 should have been blocked
        assert result.error is not None

    def test_relative_redirect_to_private_blocked_httpx(self, monkeypatch):
        """langchain http_get blocks a relative redirect targeting a private IP."""
        import socket as socket_mod

        import httpx

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            if host == "public.example.com":
                return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
            raise socket_mod.gaierror(f"unexpected: {host}")

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 302
            # Relative path redirect — should resolve to http://public.example.com/secret
            # In this test we want to redirect to private, use scheme-relative
            resp.headers = {"location": "//192.168.1.1/admin"}
            resp.text = ""
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import http_get

        result = http_get.invoke({"url": "http://public.example.com/"})
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# Async variant tests for url_guard (validate_url_async)
# ---------------------------------------------------------------------------


class TestValidateUrlAsync:
    """validate_url_async mirrors the sync guard but runs DNS in a thread."""

    @pytest.mark.asyncio
    async def test_async_private_ip_blocked(self):
        from agentic_v2.security.url_guard import validate_url_async

        result = await validate_url_async("http://10.0.0.5/", block_private=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_public_ip_allowed(self):
        from agentic_v2.security.url_guard import validate_url_async

        result = await validate_url_async("http://93.184.216.34/", block_private=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_async_dns_resolution_private_blocked(self, monkeypatch):
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url_async

        def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", ("192.168.1.1", 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", fake_getaddrinfo)

        result = await validate_url_async("http://internal.corp/", block_private=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_dns_failure_fail_closed(self, monkeypatch):
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url_async

        def raise_gaierror(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise socket_mod.gaierror("Name or service not known")

        monkeypatch.setattr(socket_mod, "getaddrinfo", raise_gaierror)

        result = await validate_url_async("http://unresolvable.invalid/", block_private=True)
        assert result is not None


# ---------------------------------------------------------------------------
# Multicast + legacy IP-literal representations
# ---------------------------------------------------------------------------


class TestMulticastBlocked:
    """Multicast addresses are restricted (local network probing vector)."""

    @pytest.mark.parametrize("url", ["http://224.0.0.1/", "http://[ff02::1]/"])
    def test_multicast_blocked_when_flag_on(self, url: str):
        from agentic_v2.security.url_guard import validate_url

        assert validate_url(url, block_private=True) is not None


class TestLegacyIpLiteralForms:
    """Decimal/octal/hex IPv4 forms the OS resolver accepts must not bypass."""

    @pytest.mark.parametrize(
        "host",
        [
            "2852039166",  # decimal == 169.254.169.254
            "0xA9FEA9FE",  # hex     == 169.254.169.254
            "0251.0376.0251.0376",  # octal == 169.254.169.254
        ],
    )
    def test_metadata_legacy_forms_blocked_even_when_flag_off(self, host: str):
        """The always-on metadata block resists alternative representations."""
        from agentic_v2.security.url_guard import validate_url

        result = validate_url(f"http://{host}/latest/meta-data/", block_private=False)
        assert result is not None, f"{host} bypassed the metadata block"
        assert "metadata" in result.lower()

    @pytest.mark.parametrize(
        "host",
        [
            "2130706433",  # decimal == 127.0.0.1
            "0x7f000001",  # hex     == 127.0.0.1
            "127.1",  # short   == 127.0.0.1
        ],
    )
    def test_loopback_legacy_forms_blocked_when_flag_on(self, host: str):
        from agentic_v2.security.url_guard import validate_url

        result = validate_url(f"http://{host}/", block_private=True)
        assert result is not None, f"{host} bypassed the private-IP block"

    @pytest.mark.parametrize(
        "host",
        [
            "2130706433",  # decimal  == 127.0.0.1
            "0177.0.0.1",  # octal-leading first octet == 127.0.0.1
            "0x7f000001",  # hex      == 127.0.0.1
        ],
    )
    def test_encoded_loopback_forms_blocked(self, host: str, monkeypatch):
        """LOW-4: alternative IPv4 encodings of 127.0.0.1 must be BLOCKED.

        Mechanism: ``_parse_ip_literal`` (via ``socket.inet_aton``) recognises
        these legacy forms as IP literals and they fail the loopback check with
        no DNS involved. ``getaddrinfo`` is monkeypatched to raise so that, even
        if a form were NOT recognised as a literal, the DNS path would
        fail-closed (gaierror) rather than reaching out to the network — making
        the BLOCKED outcome deterministic either way.
        """
        import socket as socket_mod

        from agentic_v2.security.url_guard import validate_url

        def _raise_gaierror(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise socket_mod.gaierror("forced — no network in tests")

        monkeypatch.setattr(socket_mod, "getaddrinfo", _raise_gaierror)

        result = validate_url(f"http://{host}/", block_private=True)
        assert result is not None, f"{host} bypassed the private-IP block"


class TestCheckResolvedAddress:
    """Connect-time per-address checker used by the guarded resolver."""

    def test_metadata_ip_blocked_even_without_flag(self):
        from agentic_v2.security.url_guard import check_resolved_address

        assert check_resolved_address("169.254.169.254", block_private=False) is not None

    def test_private_ip_blocked_with_flag(self):
        from agentic_v2.security.url_guard import check_resolved_address

        assert check_resolved_address("10.0.0.1", block_private=True) is not None

    def test_private_ip_allowed_without_flag(self):
        from agentic_v2.security.url_guard import check_resolved_address

        assert check_resolved_address("10.0.0.1", block_private=False) is None

    def test_public_ip_allowed(self):
        from agentic_v2.security.url_guard import check_resolved_address

        assert check_resolved_address("93.184.216.34", block_private=True) is None


# ---------------------------------------------------------------------------
# DNS rebinding (TOCTOU) — connect-time enforcement
# ---------------------------------------------------------------------------


class TestDnsRebinding:
    """A domain that flips public→private between check and connect is caught."""

    @pytest.mark.asyncio
    async def test_aiohttp_rebinding_blocked_at_connect_time(self, monkeypatch):
        """getaddrinfo returns a public IP for the pre-check, then a private
        IP when aiohttp's connector resolves — the GuardedResolver must block
        the connection (no request reaches the private address)."""
        import socket as socket_mod

        from agentic_v2.tools.builtin.http_ops import HttpTool

        monkeypatch.delenv("AGENTIC_BLOCK_PRIVATE_IPS", raising=False)
        import agentic_v2.settings as settings_mod

        settings_mod.get_settings.cache_clear()

        calls = {"n": 0}

        def rebinding_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", (ip, port or 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", rebinding_getaddrinfo)

        try:
            tool = HttpTool()
            result = await tool.execute(url="http://rebind.example.com/", timeout=5.0)
            assert not result.success
            assert result.error is not None
            # The block happened at the resolver/connect layer, not after a
            # successful request to the private address.
            assert calls["n"] >= 2
        finally:
            settings_mod.get_settings.cache_clear()

    def test_sync_pinning_uses_checked_address(self, monkeypatch):
        """httpx path: the address validated IS the address dialled, so a
        post-validation DNS flip cannot change the connect target."""
        import socket as socket_mod

        import httpx

        calls = {"n": 0}

        def rebinding_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", (ip, 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", rebinding_getaddrinfo)

        seen: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            seen["url"] = url
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = "ok"
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import _http_get_with_redirect_guard

        _http_get_with_redirect_guard("http://rebind.example.com/")
        # Connection target is the FIRST (validated) address — a later flip
        # to 127.0.0.1 never enters the picture.
        assert seen["url"] == "http://93.184.216.34/"

    def test_optout_mode_still_pins_to_checked_address(self, monkeypatch):
        """With the private-IP guard OPTED OUT (AGENTIC_BLOCK_PRIVATE_IPS=0) the
        httpx path still pins the connection to the screened address.

        Pinning is independent of the private-IP policy: a rebinding domain must
        not be able to pass the always-on metadata screen with a public address
        and then have the client re-resolve to a metadata/private address at
        connect time.  Private IPs remain permitted in this mode — only the
        connect target is locked to the address actually checked.
        """
        import socket as socket_mod

        import httpx

        monkeypatch.setenv("AGENTIC_BLOCK_PRIVATE_IPS", "0")
        import agentic_v2.settings as settings_mod

        settings_mod.get_settings.cache_clear()

        calls = {"n": 0}

        def rebinding_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
            return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 0, "", (ip, 0))]

        monkeypatch.setattr(socket_mod, "getaddrinfo", rebinding_getaddrinfo)

        seen: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            seen["url"] = url
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.text = "ok"
            return resp

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        from agentic_v2.langchain.tools import _http_get_with_redirect_guard

        try:
            _http_get_with_redirect_guard("http://rebind.example.com/")
            # Even opted out, the connect target is the screened address, not a
            # re-resolved rebinding flip to 127.0.0.1.
            assert seen["url"] == "http://93.184.216.34/"
        finally:
            settings_mod.get_settings.cache_clear()
