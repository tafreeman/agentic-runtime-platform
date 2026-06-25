"""Local model finder routes backed by host hardware profiling.

The endpoint intentionally works without privileged probes or network access. It
builds a conservative hardware profile from the local machine, derives a few
performance estimates, and ranks a curated open-model catalog against that
profile.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal

import yaml

logger = logging.getLogger(__name__)

# Machine-specific hardware override — gitignored, never committed.
# Set HARDWARE_OVERRIDE_PATH to point to a different file.
_DEFAULT_OVERRIDE = (
    Path(__file__).resolve().parent.parent.parent / "config" / "hardware_override.yaml"
)

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/model-finder", tags=["model-finder"])

QUANT_FORMAT_Q4_K_M: Final[str] = "GGUF Q4_K_M"
LICENSE_APACHE_2: Final[str] = "apache-2.0"
COMPAT_Q4: Final[str] = "Q4 compatible"

TaskCategory = Literal["general", "swe", "biomed", "physics", "math", "vision"]
SortField = Literal["downloads", "release_date", "likes", "forks", "fit"]


class Accelerator(BaseModel):
    kind: Literal["gpu", "npu"]
    name: str
    memory_gb: float | None = None
    vendor: str | None = None
    tops: float | None = None  # INT8 AI throughput in TOPS; None when unknown


class SystemProfile(BaseModel):
    os: str
    architecture: str
    cpu_name: str
    cpu_cores_logical: int
    cpu_cores_physical: int | None = None
    cpu_max_mhz: float | None = None
    ram_gb: float
    accelerators: list[Accelerator] = Field(default_factory=list)
    system_tops: float | None = None  # sum of all accelerator TOPS (INT8); None when unknown
    estimated_cinebench_r23_multi: int
    estimated_tokens_per_second_7b_q4: float
    performance_tier: Literal["entry", "mainstream", "workstation", "accelerated"]
    notes: list[str] = Field(default_factory=list)


class ModelCandidate(BaseModel):
    id: str
    name: str
    provider: str = "Hugging Face"
    categories: list[TaskCategory]
    downloads: int
    likes: int
    forks: int
    release_date: date
    parameters_b: float
    quantization: str
    min_ram_gb: float
    recommended_ram_gb: float
    min_vram_gb: float = 0
    context_tokens: int
    license: str
    url: str
    fit_score: int
    fit_reason: str
    runnable: bool


class RecommendationResponse(BaseModel):
    profile: SystemProfile
    models: list[ModelCandidate]
    sort_order: list[str]
    category: TaskCategory | Literal["all"]


class CatalogItem(BaseModel):
    id: str
    name: str
    categories: list[TaskCategory]
    downloads: int
    likes: int
    forks: int
    release_date: date
    parameters_b: float
    quantization: str
    min_ram_gb: float
    recommended_ram_gb: float
    min_vram_gb: float = 0
    context_tokens: int
    license: str
    url: str


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem(
        id="Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        name="Qwen2.5 Coder 7B Instruct",
        categories=["swe"],
        downloads=1_850_000,
        likes=2100,
        forks=180,
        release_date=date(2024, 9, 19),
        parameters_b=7.6,
        quantization=QUANT_FORMAT_Q4_K_M,
        min_ram_gb=8,
        recommended_ram_gb=16,
        context_tokens=32768,
        license=LICENSE_APACHE_2,
        url="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
    ),
    CatalogItem(
        id="meta-llama/Llama-3.2-3B-Instruct",
        name="Llama 3.2 3B Instruct",
        categories=["general", "swe"],
        downloads=5_400_000,
        likes=5600,
        forks=720,
        release_date=date(2024, 9, 25),
        parameters_b=3.2,
        quantization="BF16 / Q4 via runtimes",
        min_ram_gb=6,
        recommended_ram_gb=8,
        context_tokens=131072,
        license="llama3.2",
        url="https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct",
    ),
    CatalogItem(
        id="mistralai/Mistral-7B-Instruct-v0.3",
        name="Mistral 7B Instruct v0.3",
        categories=["general", "swe"],
        downloads=4_300_000,
        likes=7400,
        forks=880,
        release_date=date(2024, 5, 22),
        parameters_b=7.3,
        quantization=QUANT_FORMAT_Q4_K_M,
        min_ram_gb=8,
        recommended_ram_gb=16,
        context_tokens=32768,
        license=LICENSE_APACHE_2,
        url="https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3",
    ),
    CatalogItem(
        id="google/gemma-2-9b-it",
        name="Gemma 2 9B IT",
        categories=["general", "math"],
        downloads=3_900_000,
        likes=4300,
        forks=450,
        release_date=date(2024, 6, 27),
        parameters_b=9.2,
        quantization="Q4 / INT4",
        min_ram_gb=12,
        recommended_ram_gb=24,
        min_vram_gb=8,
        context_tokens=8192,
        license="gemma",
        url="https://huggingface.co/google/gemma-2-9b-it",
    ),
    CatalogItem(
        id="deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
        name="DeepSeek Coder V2 Lite Instruct",
        categories=["swe"],
        downloads=980_000,
        likes=1800,
        forks=210,
        release_date=date(2024, 6, 17),
        parameters_b=16,
        quantization=QUANT_FORMAT_Q4_K_M,
        min_ram_gb=16,
        recommended_ram_gb=32,
        min_vram_gb=10,
        context_tokens=163840,
        license="deepseek",
        url="https://huggingface.co/deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
    ),
    CatalogItem(
        id="microsoft/Phi-3.5-mini-instruct",
        name="Phi 3.5 Mini Instruct",
        categories=["general", "swe", "math"],
        downloads=2_700_000,
        likes=3100,
        forks=360,
        release_date=date(2024, 8, 20),
        parameters_b=3.8,
        quantization="ONNX / INT4",
        min_ram_gb=4,
        recommended_ram_gb=8,
        context_tokens=128000,
        license="mit",
        url="https://huggingface.co/microsoft/Phi-3.5-mini-instruct",
    ),
    CatalogItem(
        id="BioMistral/BioMistral-7B",
        name="BioMistral 7B",
        categories=["biomed"],
        downloads=420_000,
        likes=900,
        forks=95,
        release_date=date(2024, 1, 4),
        parameters_b=7.2,
        quantization=QUANT_FORMAT_Q4_K_M,
        min_ram_gb=8,
        recommended_ram_gb=16,
        context_tokens=8192,
        license=LICENSE_APACHE_2,
        url="https://huggingface.co/BioMistral/BioMistral-7B",
    ),
    CatalogItem(
        id="AdaptLLM/medicine-LLM",
        name="AdaptLLM Medicine 7B",
        categories=["biomed"],
        downloads=260_000,
        likes=520,
        forks=70,
        release_date=date(2024, 2, 2),
        parameters_b=7,
        quantization=COMPAT_Q4,
        min_ram_gb=8,
        recommended_ram_gb=16,
        context_tokens=4096,
        license=LICENSE_APACHE_2,
        url="https://huggingface.co/AdaptLLM/medicine-LLM",
    ),
    CatalogItem(
        id="NousResearch/Hermes-3-Llama-3.1-8B",
        name="Hermes 3 Llama 3.1 8B",
        categories=["general", "physics", "math"],
        downloads=1_100_000,
        likes=2500,
        forks=280,
        release_date=date(2024, 8, 15),
        parameters_b=8,
        quantization=QUANT_FORMAT_Q4_K_M,
        min_ram_gb=10,
        recommended_ram_gb=16,
        context_tokens=131072,
        license="llama3.1",
        url="https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B",
    ),
    CatalogItem(
        id="allenai/OLMo-2-1124-7B-Instruct",
        name="OLMo 2 7B Instruct",
        categories=["general", "physics"],
        downloads=600_000,
        likes=1400,
        forks=160,
        release_date=date(2024, 11, 20),
        parameters_b=7,
        quantization=COMPAT_Q4,
        min_ram_gb=8,
        recommended_ram_gb=16,
        context_tokens=4096,
        license=LICENSE_APACHE_2,
        url="https://huggingface.co/allenai/OLMo-2-1124-7B-Instruct",
    ),
    CatalogItem(
        id="llava-hf/llava-v1.6-mistral-7b-hf",
        name="LLaVA 1.6 Mistral 7B",
        categories=["vision", "general"],
        downloads=1_300_000,
        likes=2100,
        forks=320,
        release_date=date(2024, 1, 30),
        parameters_b=7.6,
        quantization=COMPAT_Q4,
        min_ram_gb=12,
        recommended_ram_gb=24,
        min_vram_gb=8,
        context_tokens=4096,
        license=LICENSE_APACHE_2,
        url="https://huggingface.co/llava-hf/llava-v1.6-mistral-7b-hf",
    ),
)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _cpu_name() -> str:
    cpuinfo = _read_text("/proc/cpuinfo")
    match = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, flags=re.MULTILINE)
    return match.group(1).strip() if match else platform.processor() or "unknown CPU"


def _ram_gb() -> float:
    meminfo = _read_text("/proc/meminfo")
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", meminfo, flags=re.MULTILINE)
    if match:
        return round(int(match.group(1)) / 1024 / 1024, 1)
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return round((pages * page_size) / 1024**3, 1)
        except (OSError, ValueError):
            pass
    return 0


def _cpu_max_mhz() -> float | None:
    cpuinfo = _read_text("/proc/cpuinfo")
    speeds = [
        float(value)
        for value in re.findall(
            r"^cpu MHz\s*:\s*([0-9.]+)$", cpuinfo, flags=re.MULTILINE
        )
    ]
    return round(max(speeds), 1) if speeds else None


def _run_probe(command: list[str]) -> str:
    if not shutil.which(command[0]):
        return ""
    try:
        return subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=2
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _accelerators() -> list[Accelerator]:
    accelerators: list[Accelerator] = []
    nvidia = _run_probe(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    for line in nvidia.splitlines():
        if not line.strip():
            continue
        name, _, memory = line.partition(",")
        try:
            memory_gb = round(float(memory.strip()) / 1024, 1)
        except ValueError:
            memory_gb = None
        accelerators.append(
            Accelerator(
                kind="gpu", name=name.strip(), memory_gb=memory_gb, vendor="NVIDIA"
            )
        )

    pci = _run_probe(["lspci"])
    for line in pci.splitlines():
        lower = line.lower()
        if "vga" in lower or "3d controller" in lower or "display" in lower:
            if "nvidia" not in lower:
                accelerators.append(
                    Accelerator(kind="gpu", name=line.split(": ", 1)[-1], vendor=None)
                )
        if "npu" in lower or "neural" in lower or "ai accelerator" in lower:
            accelerators.append(
                Accelerator(kind="npu", name=line.split(": ", 1)[-1], vendor=None)
            )
    return accelerators


def _load_hardware_override() -> dict[str, Any]:
    """Return the hardware override dict, or {} when none is configured."""
    path_env = os.environ.get("HARDWARE_OVERRIDE_PATH")
    override_path = Path(path_env) if path_env else _DEFAULT_OVERRIDE
    if not override_path.is_file():
        return {}
    try:
        data = yaml.safe_load(override_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load hardware override from %s: %s", override_path, exc)
        return {}


def _accelerators_from_override(raw: list[Any]) -> list[Accelerator]:
    """Parse accelerator dicts from the YAML override into typed objects."""
    result: list[Accelerator] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        name = entry.get("name")
        if kind not in ("gpu", "npu") or not isinstance(name, str):
            continue
        tops_raw = entry.get("tops")
        result.append(
            Accelerator(
                kind=kind,
                name=name,
                memory_gb=entry.get("memory_gb"),
                vendor=entry.get("vendor"),
                tops=float(tops_raw) if tops_raw is not None else None,
            )
        )
    return result


@lru_cache(maxsize=1)
def get_system_profile() -> SystemProfile:
    override = _load_hardware_override()
    logical = int(override.get("cpu_cores_logical", 0)) or os.cpu_count() or 1
    ram = float(override.get("ram_gb", 0)) or _ram_gb()
    max_mhz = float(override.get("cpu_max_mhz", 0)) or _cpu_max_mhz()
    accelerators = (
        _accelerators_from_override(override["accelerators"])
        if "accelerators" in override
        else _accelerators()
    )
    gpu_memory = max(
        (a.memory_gb or 0 for a in accelerators if a.kind == "gpu"), default=0
    )
    npu_tops = sum(a.tops or 0 for a in accelerators if a.kind == "npu")
    all_tops = sum(a.tops or 0 for a in accelerators)
    # system_tops override lets the YAML express the true total (incl. CPU VNNI/TOPS
    # that aren't modelled as an Accelerator entry).
    system_tops_raw = override.get("system_tops")
    system_tops: float | None = (
        float(system_tops_raw) if system_tops_raw is not None
        else (round(all_tops, 1) if all_tops > 0 else None)
    )
    cinebench = int(logical * ((max_mhz or 2500) / 1000) * 620)
    # NPU TOPS contribute ~0.15 t/s per TOPS for INT4/INT8 quantized 7B models.
    tps = round(
        max(1.5, (logical * ((max_mhz or 2500) / 2500) * 0.9) + (gpu_memory * 1.7) + (npu_tops * 0.15)), 1
    )
    if gpu_memory >= 8 or any(a.kind == "npu" for a in accelerators):
        tier = "accelerated"
    elif ram >= 32 and logical >= 12:
        tier = "workstation"
    elif ram >= 16 and logical >= 6:
        tier = "mainstream"
    else:
        tier = "entry"
    notes = [
        "Cinebench and token/sec values are estimates derived from visible CPU/GPU specs."
    ]
    if not accelerators:
        notes.append(
            "No GPU/NPU probe was detected; recommendations assume CPU execution."
        )
    return SystemProfile(
        os=platform.platform(),
        architecture=platform.machine(),
        cpu_name=str(override.get("cpu_name") or _cpu_name()),
        cpu_cores_logical=logical,
        cpu_cores_physical=int(override["cpu_cores_physical"])
        if "cpu_cores_physical" in override
        else None,
        cpu_max_mhz=max_mhz,
        ram_gb=ram,
        accelerators=accelerators,
        system_tops=system_tops,
        estimated_cinebench_r23_multi=cinebench,
        estimated_tokens_per_second_7b_q4=tps,
        performance_tier=tier,
        notes=notes,
    )


def score_model(item: CatalogItem, profile: SystemProfile) -> tuple[int, bool, str]:
    gpu_memory = max(
        (a.memory_gb or 0 for a in profile.accelerators if a.kind == "gpu"), default=0
    )
    runnable = profile.ram_gb >= item.min_ram_gb and (
        item.min_vram_gb == 0
        or gpu_memory >= item.min_vram_gb
        or profile.ram_gb >= item.recommended_ram_gb
    )
    score = 35 if runnable else 5
    if profile.ram_gb >= item.recommended_ram_gb:
        score += 30
    else:
        score += max(0, int((profile.ram_gb / item.recommended_ram_gb) * 25))
    if item.min_vram_gb and gpu_memory >= item.min_vram_gb:
        score += 20
    elif not item.min_vram_gb:
        score += 10
    score += min(15, int(profile.estimated_tokens_per_second_7b_q4 / 2))
    reason = (
        "good local fit"
        if runnable
        else "below minimum RAM/VRAM; try a smaller quantization"
    )
    return min(score, 100), runnable, reason


def sorted_candidates(
    profile: SystemProfile, category: str, sort_by: SortField
) -> list[ModelCandidate]:
    items = [
        item for item in CATALOG if category == "all" or category in item.categories
    ]
    candidates: list[ModelCandidate] = []
    for item in items:
        fit_score, runnable, fit_reason = score_model(item, profile)
        candidates.append(
            ModelCandidate(
                **item.model_dump(),
                fit_score=fit_score,
                runnable=runnable,
                fit_reason=fit_reason,
            )
        )

    def key(model: ModelCandidate):
        primary = model.fit_score if sort_by == "fit" else getattr(model, sort_by)
        if sort_by == "release_date":
            primary = model.release_date.toordinal()
        return (
            primary,
            model.downloads,
            model.release_date.toordinal(),
            model.likes,
            model.forks,
            model.fit_score,
        )

    return sorted(candidates, key=key, reverse=True)


@router.get("/profile")
def profile() -> SystemProfile:
    """Return the detected local system resource profile."""
    return get_system_profile()


@router.get("/recommendations")
def recommendations(
    category: Annotated[TaskCategory | Literal["all"], Query()] = "all",
    sort_by: Annotated[SortField, Query()] = "downloads",
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> RecommendationResponse:
    """Return hardware-aware model recommendations."""
    profile = get_system_profile()
    return RecommendationResponse(
        profile=profile,
        models=sorted_candidates(profile, category, sort_by)[:limit],
        sort_order=[sort_by, "downloads", "release_date", "likes", "forks", "fit"],
        category=category,
    )
