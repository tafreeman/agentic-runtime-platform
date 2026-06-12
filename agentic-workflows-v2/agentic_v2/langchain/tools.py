"""Standard LangChain tool definitions.

Each tool is a plain ``@tool``-decorated function.  These replace the
custom ``BaseTool`` subclasses and are directly consumable by any
LangChain agent or ``ToolNode``.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from langchain_core.tools import tool

if TYPE_CHECKING:
    import httpx

from ..security.url_guard import validate_url_pinned
from ..settings import get_settings
from ..utils.path_safety import ensure_within_base


class _ApprovalGated:
    """Marker tool exposing ``requires_approval=True`` to the shared gate.

    The native ``@tool`` functions in this module are plain callables with no
    runtime ``BaseTool`` instance, so we hand the approval gate a tiny stand-in
    whose ``requires_approval`` flag forces the per-tool trigger. ``shell_run``
    and ``file_write`` are shell-exec / filesystem-write tools and are always
    treated as high-impact regardless of settings.
    """

    requires_approval = True

    def __init__(self, name: str) -> None:
        self.name = name


def _check_tool_approval(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Consult the human-approval gate from a synchronous ``@tool`` function.

    Returns an error string (the adapter's ``ERROR: ...`` contract) when the
    call is denied — including the fail-closed no-provider case — or ``None``
    when execution may proceed. Mirrors the engine/agent dispatch points but
    runs the async gate to completion from a sync caller.
    """
    from ..engine.tool_execution import call_id_for
    from ..governance.approval import evaluate_tool_approval

    async def _run() -> Any:
        return await evaluate_tool_approval(
            tool=_ApprovalGated(tool_name),
            tool_name=tool_name,
            tool_args=tool_args,
            call_id=call_id_for(tool_name, tool_args),
            agent_or_step=None,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Inside an event loop (e.g. async LangGraph node) — run on a worker.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            outcome = pool.submit(asyncio.run, _run()).result()
    else:
        outcome = asyncio.run(_run())

    if not outcome.allowed:
        return f"ERROR: {outcome.error_message}"
    return None

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

# Commands blocked from shell execution (case-insensitive substring match).
_SHELL_BLOCKLIST = frozenset(
    {
        "rm -rf /",
        "rm -r -f /",
        ":(){ :|:& };:",
        "mkfs",
        "dd if=",
        "> /dev/sda",
        "chmod -r 777 /",
        "chmod -R 777 /",
    }
)

# Maximum redirects to follow before giving up.
_MAX_REDIRECTS = 5

# HTTP status codes that carry a redirect Location header.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _is_dangerous_command(command: str) -> bool:
    """Return True if *command* matches any entry in the shell blocklist."""
    cmd_lower = command.lower()
    return any(pattern in cmd_lower for pattern in _SHELL_BLOCKLIST)


def _http_get_with_redirect_guard(
    url: str,
    *,
    timeout: float = 15,
    headers: dict[str, str] | None = None,
) -> "httpx.Response":
    """Perform an HTTP GET following redirects with SSRF re-validation.

    Args:
        url: Initial URL to fetch.
        timeout: Request timeout in seconds.
        headers: Optional extra request headers (sent on the first hop only).

    Returns:
        The final ``httpx.Response``.

    Raises:
        ValueError: When a redirect target is blocked or the limit is exceeded.
    """
    import httpx

    block_private = get_settings().agentic_block_private_ips
    current_url = url

    # One Client for all hops: reuses the connection pool instead of paying
    # client + pool setup/teardown per redirect.
    with httpx.Client(timeout=timeout) as client:
        for hop in range(_MAX_REDIRECTS + 1):
            request_url, host_header, extensions = _pin_request_target(
                current_url, block_private=block_private
            )

            # Only send custom headers on the first hop — re-sending caller
            # headers (Authorization, API keys) to a redirect target would
            # leak credentials to whatever host the server redirects to.
            hop_headers: dict[str, str] = dict(headers) if headers and hop == 0 else {}
            if host_header:
                hop_headers["Host"] = host_header

            resp = client.get(
                request_url,
                follow_redirects=False,
                headers=hop_headers or None,
                extensions=extensions,
            )

            if resp.status_code not in _REDIRECT_STATUSES:
                return resp

            if hop == _MAX_REDIRECTS:
                raise ValueError(
                    f"Redirect limit ({_MAX_REDIRECTS}) exceeded. "
                    "Request blocked to prevent redirect loops."
                )

            location = resp.headers.get("location", "")
            if not location:
                raise ValueError("Redirect response missing Location header.")

            # Resolve relative redirects against the LOGICAL hostname URL,
            # not the IP-pinned request URL.
            current_url = urljoin(current_url, location)

    raise ValueError("Unexpected exit from redirect loop.")  # pragma: no cover


def _pin_request_target(
    current_url: str, *, block_private: bool
) -> tuple[str, str | None, dict[str, Any] | None]:
    """Validate *current_url* and pin the connection to the validated IP.

    The guard's pre-request DNS check and the HTTP client's own resolution are
    otherwise two separate lookups — a rebinding domain can pass the first and
    serve a private/metadata address to the second.  When the guard resolved a
    DNS name, we connect to that exact address: the URL host is rewritten to
    the pinned IP, the original hostname travels in the ``Host`` header, and
    (for https) in the ``sni_hostname`` extension so TLS handshake + cert
    verification still use the real hostname.

    Returns ``(request_url, host_header, extensions)``; the last two are
    ``None`` when no pinning applies (IP-literal host or guard flag off).

    Raises:
        ValueError: When the guard blocks the URL.
    """
    from urllib.parse import urlparse

    err, pinned_ip = validate_url_pinned(current_url, block_private=block_private)
    if err:
        raise ValueError(err)
    if pinned_ip is None:
        return current_url, None, None

    parsed = urlparse(current_url)
    ip_netloc = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    if parsed.port:
        ip_netloc += f":{parsed.port}"
    request_url = parsed._replace(netloc=ip_netloc).geturl()

    hostname = parsed.hostname or ""
    host_header = f"{hostname}:{parsed.port}" if parsed.port else hostname
    extensions = {"sni_hostname": hostname} if parsed.scheme == "https" else None
    return request_url, host_header, extensions


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


@tool
def file_read(path: str) -> str:
    """Read the contents of a file and return them as a string.

    Args:
        path: Absolute or relative path to the file.
    """
    base_dir = os.environ.get("AGENTIC_FILE_BASE_DIR")
    if base_dir:
        try:
            ensure_within_base(path, base_dir)
        except ValueError as e:
            return f"ERROR: {e}"
    p = Path(path)
    if not p.exists():
        return f"ERROR: File not found: {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"


@tool
def file_write(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        path: Destination file path.
        content: Text content to write.
    """
    denied = _check_tool_approval("file_write", {"path": path, "content": content})
    if denied:
        return denied
    base_dir = os.environ.get("AGENTIC_FILE_BASE_DIR")
    if base_dir:
        try:
            ensure_within_base(path, base_dir)
        except ValueError as e:
            return f"ERROR: {e}"
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def file_list(directory: str, pattern: str = "*") -> str:
    """List files in a directory matching a glob pattern.

    Args:
        directory: Directory path to list.
        pattern: Glob pattern (default ``*``).
    """
    p = Path(directory)
    if not p.is_dir():
        return f"ERROR: Not a directory: {directory}"
    try:
        files = sorted(str(f.relative_to(p)) for f in p.glob(pattern) if f.is_file())
        return json.dumps(files[:200])
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Code analysis
# ---------------------------------------------------------------------------


@tool
def code_analyze(code: str, language: str = "python") -> str:
    """Analyze code and return structural metrics.

    Args:
        code: Source code string to analyze.
        language: Programming language (currently only ``python`` is supported).
    """
    if language != "python":
        return json.dumps({"error": f"Unsupported language: {language}"})

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return json.dumps({"error": f"Syntax error: {e}"})

    functions = []
    classes = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    return json.dumps(
        {
            "lines": len(code.splitlines()),
            "functions": functions,
            "classes": classes,
            "imports": imports,
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Shell / command execution
# ---------------------------------------------------------------------------


@tool
def shell_run(command: str, cwd: str | None = None, timeout: int = 30) -> str:
    """Execute a shell command and return stdout + stderr.

    Args:
        command: Shell command to run.
        cwd: Working directory (optional).
        timeout: Max seconds to wait (default 30).
    """
    denied = _check_tool_approval(
        "shell_run", {"command": command, "cwd": cwd, "timeout": timeout}
    )
    if denied:
        return denied
    if _is_dangerous_command(command):
        return "ERROR: Command blocked by security policy."
    try:
        result = subprocess.run(
            shlex.split(command),
            shell=False,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        # Truncate long output
        if len(output) > 12000:
            output = output[:12000] + "\n... (truncated)"
        return output
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Search / grep
# ---------------------------------------------------------------------------


def _scan_file_for_query(
    filepath: Path,
    root: Path,
    query_lower: str,
    results: list[dict],
    max_results: int,
) -> bool:
    """Append matching lines from *filepath* to *results*.

    Returns True if *results* reached *max_results* (caller should stop).
    """
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if query_lower in line.lower():
                results.append(
                    {
                        "file": str(filepath.relative_to(root)),
                        "line": i,
                        "content": line.strip()[:200],
                    }
                )
                if len(results) >= max_results:
                    return True
    except Exception:
        return False
    return False


@tool
def search_files(
    directory: str,
    query: str,
    file_pattern: str = "*.py",
    max_results: int = 20,
) -> str:
    """Search for a text pattern across files in a directory.

    Args:
        directory: Root directory to search.
        query: Text or regex pattern to search for.
        file_pattern: Glob pattern for files to search (default ``*.py``).
        max_results: Maximum number of results to return.
    """
    results: list[dict] = []
    p = Path(directory)
    if not p.is_dir():
        return f"ERROR: Not a directory: {directory}"

    query_lower = query.lower()
    try:
        for filepath in p.rglob(file_pattern):
            if not filepath.is_file():
                continue
            if _scan_file_for_query(filepath, p, query_lower, results, max_results):
                break
    except Exception as e:
        return f"ERROR: {e}"

    return json.dumps(results, indent=2)


# ---------------------------------------------------------------------------
# Context / memory
# ---------------------------------------------------------------------------


@tool
def context_store(key: str, value: str) -> str:
    """Store a key-value pair in the workflow context.

    Args:
        key: Context key name.
        value: Value to store (string).
    """
    # Agents can use this to pass structured data between steps.
    # The actual state update happens in the node wrapper.
    return json.dumps({"stored": key, "length": len(value)})


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@tool
def http_get(url: str) -> str:
    """Fetch content from a URL via HTTP GET.

    Args:
        url: The URL to fetch (http/https only, no private IPs).
    """
    try:
        resp = _http_get_with_redirect_guard(url, timeout=15)
        text = resp.text
        if len(text) > 12000:
            text = text[:12000] + "\n... (truncated)"
        return text
    except ValueError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------


def _normalize_domain_filter(domains: list[str] | None) -> list[str]:
    """Lowercase, strip, and drop empty/non-string entries from a domain filter."""
    return [
        d.strip().lower().lstrip(".")
        for d in (domains or [])
        if isinstance(d, str) and d.strip()
    ]


def _domain_matches(hostname: str, patterns: list[str]) -> bool:
    """Return True if *hostname* exactly equals or is a subdomain of a pattern."""
    host = hostname.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return any(host == pattern or host.endswith(f".{pattern}") for pattern in patterns)


def _fetch_ddg_results(query: str) -> tuple[list, list]:
    """Fetch DuckDuckGo HTML for *query* and return (links, snippets) matches."""
    import re
    from urllib.parse import urlencode

    # DuckDuckGo HTML endpoint avoids API-key dependencies.
    # Redirects from duckduckgo.com are re-validated by _http_get_with_redirect_guard.
    # Note: result URLs extracted from the HTML are NOT individually fetched here —
    # they are returned as strings for the caller to use; only the DDG page itself
    # (and any DDG-originated redirects) goes through the guard.
    ddg_url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
    response = _http_get_with_redirect_guard(
        ddg_url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    body = response.text

    # Guard against ReDoS on untrusted HTTP response bodies: cap input
    # length and rewrite inner-content captures to exclude '<' so the
    # engine cannot backtrack across tag boundaries.
    _MAX_BODY_LEN = 524288  # 512 KB — generous for a DuckDuckGo HTML page
    body = body[:_MAX_BODY_LEN]
    links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]*(?:<(?!/a>)[^<]*)*)</a>',
        body,
        flags=re.IGNORECASE,
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>([^<]*(?:<(?!/a>)[^<]*)*)</a>',
        body,
        flags=re.IGNORECASE,
    )
    return links, snippets


def _resolve_result_url(href: str) -> str:
    """Unwrap a DuckDuckGo ``/l/?uddg=...`` redirect link to its target URL."""
    url = href
    if "uddg=" in href:
        try:
            from urllib.parse import parse_qs, unquote, urlparse

            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if qs.get("uddg"):
                url = unquote(qs["uddg"][0])
        except ValueError:
            pass
    return url


def _hostname_for_url(url: str) -> str:
    """Return the lowercased netloc of *url* with a leading ``www.`` stripped."""
    from urllib.parse import urlparse

    hostname = urlparse(url).netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _clean_html_text(raw: str) -> str:
    """Strip HTML tags and unescape entities from *raw*, returning trimmed text."""
    import html
    import re

    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def _collect_search_results(
    links: list,
    snippets: list,
    allowed: list[str],
    blocked: list[str],
    max_results: int,
) -> list[dict[str, str]]:
    """Filter and assemble result entries from raw DuckDuckGo link/snippet matches."""
    results: list[dict[str, str]] = []
    for idx, (href, raw_title) in enumerate(links):
        url = _resolve_result_url(href)
        hostname = _hostname_for_url(url)

        if blocked and _domain_matches(hostname, blocked):
            continue
        if allowed and not _domain_matches(hostname, allowed):
            continue

        snippet = ""
        if idx < len(snippets):
            snippet = _clean_html_text(snippets[idx])

        results.append(
            {
                "title": _clean_html_text(raw_title),
                "url": url,
                "domain": hostname,
                "snippet": snippet,
            }
        )
        if len(results) >= max_results:
            break
    return results


@tool
def web_search(
    query: str,
    max_results: int = 5,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> str:
    """Search the public web and return top result URLs/snippets.

    Args:
        query: Search query text.
        max_results: Maximum number of results to return (1-10).
        allowed_domains: Optional domain allowlist (exact or suffix match).
        blocked_domains: Optional domain blocklist (exact or suffix match).
    """
    max_results = max(1, min(int(max_results), 10))
    allowed = _normalize_domain_filter(allowed_domains)
    blocked = _normalize_domain_filter(blocked_domains)

    try:
        links, snippets = _fetch_ddg_results(query)
        results = _collect_search_results(
            links, snippets, allowed, blocked, max_results
        )

        return json.dumps(
            {
                "query": query,
                "filters": {
                    "allowed_domains": allowed,
                    "blocked_domains": blocked,
                },
                "results": results,
            },
            indent=2,
        )
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool registry helper
# ---------------------------------------------------------------------------

# Master list of all available tools
ALL_TOOLS = [
    file_read,
    file_write,
    file_list,
    code_analyze,
    shell_run,
    search_files,
    web_search,
    context_store,
    http_get,
]

# Tier-based tool sets (agents get tools matching their tier or below)
TIER_TOOLS: dict[int, list] = {
    0: [file_read, file_list, code_analyze],
    1: [file_read, file_write, file_list, code_analyze, search_files],
    2: [
        file_read,
        file_write,
        file_list,
        code_analyze,
        search_files,
        web_search,
        shell_run,
        context_store,
        http_get,
    ],
    3: ALL_TOOLS,
    4: ALL_TOOLS,
    5: ALL_TOOLS,
}


def get_tools_for_tier(tier: int) -> list:
    """Return the tool list appropriate for a given model tier."""
    return list(TIER_TOOLS.get(min(tier, 5), ALL_TOOLS))


def get_tools_by_name(names: list[str]) -> list:
    """Filter tools to only those matching the given names."""
    name_set = set(names)
    return [t for t in ALL_TOOLS if t.name in name_set]
