"""Tier 0 HTTP request tools - No LLM required."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import aiohttp

from ...settings import get_settings
from ...security.url_guard import validate_url_async
from ..base import BaseTool, ToolResult

# Maximum number of redirects to follow manually before giving up.
_MAX_REDIRECTS = 5

# HTTP status codes that carry a redirect Location header.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


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
    for hop in range(_MAX_REDIRECTS + 1):
        err = await validate_url_async(current_url, block_private=block_private)
        if err:
            raise ValueError(err)

        # Only send body / params on the first request; redirected GETs drop them.
        send_body = json_body if hop == 0 else None
        send_params = params if hop == 0 else {}
        send_method = method if hop == 0 else "GET"

        response = await session.request(
            method=send_method,
            url=current_url,
            headers=headers,
            json=send_body if send_body is not None else None,
            params=send_params,
            timeout=timeout_obj,
            allow_redirects=False,
        )

        if response.status not in _REDIRECT_STATUSES:
            return response, current_url

        if hop == _MAX_REDIRECTS:
            await response.release()
            raise ValueError(
                f"Redirect limit ({_MAX_REDIRECTS}) exceeded. "
                "Request blocked to prevent redirect loops."
            )

        location = response.headers.get("Location", "")
        await response.release()
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
    def description(self) -> str:
        return "Execute HTTP requests with support for various methods and headers"

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

            async with aiohttp.ClientSession() as session:
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
        return "Execute HTTP GET request"

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
    def description(self) -> str:
        return "Execute HTTP POST request with JSON body"

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
