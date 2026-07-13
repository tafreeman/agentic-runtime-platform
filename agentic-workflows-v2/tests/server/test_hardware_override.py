"""Endpoint tests for /api/model-finder/profile-override (GET/PUT/DELETE).

Wire contract:

* ``GET``    -> 200 ``{"override": HardwareOverride|null}``
* ``PUT``    -> 200 ``{"profile": SystemProfile, "override": HardwareOverride}``
* ``DELETE`` -> 200 ``{"profile": SystemProfile, "override": null}``

All tests run against a tmp_path-scoped ``HARDWARE_OVERRIDE_PATH`` and clear
the ``get_system_profile`` lru_cache around each test. Overrides always pin
``accelerators`` explicitly so the live GPU/NPU probes never run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentic_v2.server.routes.model_finder import get_system_profile

# Deliberately absurd so a real machine can never coincide with the override.
_OVERRIDE_RAM_GB = 4096.0


@pytest.fixture(autouse=True)
def override_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate the override file per test and keep the profile cache honest."""
    path = tmp_path / "hardware_override.yaml"
    monkeypatch.setenv("HARDWARE_OVERRIDE_PATH", str(path))
    get_system_profile.cache_clear()
    yield path
    get_system_profile.cache_clear()


class TestGetProfileOverride:
    def test_returns_null_when_no_override_file(self, client) -> None:
        response = client.get("/api/model-finder/profile-override")

        assert response.status_code == 200
        assert response.json() == {"override": None}

    def test_echoes_persisted_override(self, client) -> None:
        put = client.put(
            "/api/model-finder/profile-override",
            json={"ram_gb": 64.0, "system_tops": 45.5, "accelerators": []},
        )
        assert put.status_code == 200

        response = client.get("/api/model-finder/profile-override")

        assert response.status_code == 200
        override = response.json()["override"]
        assert override["ram_gb"] == 64.0
        assert override["system_tops"] == 45.5
        assert override["accelerators"] == []
        # Fields never set stay null.
        assert override["cpu_name"] is None


class TestPutProfileOverride:
    def test_persists_and_recomputes_profile(self, client, override_path) -> None:
        body = {
            "ram_gb": _OVERRIDE_RAM_GB,
            "cpu_cores_logical": 24,
            "accelerators": [],
        }

        response = client.put("/api/model-finder/profile-override", json=body)

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["profile"]["ram_gb"] == _OVERRIDE_RAM_GB
        assert payload["profile"]["cpu_cores_logical"] == 24
        assert payload["override"]["ram_gb"] == _OVERRIDE_RAM_GB
        # None fields are dropped before persisting — YAML pins only the
        # values that were actually overridden.
        on_disk = yaml.safe_load(override_path.read_text(encoding="utf-8"))
        assert on_disk == {
            "ram_gb": _OVERRIDE_RAM_GB,
            "cpu_cores_logical": 24,
            "accelerators": [],
        }

    def test_profile_route_reflects_override_immediately(self, client) -> None:
        """PUT must cache_clear() — a stale lru_cache would serve old specs."""
        client.put(
            "/api/model-finder/profile-override",
            json={"ram_gb": _OVERRIDE_RAM_GB, "accelerators": []},
        )

        profile = client.get("/api/model-finder/profile")

        assert profile.status_code == 200
        assert profile.json()["ram_gb"] == _OVERRIDE_RAM_GB

    def test_boolean_system_tops_is_422(self, client, override_path) -> None:
        response = client.put(
            "/api/model-finder/profile-override",
            json={"system_tops": True, "accelerators": []},
        )

        assert response.status_code == 422
        assert not override_path.exists()

    def test_boolean_ram_gb_is_422(self, client, override_path) -> None:
        response = client.put(
            "/api/model-finder/profile-override",
            json={"ram_gb": True, "accelerators": []},
        )

        assert response.status_code == 422
        assert not override_path.exists()

    @pytest.mark.parametrize(
        "field",
        ["cpu_cores_logical", "cpu_cores_physical", "cpu_max_mhz", "ram_gb"],
    )
    def test_negative_numeric_override_is_422(
        self, client, override_path, field
    ) -> None:
        """The form's min="0" is client-side only; the server must reject too."""
        response = client.put(
            "/api/model-finder/profile-override",
            json={field: -4, "accelerators": []},
        )

        assert response.status_code == 422
        assert not override_path.exists()

    @pytest.mark.parametrize("field", ["cpu_cores_logical", "ram_gb"])
    def test_zero_core_or_ram_override_is_422(
        self, client, override_path, field
    ) -> None:
        """Zero cores/RAM is as corrupting as negative for fit scoring."""
        response = client.put(
            "/api/model-finder/profile-override",
            json={field: 0, "accelerators": []},
        )

        assert response.status_code == 422
        assert not override_path.exists()

    def test_negative_system_tops_is_422_but_zero_allowed(
        self, client, override_path
    ) -> None:
        """system_tops is a sum: exactly 0 means "no accelerators" and is legal."""
        rejected = client.put(
            "/api/model-finder/profile-override",
            json={"system_tops": -1, "accelerators": []},
        )
        assert rejected.status_code == 422
        assert not override_path.exists()

        accepted = client.put(
            "/api/model-finder/profile-override",
            json={"system_tops": 0, "accelerators": []},
        )
        assert accepted.status_code == 200, accepted.text

    def test_negative_accelerator_memory_or_tops_is_422(
        self, client, override_path
    ) -> None:
        for payload in (
            {"kind": "gpu", "name": "Bad GPU", "memory_gb": -8},
            {"kind": "npu", "name": "Bad NPU", "tops": -40},
        ):
            response = client.put(
                "/api/model-finder/profile-override",
                json={"accelerators": [payload]},
            )

            assert response.status_code == 422, payload
            assert not override_path.exists()

    def test_boolean_accelerator_memory_or_tops_is_422(
        self, client, override_path
    ) -> None:
        """Bool coerces to 1.0 without the guard, silently claiming hardware."""
        for payload in (
            {"kind": "gpu", "name": "Bool GPU", "memory_gb": True},
            {"kind": "npu", "name": "Bool NPU", "tops": True},
        ):
            response = client.put(
                "/api/model-finder/profile-override",
                json={"accelerators": [payload]},
            )

            assert response.status_code == 422, payload
            assert not override_path.exists()

    def test_accelerators_drive_system_tops_and_tier(self, client) -> None:
        body = {
            "accelerators": [
                {"kind": "gpu", "name": "Test GPU", "tops": 40, "memory_gb": 16}
            ]
        }

        response = client.put("/api/model-finder/profile-override", json=body)

        assert response.status_code == 200, response.text
        profile = response.json()["profile"]
        assert profile["system_tops"] == 40.0
        assert profile["performance_tier"] == "accelerated"


class TestDeleteProfileOverride:
    def test_clears_override_and_recomputes_profile(
        self, client, override_path
    ) -> None:
        client.put(
            "/api/model-finder/profile-override",
            json={"ram_gb": _OVERRIDE_RAM_GB, "accelerators": []},
        )
        assert override_path.exists()

        response = client.delete("/api/model-finder/profile-override")

        assert response.status_code == 200
        payload = response.json()
        assert payload["override"] is None
        assert payload["profile"]["ram_gb"] != _OVERRIDE_RAM_GB
        assert not override_path.exists()
        # GET agrees the override is gone.
        assert (
            client.get("/api/model-finder/profile-override").json()["override"] is None
        )

    def test_missing_file_is_tolerated(self, client, override_path) -> None:
        assert not override_path.exists()

        response = client.delete("/api/model-finder/profile-override")

        assert response.status_code == 200
        assert response.json()["override"] is None
