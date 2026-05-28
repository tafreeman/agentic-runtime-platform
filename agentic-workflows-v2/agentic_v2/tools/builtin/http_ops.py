"""Tier 0 HTTP request tools - No LLM required."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import aiohttp

from ..base import BaseTool, ToolResult

# ---------------------------------------------------------------------------
# URL validation for SSRF prevention
# ---------------------------------------------------------------------------

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
_METADATA_HOSTS = frozenset({"metadata.google.internal", "metadata", "169.254.169.254"})


def _validate_url(url: str) -> str | None:
    """Validate a URL for SSRF safety. Returns error string or None.

    Always blocks:
      - Non http/https schemes
      - Cloud metadata endpoints (169.254.169.254, metadata.google.internal)

    When ``AGENTIC_BLOCK_PRIVATE_IPS=1`` is set:
      - Also blocks RFC 1918 private IPs, loopback, and link-local addresses
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        return f"URL scheme '{parsed.scheme}' not allowed. Only http/https permitted."

    hostname = parsed.hostname or ""

    # Always block well-known metadata hostnames
    if hostname.lower() in _METADATA_HOSTS:
        return f"Access to metadata endpoint '{hostname}' is blocked."

    # Block private/reserved IP addresses when strict mode is enabled
    from ...settings import get_settings
    block_private = get_settings().agentic_block_private_ips
    if block_private:
        try:
            addr = ipaddress.ip_address(hostname)
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
            ):
                return f"Access to private/reserved IP address '{hostname}' is blocked."
        except ValueError:
            pass  # hostname is not an IP literal — allowed

    return None


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
            # Validate URL for SSRF
            url_error = _validate_url(url)
            if url_error:
                return ToolResult(success=False, error=url_error)

            # Validate method
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

            # Prepare request
            headers = headers or {}
            params = params or {}

            # Add default content-type for JSON body
            if body is not None and "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"

            async with aiohttp.ClientSession() as session:
                timeout_obj = aiohttp.ClientTimeout(total=timeout)

                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if body is not None else None,
                    params=params,
                    timeout=timeout_obj,
                ) as response:
                    # Read response
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
                            "url": str(response.url),
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
