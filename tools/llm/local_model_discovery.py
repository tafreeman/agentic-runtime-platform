"""Model discovery and resolution utilities for local ONNX models.

Provides functions to locate ONNX model directories under the AI Gallery
cache and query their availability without loading them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Default model locations.
# Keep these portable: avoid hard-coded user paths.
_AI_GALLERY_ROOT = Path.home() / ".cache" / "aigallery"

# Known AI Gallery directories keyed by short model names.
# NOTE: These are directory names, not the final ONNX compute subfolder.
_MODEL_DIRS = {
    "phi4": ["microsoft--Phi-4-mini-instruct-onnx"],
    "phi4mini": ["microsoft--Phi-4-mini-instruct-onnx"],
    "phi3": ["microsoft--Phi-3-mini-4k-instruct-onnx"],
    "phi3.5": ["microsoft--Phi-3.5-mini-instruct-onnx"],
    "mistral": ["microsoft--mistral-7b-instruct-v0.2-ONNX"],
    "mistral-7b": ["microsoft--mistral-7b-instruct-v0.2-ONNX"],
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float conversion.

    Local model outputs occasionally include `null` / missing numeric fields.
    Treat those as `default` instead of raising.
    """
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _find_onnx_model_dir(base: Path) -> Path | None:
    """Return the first directory under base that looks like an ONNX model folder."""
    if not base.exists() or not base.is_dir():
        return None

    # Heuristic: prefer folders containing *.onnx; often nested under main/**/cpu_* or directml.
    for d in base.rglob("*"):
        if not d.is_dir():
            continue
        try:
            if any(d.glob("*.onnx")):
                return d
        except OSError:
            continue

    return None


def _resolve_model_path(model_key: str | None) -> Path | None:
    """Resolve a model key to a concrete ONNX folder path, if available."""
    if not _AI_GALLERY_ROOT.exists():
        return None

    if model_key:
        key = model_key.strip().lower()
        candidates = _MODEL_DIRS.get(key, [])
        for dirname in candidates:
            base = _AI_GALLERY_ROOT / dirname
            p = _find_onnx_model_dir(base)
            if p:
                return p

    # Fallback: first available known model (in a stable order)
    for key in ["phi4mini", "phi3.5", "phi3", "mistral"]:
        for dirname in _MODEL_DIRS.get(key, []):
            base = _AI_GALLERY_ROOT / dirname
            p = _find_onnx_model_dir(base)
            if p:
                return p

    return None


def check_model_available() -> bool:
    """Check if a local model is available."""
    return _resolve_model_path(None) is not None


def get_model_info() -> dict[str, Any]:
    """Get information about available local models."""
    info: dict[str, Any] = {
        "available": False,
        "paths_checked": [str(_AI_GALLERY_ROOT)],
        "found_path": None,
        "onnxruntime_genai_installed": False,
    }

    # Check for onnxruntime-genai
    try:
        import onnxruntime_genai

        info["onnxruntime_genai_installed"] = True
        info["onnxruntime_genai_version"] = onnxruntime_genai.__version__
    except ImportError:
        pass

    # Check for model
    found = _resolve_model_path(None)
    if found:
        info["available"] = True
        info["found_path"] = str(found)
        try:
            model_files = list(found.glob("*.onnx"))
            info["model_files"] = [f.name for f in model_files]
        except OSError:
            info["model_files"] = []

    return info
