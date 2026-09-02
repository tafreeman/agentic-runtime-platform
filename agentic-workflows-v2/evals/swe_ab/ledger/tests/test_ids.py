"""Tests for ledger.ids: determinism, order-insensitivity, distinctness."""

from __future__ import annotations

import hashlib
from typing import Any

from ledger.ids import (
    arm_config_id,
    canonical_json,
    content_id,
    digest_bytes,
    grader_id,
    image_digest_set,
    image_id,
    model_id,
    prompt_id,
    substrate_id,
    task_id,
    task_set_id,
    workflow_id,
)

# ---------------------------------------------------------------------
# canonical_json / content_id
# ---------------------------------------------------------------------


def test_canonical_json_is_deterministic_across_key_order() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b


def test_canonical_json_matches_expected_shape() -> None:
    assert canonical_json({"a": 1, "b": "x"}) == '{"a":1,"b":"x"}'


def test_content_id_prefix() -> None:
    result = content_id("xyz", {"a": 1})
    assert result.startswith("xyz_")


def test_content_id_hash_length() -> None:
    result = content_id("xyz", {"a": 1})
    digest_part = result.removeprefix("xyz_")
    assert len(digest_part) == 16


def test_content_id_deterministic_across_processes_equivalent() -> None:
    # Simulate "two calls" by recomputing independently from the same
    # logical payload; content_id must not depend on any process-local
    # state (e.g. PYTHONHASHSEED-randomized dict/set iteration).
    payload = {"provider": "acme", "wire_ref": "acme/x-1", "temp": 0.2}
    first = content_id("mdl", payload)
    second = content_id("mdl", dict(reversed(list(payload.items()))))
    assert first == second


def test_content_id_matches_manual_sha256() -> None:
    payload = {"a": 1, "b": 2}
    expected_digest = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    assert content_id("pre", payload) == f"pre_{expected_digest[:16]}"


def test_content_id_different_inputs_differ() -> None:
    assert content_id("mdl", {"a": 1}) != content_id("mdl", {"a": 2})


def test_content_id_different_prefix_differs_even_with_same_payload() -> None:
    payload = {"a": 1}
    assert content_id("mdl", payload) != content_id("prm", payload)


# ---------------------------------------------------------------------
# digest_bytes
# ---------------------------------------------------------------------


def test_digest_bytes_format() -> None:
    result = digest_bytes(b"hello world")
    assert result.startswith("sha256:")
    assert result == "sha256:" + hashlib.sha256(b"hello world").hexdigest()


def test_digest_bytes_deterministic() -> None:
    assert digest_bytes(b"same") == digest_bytes(b"same")


def test_digest_bytes_distinct_inputs_differ() -> None:
    assert digest_bytes(b"one") != digest_bytes(b"two")


# ---------------------------------------------------------------------
# image_digest_set: order- and duplicate-insensitive
# ---------------------------------------------------------------------


def test_image_digest_set_order_insensitive() -> None:
    digests = ["sha256:bbb", "sha256:aaa", "sha256:ccc"]
    assert image_digest_set(digests) == image_digest_set(list(reversed(digests)))


def test_image_digest_set_duplicate_insensitive() -> None:
    digests = ["sha256:aaa", "sha256:bbb"]
    duped = ["sha256:aaa", "sha256:bbb", "sha256:aaa", "sha256:bbb"]
    assert image_digest_set(digests) == image_digest_set(duped)


def test_image_digest_set_distinct_sets_differ() -> None:
    assert image_digest_set(["sha256:aaa"]) != image_digest_set(["sha256:bbb"])


def test_image_digest_set_is_bare_hex_prefix() -> None:
    result = image_digest_set(["sha256:aaa", "sha256:bbb"])
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------
# Thin id wrappers: determinism, key-order insensitivity (via kwargs,
# which are inherently order-insensitive), prefix correctness, and
# distinctness on differing inputs.
# ---------------------------------------------------------------------


def test_model_id_prefix_and_determinism() -> None:
    kwargs: dict[str, Any] = dict(
        provider="acme",
        wire_ref="acme/x-1",
        family="x",
        params_b=7.0,
        quantization=None,
        context_window=8192,
        serving_mode="hosted",
    )
    first = model_id(**kwargs)
    second = model_id(**kwargs)
    assert first == second
    assert first.startswith("mdl_")


def test_model_id_distinct_on_differing_field() -> None:
    base: dict[str, Any] = dict(
        provider="acme",
        wire_ref="acme/x-1",
        family="x",
        params_b=7.0,
        quantization=None,
        context_window=8192,
        serving_mode="hosted",
    )
    other = dict(base, serving_mode="local_gpu")
    assert model_id(**base) != model_id(**other)


def test_prompt_id_prefix() -> None:
    result = prompt_id(role="system", text_digest="sha256:abc")
    assert result.startswith("prm_")


def test_workflow_id_prefix_and_prompt_id_order_insensitive() -> None:
    a = workflow_id(name="wf", yaml_digest="sha256:abc", prompt_ids=["p2", "p1"])
    b = workflow_id(name="wf", yaml_digest="sha256:abc", prompt_ids=["p1", "p2"])
    assert a == b
    assert a.startswith("wfl_")


def test_workflow_id_distinct_prompt_sets_differ() -> None:
    a = workflow_id(name="wf", yaml_digest="sha256:abc", prompt_ids=["p1"])
    b = workflow_id(name="wf", yaml_digest="sha256:abc", prompt_ids=["p1", "p2"])
    assert a != b


def test_grader_id_prefix() -> None:
    result = grader_id(
        name="exact_match",
        kind="deterministic",
        module_digest="sha256:abc",
        rubric_id=None,
    )
    assert result.startswith("grd_")


def test_image_id_prefix_and_determinism() -> None:
    a = image_id(repo="ghcr.io/acme/x", digest="sha256:abc")
    b = image_id(repo="ghcr.io/acme/x", digest="sha256:abc")
    assert a == b
    assert a.startswith("img_")


def test_task_set_id_prefix() -> None:
    result = task_set_id(name="swebench", source="hf", revision="v1", filter_expr=None)
    assert result.startswith("tsk_")


def test_task_id_prefix_and_distinctness() -> None:
    a = task_id(task_set_id="tsk_x", instance_id="repo__1")
    b = task_id(task_set_id="tsk_x", instance_id="repo__2")
    assert a.startswith("tas_")
    assert a != b


def test_substrate_id_prefix() -> None:
    result = substrate_id(
        task_set_id="tsk_x",
        harness_version="1.0",
        runtime_digest="sha256:abc",
        evalkit_version="0.3.0",
        grader_id="grd_x",
        image_digest_set="deadbeefdeadbeef",
    )
    assert result.startswith("sub_")


def test_arm_config_id_prefix_and_stop_sequences_order_insensitive() -> None:
    kwargs: dict[str, Any] = dict(
        model_id="mdl_x",
        temperature=0.2,
        top_p=1.0,
        top_k=None,
        max_tokens=4096,
        seed=None,
        context_window_used=8192,
        workflow_id="wfl_x",
        retrieval_mode="oracle",
        tool_policy=None,
    )
    a = arm_config_id(stop_sequences=["</s>", "STOP"], **kwargs)
    b = arm_config_id(stop_sequences=["STOP", "</s>"], **kwargs)
    assert a == b
    assert a.startswith("arm_")


def test_arm_config_id_distinct_on_temperature() -> None:
    kwargs: dict[str, Any] = dict(
        model_id="mdl_x",
        top_p=1.0,
        top_k=None,
        max_tokens=4096,
        seed=None,
        stop_sequences=(),
        context_window_used=8192,
        workflow_id="wfl_x",
        retrieval_mode="oracle",
        tool_policy=None,
    )
    a = arm_config_id(temperature=0.2, **kwargs)
    b = arm_config_id(temperature=0.7, **kwargs)
    assert a != b
