from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from agentic_v2 import langchain as langchain_module
from agentic_v2.adapters import langchain as langchain_adapter_module
from agentic_v2.core import tenant as tenant_mod
from agentic_v2.server import middleware as server_middleware
from agentic_v2.server.routes import models as model_routes
from agentic_v2.settings import (
    Settings,
    _coerce_env_flag,
    get_settings,
    is_agentic_no_llm_enabled,
)
from agentic_v2.utils import path_safety


@pytest.mark.asyncio
async def test_model_probe_route_covers_success_importerror_and_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(
        probe_and_update_tier_defaults=lambda: {"available_providers": ["openai"]}
    )
    monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", fake_module)
    assert await model_routes.probe_models() == {"available_providers": ["openai"]}

    fake_module = SimpleNamespace(
        probe_and_update_tier_defaults=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", fake_module)
    with pytest.raises(Exception) as exc_info:
        await model_routes.probe_models()
    assert getattr(exc_info.value, "status_code", None) == 500

    real_import = builtins.__import__

    def _fake_import(name, globalns=None, localns=None, fromlist=(), level=0):
        if name == "agentic_v2.langchain.models":
            raise ImportError("missing extras")
        return real_import(name, globalns, localns, fromlist, level)

    import agentic_v2.langchain as langchain_pkg

    monkeypatch.delitem(sys.modules, "agentic_v2.langchain.models", raising=False)
    monkeypatch.delattr(langchain_pkg, "models", raising=False)
    monkeypatch.setitem(sys.modules, "agentic_v2.langchain.models", None)
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(Exception) as exc_info:
        await model_routes.probe_models()
    assert getattr(exc_info.value, "status_code", None) == 503


def test_settings_helpers_cover_env_coercion_and_cached_settings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert _coerce_env_flag(True, var_name="FLAG") is True
    assert _coerce_env_flag(None, var_name="FLAG") is False

    monkeypatch.setenv("AGENTIC_NO_LLM", "yes")
    assert is_agentic_no_llm_enabled() is True

    caplog.clear()
    monkeypatch.setenv("AGENTIC_NO_LLM", "2")
    assert is_agentic_no_llm_enabled() is False
    assert "not recognised" in caplog.text

    settings = Settings(
        log_format="LOUD",
        audit_log_backend="mystery",
        agentic_oidc_algorithms="RS256, HS256",
    )
    assert settings.log_format == "text"
    assert settings.audit_log_backend == "file"
    assert settings.agentic_oidc_algorithms == ["RS256", "HS256"]

    list_settings = Settings(agentic_oidc_algorithms=[" RS256 ", "", "HS256"])
    assert list_settings.agentic_oidc_algorithms == ["RS256", "HS256"]

    none_settings = Settings(
        log_format=None,
        audit_log_backend=None,
        agentic_oidc_algorithms=None,
    )
    assert none_settings.log_format == "text"
    assert none_settings.audit_log_backend == "file"
    assert none_settings.agentic_oidc_algorithms == ["RS256"]

    fallback_settings = Settings(agentic_oidc_algorithms=object())
    assert fallback_settings.agentic_oidc_algorithms == ["RS256"]

    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second


def test_oidc_algorithms_env_comma_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare comma-separated env value parses to a list via the env source.

    PR #74 review: the field is ``Annotated[list[str], NoDecode]`` so
    pydantic-settings does not try (and fail) to JSON-decode the raw env
    string; the before-validator performs the comma split. The declared type
    stays ``list[str]`` so consumers (e.g. PyJWT) never receive a raw string.
    """
    monkeypatch.setenv("AGENTIC_OIDC_ALGORITHMS", "RS256,HS256")
    settings = Settings()
    assert settings.agentic_oidc_algorithms == ["RS256", "HS256"]

    monkeypatch.setenv("AGENTIC_OIDC_ALGORITHMS", "ES256")
    single = Settings()
    assert single.agentic_oidc_algorithms == ["ES256"]


def test_tenant_helpers_cover_claims_and_dry_run(tmp_path: Path) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(agentic_oidc_enabled=True)),
        }
    )
    request.state.user = {"claims": {"tenant": "claims tenant", "sub": "claims-user"}}
    resolved = tenant_mod.get_tenant_context(request)
    assert resolved.tenant_id == "claims_tenant"
    assert resolved.actor_subject == "claims-user"

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    dry_file = runs_root / "run.json"
    dry_file.write_text("{}", encoding="utf-8")
    moved = tenant_mod.migrate_legacy_tenant_storage(
        runs_dir=runs_root,
        datasets_dir=tmp_path / "datasets-missing",
        tenant_id="tenant-b",
        dry_run=True,
    )
    assert moved["runs"]
    assert dry_file.exists()
    assert not (runs_root / "tenant-b").exists()

    target = tenant_mod.tenant_run_dir("tenant-b", base_dir=tmp_path / "other-runs", create=False)
    assert target.name == "tenant-b"
    assert not target.exists()


@pytest.mark.asyncio
async def test_sanitization_dispatch_covers_non_json_and_body_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = server_middleware.SanitizationASGIMiddleware(lambda scope, receive, send: None)
    app = SimpleNamespace(state=SimpleNamespace(sanitization=object()))
    called = {"count": 0}

    async def _call_next(_request):
        called["count"] += 1
        return JSONResponse({"ok": True})

    class _FakeRequest:
        def __init__(self, headers, body_result=None, body_error=None):
            self.app = app
            self.headers = headers
            self._body_result = body_result
            self._body_error = body_error
            self.scope = {"type": "http"}

        async def body(self):
            if self._body_error is not None:
                raise self._body_error
            return self._body_result

    response = await middleware.dispatch(_FakeRequest({"content-type": "text/plain"}), _call_next)
    assert response.status_code == 200
    assert called["count"] == 1

    monkeypatch.delenv("AGENTIC_SANITIZER_FAIL_OPEN", raising=False)
    response = await middleware.dispatch(
        _FakeRequest(
            {"content-type": "application/json"},
            body_error=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        ),
        _call_next,
    )
    assert response.status_code == 400

    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    response = await middleware.dispatch(
        _FakeRequest(
            {"content-type": "application/json"},
            body_error=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        ),
        _call_next,
    )
    assert response.status_code == 200

    response = await middleware.dispatch(
        _FakeRequest(
            {"content-type": "application/json"},
            body_error=RuntimeError("broken body"),
        ),
        _call_next,
    )
    assert response.status_code == 200


def test_path_safety_fallback_branch_without_is_relative_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ResolvedPath:
        def __init__(self, value: str):
            self.value = value

        def is_relative_to(self, _other):
            raise AttributeError()

        def __str__(self) -> str:
            return self.value

    class _FakePath:
        def __init__(self, value):
            self.value = str(value)

        def resolve(self):
            return _ResolvedPath(self.value)

    # Use platform-native separator so the os.sep fallback works on Linux and Windows.
    sep = os.sep
    monkeypatch.setattr(path_safety, "Path", _FakePath)
    assert path_safety.is_within_base(f"{sep}repo{sep}child", f"{sep}repo") is True
    assert path_safety.is_within_base(f"{sep}elsewhere", f"{sep}repo") is False


def test_langchain_module_getattr_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    assert langchain_module.get_chat_model is not None
    assert langchain_module.get_model_for_tier is not None
    assert langchain_module.compile_workflow is not None
    assert langchain_module.WorkflowRunner is not None

    monkeypatch.delattr(langchain_adapter_module, "LangChainEngine", raising=False)
    monkeypatch.setattr(
        langchain_adapter_module,
        "_IMPORT_ERROR",
        ImportError("missing adapter extras"),
    )
    with pytest.raises(ImportError):
        _ = langchain_adapter_module.LangChainEngine

    with pytest.raises(AttributeError):
        _ = langchain_module.does_not_exist
