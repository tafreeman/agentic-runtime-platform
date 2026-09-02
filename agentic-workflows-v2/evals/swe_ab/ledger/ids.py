"""Deterministic, content-addressed identifiers for ledger entities.

Every id is derived from the fields that define that entity's identity: the
same fields always produce the same id, regardless of process, machine, or
the key order in which the fields were supplied. This makes ids safe to
compute independently in multiple places (e.g. a writer and a reader) and
guarantees natural deduplication — two logically identical entities collide
on the same row instead of being inserted twice.

Standard library only. Do not add third-party imports here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "canonical_json",
    "content_id",
    "digest_bytes",
    "image_digest_set",
    "model_id",
    "prompt_id",
    "workflow_id",
    "grader_id",
    "image_id",
    "task_set_id",
    "task_id",
    "substrate_id",
    "arm_config_id",
]


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Render `payload` as a canonical JSON string.

    Sorted keys and fixed separators make the output insensitive to the
    dict's insertion order; `default=str` gives a stable, if lossy,
    fallback for non-JSON-native values (e.g. tuples already convert to
    lists automatically, but anything more exotic falls back to `str`).
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def content_id(prefix: str, payload: Mapping[str, Any]) -> str:
    """Return a stable `<prefix>_<16-hex-digest>` id for `payload`."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def digest_bytes(data: bytes) -> str:
    """Return a `sha256:<hex>` digest string for raw bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def image_digest_set(digests: Iterable[str]) -> str:
    """Return an order- and duplicate-insensitive digest over `digests`.

    Used to fold the set of container image digests that make up a
    substrate into one stable, comparable value. The input is sorted and
    deduplicated before hashing, so the result depends only on the set of
    distinct digest strings supplied, not their order or multiplicity.
    """
    unique_sorted = sorted(set(digests))
    joined = "\n".join(unique_sorted)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def model_id(
    *,
    provider: str,
    wire_ref: str,
    family: str,
    params_b: float | None,
    quantization: str | None,
    context_window: int | None,
    serving_mode: str,
) -> str:
    return content_id(
        "mdl",
        {
            "provider": provider,
            "wire_ref": wire_ref,
            "family": family,
            "params_b": params_b,
            "quantization": quantization,
            "context_window": context_window,
            "serving_mode": serving_mode,
        },
    )


def prompt_id(*, role: str, text_digest: str) -> str:
    return content_id("prm", {"role": role, "text_digest": text_digest})


def workflow_id(
    *,
    name: str,
    yaml_digest: str,
    prompt_ids: Sequence[str],
) -> str:
    return content_id(
        "wfl",
        {
            "name": name,
            "yaml_digest": yaml_digest,
            "prompt_ids": tuple(sorted(prompt_ids)),
        },
    )


def grader_id(
    *,
    name: str,
    kind: str,
    module_digest: str,
    rubric_id: str | None,
) -> str:
    return content_id(
        "grd",
        {
            "name": name,
            "kind": kind,
            "module_digest": module_digest,
            "rubric_id": rubric_id,
        },
    )


def image_id(*, repo: str, digest: str) -> str:
    return content_id("img", {"repo": repo, "digest": digest})


def task_set_id(
    *,
    name: str,
    source: str,
    revision: str,
    filter_expr: str | None,
) -> str:
    return content_id(
        "tsk",
        {
            "name": name,
            "source": source,
            "revision": revision,
            "filter_expr": filter_expr,
        },
    )


def task_id(*, task_set_id: str, instance_id: str) -> str:
    return content_id(
        "tas",
        {"task_set_id": task_set_id, "instance_id": instance_id},
    )


def substrate_id(
    *,
    task_set_id: str,
    harness_version: str,
    runtime_digest: str,
    evalkit_version: str,
    grader_id: str,
    image_digest_set: str,
) -> str:
    return content_id(
        "sub",
        {
            "task_set_id": task_set_id,
            "harness_version": harness_version,
            "runtime_digest": runtime_digest,
            "evalkit_version": evalkit_version,
            "grader_id": grader_id,
            "image_digest_set": image_digest_set,
        },
    )


def arm_config_id(
    *,
    model_id: str,
    temperature: float | None,
    top_p: float | None,
    top_k: int | None,
    max_tokens: int | None,
    seed: int | None,
    stop_sequences: Sequence[str],
    context_window_used: int | None,
    workflow_id: str,
    retrieval_mode: str,
    tool_policy: str | None,
) -> str:
    return content_id(
        "arm",
        {
            "model_id": model_id,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_tokens": max_tokens,
            "seed": seed,
            "stop_sequences": tuple(sorted(stop_sequences)),
            "context_window_used": context_window_used,
            "workflow_id": workflow_id,
            "retrieval_mode": retrieval_mode,
            "tool_policy": tool_policy,
        },
    )
