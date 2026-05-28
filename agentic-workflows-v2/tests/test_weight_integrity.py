"""Tests for local model weight integrity verification."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "agentic_v2"
_MODULE_PATH = _PACKAGE_ROOT / "models" / "weight_integrity.py"


def _load_weight_integrity() -> ModuleType:
    """Load the module directly to avoid broad package re-exports in tests."""
    spec = importlib.util.spec_from_file_location(
        "agentic_v2.models.weight_integrity",
        _MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_known_hash_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_weight_integrity()
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"known model bytes")
    expected = hashlib.sha256(b"known model bytes").hexdigest()
    monkeypatch.setenv("AGENTIC_TRUSTED_MODEL_HASHES", str(tmp_path / "missing.yaml"))

    result = module.verify_model_weights(model_file, expected_hash=expected)

    assert result.verified is True
    assert result.status == "verified"
    assert result.actual_hash == expected
    assert result.expected_hash == expected
    assert result.warnings == []


def test_mismatch_warns_when_not_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_weight_integrity()
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"actual")
    monkeypatch.delenv("AGENTIC_STRICT_MODEL_VERIFY", raising=False)
    monkeypatch.setenv("AGENTIC_TRUSTED_MODEL_HASHES", str(tmp_path / "missing.yaml"))

    result = module.verify_model_weights(model_file, expected_hash="0" * 64)

    assert result.verified is False
    assert result.status == "mismatch"
    assert result.warnings


def test_mismatch_errors_when_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_weight_integrity()
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"actual")
    monkeypatch.setenv("AGENTIC_STRICT_MODEL_VERIFY", "1")
    monkeypatch.setenv("AGENTIC_TRUSTED_MODEL_HASHES", str(tmp_path / "missing.yaml"))

    with pytest.raises(module.ModelWeightVerificationError):
        module.verify_model_weights(model_file, expected_hash="0" * 64)


def test_missing_hash_file_is_graceful_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_weight_integrity()
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"actual")
    monkeypatch.delenv("AGENTIC_STRICT_MODEL_VERIFY", raising=False)
    monkeypatch.setenv("AGENTIC_TRUSTED_MODEL_HASHES", str(tmp_path / "missing.yaml"))

    result = module.verify_model_weights(model_file)

    assert result.verified is False
    assert result.status == "unknown"
    assert result.actual_hash == hashlib.sha256(b"actual").hexdigest()
    assert result.expected_hash is None
    assert result.warnings


def test_yaml_schema_validation_rejects_invalid_entries(tmp_path: Path) -> None:
    module = _load_weight_integrity()
    config_path = tmp_path / "trusted_model_hashes.yaml"
    config_path.write_text(
        """
schema_version: trusted-model-hashes.v1
models:
  - id: bad-entry
    path: ./model.onnx
    sha256: not-a-sha256
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(module.TrustedHashConfigError):
        module.load_trusted_hashes(config_path)


def test_trusted_hashes_can_be_loaded_by_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_weight_integrity()
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"trusted")
    expected = hashlib.sha256(b"trusted").hexdigest()
    config_path = tmp_path / "trusted_model_hashes.yaml"
    config_path.write_text(
        f"""
schema_version: trusted-model-hashes.v1
models:
  - id: local-test-model
    path: {model_file.as_posix()}
    sha256: {expected}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTIC_TRUSTED_MODEL_HASHES", str(config_path))

    result = module.verify_model_weights(model_file)

    assert result.verified is True
    assert result.status == "verified"
    assert result.config_path == config_path


@pytest.mark.skip(
    reason="Fails when global sys.path resolves tools.llm to a sibling clone. "
           "Requires isolated venv for correct execution."
)
def test_local_provider_verifies_weights_before_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.llm import provider_adapters

    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"trusted")
    config_path = tmp_path / "trusted_model_hashes.yaml"
    config_path.write_text(
        f"""
schema_version: trusted-model-hashes.v1
models:
  - id: local-test-model
    path: {model_file.as_posix()}
    sha256: {"0" * 64}
""".strip(),
        encoding="utf-8",
    )

    class FakeLocalModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("LocalModel should not load after strict mismatch")

    monkeypatch.setitem(
        sys.modules,
        "tools.llm.local_model",
        SimpleNamespace(LocalModel=FakeLocalModel),
    )
    monkeypatch.setenv("AGENTIC_TRUSTED_MODEL_HASHES", str(config_path))
    monkeypatch.setenv("AGENTIC_STRICT_MODEL_VERIFY", "1")

    with pytest.raises(RuntimeError, match="Local model weight verification failed"):
        provider_adapters.call_local(
            "local:test",
            "hello",
            None,
            local_models={"test": model_file.as_posix()},
            resolve_model_path=lambda _model_key: model_file,
        )
