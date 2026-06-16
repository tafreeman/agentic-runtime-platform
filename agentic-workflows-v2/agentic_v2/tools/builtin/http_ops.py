"""Tier 0 HTTP request tools - No LLM required."""

from __future__ import annotations

import socket
from typing import Any
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

from ...security.url_guard import check_resolved_address, validate_url_async
from ...settings import get_settings
from ..base import BaseTool, ToolResult

# Maximum number of redirects to follow manually before giving up.
_MAX_REDIRECTS = 5

# HTTP status codes that carry a redirect Location header.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# RFC 7538 / RFC 9110: 307 and 308 MUST preserve the original request method
# and body. 301/302/303 historically degrade to GET and drop the body — this is
# what browsers and HTTP clients do in practice.
_METHOD_PRESERVING_REDIRECTS = frozenset({307, 308})


class GuardedResolver(AbstractResolver):
    """DNS resolver that re-applies the SSRF guard at connect time.

    The pre-request ``validate_url_async`` check resolves the hostname in a
    separate ``getaddrinfo`` call; a DNS-rebinding domain can return a public
    address there and a private/metadata address when the HTTP client
    resolves again to connect.  Wrapping the connector's resolver closes that
    TOCTOU window: every address aiohttp is about to dial is validated here,
    and a restricted result aborts the connection (surfacing as a
    ``ClientConnectorError``).

    IP-literal hosts never reach the resolver — they are validated by the
    pre-request check and involve no DNS, so rebinding does not apply.
    Metadata endpoint IPs are blocked unconditionally; private/loopback/
    link-local/etc. only when *block_private* is on (so the localhost opt-out
    used by dev/test environments keeps working).
    """

    def __init__(self, block_private: bool) -> None:
        self._inner = DefaultResolver()
        self._block_private = block_private

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[dict[str, Any]]:
        infos = await self._inner.resolve(host, port, family)
        for info in infos:
            err = check_resolved_address(
                str(info["host"]), block_private=self._block_private
            )
            if err:
                raise OSError(f"SSRF guard blocked connection to '{host}': {err}")
        return infos

    async def close(self) -> None:
        await self._inner.close()


async def _guarded_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: Any,
    params: dict[str, str],
    timeout_obj: aiohttp.ClientTimeout,
    block_private: bool,
) -> tuple[aiohttp.ClientResponse, str]:
    """Execute *method* on *url* following redirects with SSRF re-validation.

    Returns ``(response, final_url)`` where the response is from the last hop.
    The caller is responsible for closing the response (use ``async with``).

    Raises ``ValueError`` with a human-readable message on SSRF block or
    when the redirect limit is exceeded.
    """
    current_url = url
    # Per-hop method/body/params evolve as we follow redirects. RFC 7538/9110:
    # 307/308 preserve the original method and body; 301/302/303 degrade to GET
    # and drop the body. These start as the caller's values and are updated from
    # each redirect's status before the next hop.
    current_method = method
    current_body = json_body
    current_params = params
    for hop in range(_MAX_REDIRECTS + 1):
        err = await validate_url_async(current_url, block_private=block_private)
        if err:
            raise ValueError(err)

        # Custom headers are sent on the FIRST hop only — re-sending caller
        # headers (Authorization, API keys) to a redirect target would leak
        # credentials to whatever host the original server chose to redirect to.
        send_headers = headers if hop == 0 else {}

        response = await session.request(
            method=current_method,
            url=current_url,
            headers=send_headers,
            json=current_body if current_body is not None else None,
            params=current_params,
            timeout=timeout_obj,
            allow_redirects=False,
        )

        if response.status not in _REDIRECT_STATUSES:
            return response, current_url

        if hop == _MAX_REDIRECTS:
            # ClientResponse.release() is synchronous in aiohttp 3.x.
            response.release()
            raise ValueError(
                f"Redirect limit ({_MAX_REDIRECTS}) exceeded. "
                "Request blocked to prevent redirect loops."
            )

        # Decide how the NEXT hop is issued based on THIS redirect's status.
        if response.status not in _METHOD_PRESERVING_REDIRECTS:
            # 301/302/303 → GET, drop the body and the original query params.
            current_method = "GET"
            current_body = None
            current_params = {}
        # else 307/308 → keep current_method / current_body / current_params.

        location = response.headers.get("Location", "")
        response.release()
        if not location:
            raise ValueError("Redirect response missing Location header.")

        # Resolve relative redirects against the current URL.
        current_url = urljoin(current_url, location)

    # Unreachable, but satisfies the type checker.
    raise ValueError("Unexpected exit from redirect loop.")  # pragma: no cover


class HttpTool(BaseTool):
    """Execute HTTP requests (GET, POST, PUT, DELETE, etc.)."""

    @property
    def name(self) -> str:
        return "http"

    @property
    def requires_approval(self) -> bool:
        # High-impact: can issue mutating requests (POST/PUT/DELETE). Gated.
        return True

    @property
    def description(self) -> str:
        return (
            "General HTTP client for ANY method (GET/POST/PUT/DELETE/PATCH/"
            "HEAD/OPTIONS). Takes a `url`, a `method` (default GET), optional "
            "`headers`, `params` (query string), `body` (a dict that is "
            "JSON-encoded), and a `timeout` in seconds (default 30). Returns "
            "status code, response headers, and decoded body. Requires approval "
            "because it can issue mutating requests. Edge cases: non-2xx status "
            "codes are returned, not raised; a timeout yields a failure result. "
            "PREFER the `http_get` wrapper for a plain read and `http_post` for "
            "a JSON create; reach for this generic tool when you need PUT, "
            "DELETE, PATCH, a custom timeout, or full method control."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "url": {
                "type": "string",
                "description": "URL to send request to",
                "required": True,
            },
            "method": {
                "type": "string",
                "description": "HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)",
                "required": False,
                "default": "GET",
            },
            "headers": {
                "type": "object",
                "description": "HTTP headers as key-value pairs",
                "required": False,
                "default": {},
            },
            "body": {
                "type": "object",
                "description": "Request body (will be JSON-encoded)",
                "required": False,
                "default": None,
            },
            "params": {
                "type": "object",
                "description": "URL query parameters",
                "required": False,
                "default": {},
            },
            "timeout": {
                "type": "number",
                "description": "Request timeout in seconds",
                "required": False,
                "default": 30,
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "http(url='https://api.example.com/data', method='GET') → Fetch data",
            "http(url='https://api.example.com/create', method='POST', body={'name': 'test'}) → Create resource",
            "http(url='https://api.example.com/search', params={'q': 'query'}) → Search with params",
        ]

    async def execute(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: dict | list | None = None,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> ToolResult:
        """Execute HTTP request."""
        try:
            allowed_methods = {
                "GET",
                "POST",
                "PUT",
                "DELETE",
                "PATCH",
                "HEAD",
                "OPTIONS",
            }
            method = method.upper()
            if method not in allowed_methods:
                return ToolResult(
                    success=False,
                    error=f"Method '{method}' not allowed. Allowed: {', '.join(sorted(allowed_methods))}",
                )

            headers = headers or {}
            params_map: dict[str, str] = params or {}

            if body is not None and "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"

            block_private = get_settings().agentic_block_private_ips

            # GuardedResolver re-validates every DNS answer at connect time so
            # a rebinding domain cannot serve a public address to the pre-check
            # and a private/metadata one to the actual connection.
            connector = aiohttp.TCPConnector(resolver=GuardedResolver(block_private))
            async with aiohttp.ClientSession(connector=connector) as session:
                timeout_obj = aiohttp.ClientTimeout(total=timeout)
                try:
                    response, final_url = await _guarded_request(
                        session,
                        method,
                        url,
                        headers=headers,
                        json_body=body,
                        params=params_map,
                        timeout_obj=timeout_obj,
                        block_private=block_private,
                    )
                except ValueError as guard_err:
                    return ToolResult(success=False, error=str(guard_err))

                async with response:
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        response_data = await response.json()
                    else:
                        response_data = await response.text()

                    return ToolResult(
                        success=response.status < 400,
                        data={
                            "status": response.status,
                            "headers": dict(response.headers),
                            "body": response_data,
                            "url": final_url,
                        },
                        metadata={
                            "method": method,
                            "content_type": content_type,
                            "status_code": response.status,
                        },
                    )

        except aiohttp.ClientError as e:
            return ToolResult(
                success=False,
                error=f"HTTP request failed: {e!s}",
                metadata={"url": url, "method": method},
            )
        except Exception as e:
            return ToolResult(
                success=False, error=f"Failed to execute HTTP request: {e!s}"
            )


class HttpGetTool(BaseTool):
    """Convenience wrapper for HTTP GET requests."""

    @property
    def name(self) -> str:
        return "http_get"

    @property
    def description(self) -> str:
        return (
            "Read-only HTTP GET convenience wrapper: fetch a `url` with optional "
            "query `params` and `headers`. Sends NO request body and is "
            "ungated, so use it for safe idempotent reads (fetch a page, hit a "
            "read API, poll a status endpoint). Returns status, headers, and "
            "decoded body; non-2xx codes are returned rather than raised. PREFER "
            "`http_get` for safe reads; for a state-changing call prefer "
            "`http_post`; for PUT/DELETE/PATCH or a custom timeout use the "
            "generic `http` tool."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "url": {
                "type": "string",
                "description": "URL to fetch",
                "required": True,
            },
            "params": {
                "type": "object",
                "description": "URL query parameters",
                "required": False,
                "default": {},
            },
            "headers": {
                "type": "object",
                "description": "HTTP headers",
                "required": False,
                "default": {},
            },
        }

    async def execute(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ToolResult:
        """Execute HTTP GET."""
        http_tool = HttpTool()
        return await http_tool.execute(
            url=url, method="GET", params=params, headers=headers
        )


class HttpPostTool(BaseTool):
    """Convenience wrapper for HTTP POST requests."""

    @property
    def name(self) -> str:
        return "http_post"

    @property
    def requires_approval(self) -> bool:
        # High-impact: state-changing HTTP POST. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "HTTP POST convenience wrapper: send a `body` dict (JSON-encoded) to "
            "a `url` with optional `headers`. Use it for state-changing creates "
            "/submits (create a resource, submit a form, call a write API). "
            "Requires approval because it mutates server state. Returns status, "
            "headers, and decoded body; non-2xx codes are returned, not raised. "
            "PREFER `http_post` for a JSON create/submit; for a read prefer "
            "`http_get`; for PUT/DELETE/PATCH or a custom timeout use the "
            "generic `http` tool."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "url": {
                "type": "string",
                "description": "URL to post to",
                "required": True,
            },
            "body": {
                "type": "object",
                "description": "JSON body to send",
                "required": True,
            },
            "headers": {
                "type": "object",
                "description": "HTTP headers",
                "required": False,
                "default": {},
            },
        }

    async def execute(
        self,
        url: str,
        body: dict | list,
        headers: dict[str, str] | None = None,
    ) -> ToolResult:
        """Execute HTTP POST."""
        http_tool = HttpTool()
        return await http_tool.execute(
            url=url, method="POST", body=body, headers=headers
        )
