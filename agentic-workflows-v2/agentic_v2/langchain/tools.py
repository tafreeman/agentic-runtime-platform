"""Standard LangChain tool definitions.

Each tool is a plain ``@tool``-decorated function.  These replace the
custom ``BaseTool`` subclasses and are directly consumable by any
LangChain agent or ``ToolNode``.
"""

from __future__ import annotations

import ast
import ipaddress
import json
import os
import shlex
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from langchain_core.tools import tool

from ..utils.path_safety import ensure_within_base

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

# Allowed URL schemes for HTTP tools.
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _is_dangerous_command(command: str) -> bool:
    """Return True if *command* matches any entry in the shell blocklist."""
    cmd_lower = command.lower()
    return any(pattern in cmd_lower for pattern in _SHELL_BLOCKLIST)


def _is_private_ip(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private/reserved IP address.

    Only active when ``AGENTIC_BLOCK_PRIVATE_IPS=1``.
    """
    if os.environ.get("AGENTIC_BLOCK_PRIVATE_IPS", "").strip() != "1":
        return False
    try:
        addr = ipaddress.ip_address(hostname)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
        )
    except ValueError:
        return False


def _validate_url(url: str) -> str | None:
    """Validate a URL for SSRF safety.

    Returns error string or None.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        return f"URL scheme '{parsed.scheme}' not allowed. Only http/https permitted."

    hostname = parsed.hostname or ""

    # Block cloud metadata endpoints and private IPs
    if _is_private_ip(hostname):
        return f"Access to private/reserved IP address '{hostname}' is blocked."

    # Block well-known metadata hostnames
    metadata_hosts = {"metadata.google.internal", "metadata", "169.254.169.254"}
    if hostname.lower() in metadata_hosts:
        return f"Access to metadata endpoint '{hostname}' is blocked."

    return None


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
    results = []
    p = Path(directory)
    if not p.is_dir():
        return f"ERROR: Not a directory: {directory}"

    try:
        for filepath in p.rglob(file_pattern):
            if not filepath.is_file():
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if query.lower() in line.lower():
                        results.append(
                            {
                                "file": str(filepath.relative_to(p)),
                                "line": i,
                                "content": line.strip()[:200],
                            }
                        )
                        if len(results) >= max_results:
                            return json.dumps(results, indent=2)
            except Exception:
                continue
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
    url_error = _validate_url(url)
    if url_error:
        return f"ERROR: {url_error}"
    try:
        import httpx

        resp = httpx.get(url, timeout=15, follow_redirects=True)
        text = resp.text
        if len(text) > 12000:
            text = text[:12000] + "\n... (truncated)"
        return text
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------


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
    allowed = [
        d.strip().lower().lstrip(".")
        for d in (allowed_domains or [])
        if isinstance(d, str) and d.strip()
    ]
    blocked = [
        d.strip().lower().lstrip(".")
        for d in (blocked_domains or [])
        if isinstance(d, str) and d.strip()
    ]

    try:
        import html
        import re

        import httpx

        # DuckDuckGo HTML endpoint avoids API-key dependencies.
        response = httpx.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        body = response.text

        links = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippets = re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        from urllib.parse import urlparse

        def _matches(hostname: str, patterns: list[str]) -> bool:
            host = hostname.lower().lstrip(".")
            if host.startswith("www."):
                host = host[4:]
            for pattern in patterns:
                if host == pattern or host.endswith(f".{pattern}"):
                    return True
            return False

        results: list[dict[str, str]] = []
        for idx, (href, raw_title) in enumerate(links):
            # DuckDuckGo wraps redirect links as /l/?uddg=... .
            url = href
            if "uddg=" in href:
                try:
                    from urllib.parse import parse_qs, unquote, urlparse

                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    if qs.get("uddg"):
                        url = unquote(qs["uddg"][0])
                except Exception:
                    pass

            parsed_url = urlparse(url)
            hostname = parsed_url.netloc.lower()
            if hostname.startswith("www."):
                hostname = hostname[4:]

            if blocked and _matches(hostname, blocked):
                continue
            if allowed and not _matches(hostname, allowed):
                continue

            title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            snippet = ""
            if idx < len(snippets):
                snippet = html.unescape(re.sub(r"<[^>]+>", "", snippets[idx])).strip()

            results.append(
                {
                    "title": title,
                    "url": url,
                    "domain": hostname,
                    "snippet": snippet,
                }
            )
            if len(results) >= max_results:
                break

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
