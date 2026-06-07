"""On-demand benchmark data loader with disk caching.

Fetches task data from HuggingFace, GitHub, or local JSON files,
normalizes every item into a :class:`BenchmarkTask` dataclass, and
maintains a SHA-256-keyed JSON cache with configurable TTL.

Public API:
    load_benchmark: Load (and cache) a list of tasks.
    fetch_task: Retrieve a single task by ID.
    clear_cache: Remove cached benchmark data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .datasets import BENCHMARK_DEFINITIONS, BenchmarkDefinition, DataSource
from .registry import BenchmarkConfig

logger = logging.getLogger(__name__)

# =============================================================================
# TASK DATA STRUCTURE
# =============================================================================


@dataclass
class BenchmarkTask:
    """A single benchmark task in a provider-agnostic normalized form.

    Regardless of the upstream source (HuggingFace, GitHub, local JSON),
    every task is projected into this common schema so that runners and
    evaluators can operate uniformly.

    Attributes:
        task_id: Unique identifier within the benchmark.
        benchmark_id: Parent benchmark (e.g. ``"humaneval"``).
        prompt: Primary task description / problem statement.
        instruction: Supplementary instructions for the solver.
        repo: Repository name (SWE-bench tasks).
        base_commit: Starting commit hash (SWE-bench tasks).
        issue_text: Full GitHub issue body (SWE-bench tasks).
        hints: Optional hints provided with the task.
        expected_output: Reference solution, if available.
        test_cases: List of test-case dicts (format varies by benchmark).
        golden_patch: Gold-standard patch (SWE-bench tasks).
        difficulty: Difficulty label (e.g. ``"easy"``, ``"hard"``).
        tags: Free-form tags for filtering.
        language: Primary programming language.
        evaluation_script: Script path for automated evaluation.
        pass_criteria: Structured pass/fail criteria dict.
    """

    # Identification
    task_id: str  # Unique ID within benchmark
    benchmark_id: str  # Which benchmark this is from

    # Task description
    prompt: str  # The task prompt/description
    instruction: str = ""  # Additional instructions

    # Context (for SWE-bench style)
    repo: str | None = None  # Repository name
    base_commit: str | None = None  # Starting commit
    issue_text: str | None = None  # GitHub issue text
    hints: str | None = None  # Any hints provided

    # Expected output
    expected_output: str | None = None  # Expected solution (if available)
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    golden_patch: str | None = None  # Gold patch for SWE-bench

    # Metadata
    difficulty: str | None = None
    tags: list[str] = field(default_factory=list)
    language: str = "python"

    # Evaluation
    evaluation_script: str | None = None  # Script to run for eval
    pass_criteria: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "benchmark_id": self.benchmark_id,
            "prompt": self.prompt,
            "instruction": self.instruction,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "issue_text": self.issue_text,
            "hints": self.hints,
            "expected_output": self.expected_output,
            "test_cases": self.test_cases,
            "golden_patch": self.golden_patch,
            "difficulty": self.difficulty,
            "tags": self.tags,
            "language": self.language,
        }


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

CACHE_DIR = Path(__file__).parent / ".cache"


def get_cache_key(benchmark_id: str, task_id: str | None = None) -> str:
    """Generate cache key for a benchmark or task."""
    key = f"{benchmark_id}:{task_id or 'all'}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def get_cache_path(benchmark_id: str, task_id: str | None = None) -> Path:
    """Get cache file path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{get_cache_key(benchmark_id, task_id)}.json"


def is_cache_valid(cache_path: Path, ttl_hours: int = 24) -> bool:
    """Check if cache is still valid."""
    if not cache_path.exists():
        return False

    mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
    return datetime.now() - mtime < timedelta(hours=ttl_hours)


def save_to_cache(data: Any, benchmark_id: str, task_id: str | None = None) -> None:
    """Save data to cache."""
    cache_path = get_cache_path(benchmark_id, task_id)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "cached_at": datetime.now().isoformat(),
                "benchmark_id": benchmark_id,
                "task_id": task_id,
                "data": data,
            },
            f,
            indent=2,
        )


def load_from_cache(benchmark_id: str, task_id: str | None = None) -> Any | None:
    """Load data from cache."""
    cache_path = get_cache_path(benchmark_id, task_id)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
            return cached.get("data")
    except (json.JSONDecodeError, KeyError):
        return None


# =============================================================================
# DATA SOURCE LOADERS
# =============================================================================


_DATASET_VIEWER_BASE = "https://datasets-server.huggingface.co"
_DATASET_VIEWER_MAX_ROWS = 100  # API hard cap per request


def _fetch_via_dataset_viewer(
    dataset_id: str,
    config: str | None,
    split: str,
    offset: int,
    length: int,
) -> list[dict[str, Any]]:
    """Fetch rows from the HuggingFace Dataset Viewer REST API.

    No extra Python packages required — uses stdlib urllib only.
    Docs: https://huggingface.co/docs/dataset-viewer
    """
    params: dict[str, str] = {
        "dataset": dataset_id,
        "split": split,
        "offset": str(offset),
        "length": str(min(length, _DATASET_VIEWER_MAX_ROWS)),
    }
    if config:
        params["config"] = config

    url = f"{_DATASET_VIEWER_BASE}/rows?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "agentic-runtime-platform/1.0"},
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return [entry["row"] for entry in body.get("rows", [])]


def _fetch_via_huggingface_hub(
    dataset_id: str,
    config: str | None,
    split: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch rows using the huggingface_hub library (already a project dep).

    Docs: https://huggingface.co/docs/huggingface_hub/index
    """
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    config_part = config or "default"
    parquet_path = f"{config_part}/{split}/0000.parquet"
    local = hf_hub_download(
        repo_id=dataset_id,
        filename=parquet_path,
        repo_type="dataset",
    )
    table = pq.read_table(local)
    if offset >= table.num_rows:
        return []
    return table.slice(offset, min(limit, table.num_rows - offset)).to_pylist()


def _load_from_huggingface_datasets_lib(
    benchmark: BenchmarkDefinition,
    limit: int | None,
    offset: int,
) -> list[dict[str, Any]]:
    """Last-resort loader using the optional heavy 'datasets' library."""
    try:
        import datasets
    except ImportError:
        logger.warning(
            "No HuggingFace loader available for %s. "
            "Install huggingface_hub (already in project deps) or datasets.",
            benchmark.source_url,
        )
        return []

    cfg = benchmark.source_config
    split = cfg.get("split", "test")
    try:
        ds = datasets.load_dataset(benchmark.source_url, split=split)
        if offset:
            ds = ds.select(range(offset, len(ds)))
        if limit:
            ds = ds.select(range(min(limit, len(ds))))
        return list(ds)
    except Exception as exc:
        logger.error("datasets library also failed for %s: %s", benchmark.source_url, exc)
        return []


def _load_from_huggingface(
    benchmark: BenchmarkDefinition,
    limit: int | None = None,
    offset: int = 0,
) -> list[BenchmarkTask]:
    """Load tasks from HuggingFace.

    Strategy (in order):
    1. Dataset Viewer REST API — no extra deps, works for any public dataset.
    2. huggingface_hub + pyarrow — already declared as a project dependency.
    3. datasets library — heavy optional dep, used only if already installed.
    """
    cfg = benchmark.source_config
    split = cfg.get("split", "test")
    hf_config: str | None = cfg.get("config") or cfg.get("subset") or None
    want = limit or 100

    logger.info("Loading from HuggingFace: %s", benchmark.source_url)

    rows: list[dict[str, Any]] = []

    # --- tier 1: Dataset Viewer REST API (zero extra deps) ---
    try:
        rows = _fetch_via_dataset_viewer(
            benchmark.source_url, hf_config, split, offset, want
        )
        logger.debug("Dataset Viewer returned %d rows", len(rows))
    except Exception as exc_viewer:
        logger.debug("Dataset Viewer unavailable (%s), trying huggingface_hub", exc_viewer)

        # --- tier 2: huggingface_hub (already in project deps) ---
        try:
            rows = _fetch_via_huggingface_hub(
                benchmark.source_url, hf_config, split, offset, want
            )
            logger.debug("huggingface_hub returned %d rows", len(rows))
        except Exception as exc_hub:
            logger.debug("huggingface_hub failed (%s), falling back to datasets", exc_hub)
            rows = _load_from_huggingface_datasets_lib(benchmark, limit, offset)
            if not rows:
                return []

    tasks: list[BenchmarkTask] = []
    for idx, item in enumerate(rows):
        task = _transform_huggingface_item(item, benchmark, offset + idx)
        if task:
            tasks.append(task)

    return tasks


def _transform_huggingface_item(
    item: dict[str, Any],
    benchmark: BenchmarkDefinition,
    idx: int,
) -> BenchmarkTask | None:
    """Transform a HuggingFace dataset item to BenchmarkTask."""

    # SWE-bench format
    if benchmark.id.startswith("swe-bench"):
        return BenchmarkTask(
            task_id=item.get("instance_id", f"task_{idx}"),
            benchmark_id=benchmark.id,
            prompt=item.get("problem_statement", ""),
            instruction="Fix the issue described above by modifying the repository.",
            repo=item.get("repo", ""),
            base_commit=item.get("base_commit", ""),
            issue_text=item.get("problem_statement", ""),
            hints=item.get("hints_text", ""),
            golden_patch=item.get("patch", ""),
            test_cases=[{"test_patch": item.get("test_patch", "")}],
            difficulty=item.get("difficulty"),
            language="python",
        )

    # HumanEval format
    elif benchmark.id.startswith("humaneval"):
        return BenchmarkTask(
            task_id=item.get("task_id", f"HumanEval/{idx}"),
            benchmark_id=benchmark.id,
            prompt=item.get("prompt", ""),
            instruction="Complete the function implementation.",
            expected_output=item.get("canonical_solution", ""),
            test_cases=[
                {
                    "test": item.get("test", ""),
                    "entry_point": item.get("entry_point", ""),
                }
            ],
            language="python",
        )

    # MBPP format
    elif benchmark.id.startswith("mbpp"):
        return BenchmarkTask(
            task_id=str(item.get("task_id", idx)),
            benchmark_id=benchmark.id,
            prompt=item.get("text", item.get("prompt", "")),
            instruction="Write a Python function to solve the problem.",
            expected_output=item.get("code", ""),
            test_cases=[
                {
                    "test_list": item.get("test_list", []),
                    "test_setup_code": item.get("test_setup_code", ""),
                }
            ],
            language="python",
        )

    # Generic format
    else:
        return BenchmarkTask(
            task_id=item.get("id", f"task_{idx}"),
            benchmark_id=benchmark.id,
            prompt=item.get("prompt", item.get("text", item.get("instruction", ""))),
            expected_output=item.get("solution", item.get("output", "")),
            language="python",
        )


def _load_from_github(
    benchmark: BenchmarkDefinition,
    limit: int | None = None,
    offset: int = 0,
) -> list[BenchmarkTask]:
    """Load tasks from a GitHub repository."""
    config = benchmark.source_config
    branch = config.get("branch", "main")
    tasks_path = config.get("tasks_path", "tasks/")

    # Construct API URL
    api_url = (
        f"https://api.github.com/repos/{benchmark.source_url}/contents/{tasks_path}"
    )
    if branch != "main":
        api_url += f"?ref={branch}"

    logger.info("Loading from GitHub: %s", benchmark.source_url)

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "prompts-library/1.0",
                "Accept": "application/vnd.github.v3+json",
            },
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            files = json.loads(response.read().decode("utf-8"))

        # Filter JSON files
        task_files = [f for f in files if f["name"].endswith(".json")]

        # Apply offset and limit
        task_files = task_files[offset:]
        if limit:
            task_files = task_files[:limit]

        # Fetch each task
        tasks = []
        for file_info in task_files:
            task_data = _fetch_github_file(file_info["download_url"])
            if task_data:
                task = BenchmarkTask(
                    task_id=task_data.get("id", file_info["name"].replace(".json", "")),
                    benchmark_id=benchmark.id,
                    prompt=task_data.get("prompt", task_data.get("description", "")),
                    instruction=task_data.get("instruction", ""),
                    expected_output=task_data.get("solution", ""),
                    test_cases=task_data.get("tests", []),
                    difficulty=task_data.get("difficulty"),
                    tags=task_data.get("tags", []),
                    language=task_data.get("language", "python"),
                )
                tasks.append(task)

        return tasks

    except Exception as e:
        logger.error("Failed to load from GitHub: %s", e)
        return []


def _fetch_github_file(url: str) -> dict[str, Any] | None:
    """Fetch a single file from GitHub."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "prompts-library/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _load_from_local(
    benchmark: BenchmarkDefinition,
    limit: int | None = None,
    offset: int = 0,
) -> list[BenchmarkTask]:
    """Load tasks from local JSON files."""
    config = benchmark.source_config
    pattern = config.get("pattern", "*.json")

    # Resolve path relative to benchmarks directory
    base_path = Path(__file__).parent.parent / benchmark.source_url

    logger.info("Loading from local: %s", base_path)

    if not base_path.exists():
        logger.error("Path not found: %s", base_path)
        return []

    # Find matching files
    task_files = sorted(base_path.glob(pattern))

    # Apply offset and limit
    task_files = task_files[offset:]
    if limit:
        task_files = task_files[:limit]

    tasks = []
    for file_path in task_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                task_data = json.load(f)

            task = BenchmarkTask(
                task_id=task_data.get("task_id", file_path.stem),
                benchmark_id=benchmark.id,
                prompt=task_data.get("description", task_data.get("prompt", "")),
                instruction=task_data.get("instruction", "Complete the task."),
                expected_output=task_data.get("solution", ""),
                test_cases=task_data.get("test_cases", []),
                difficulty=task_data.get("difficulty"),
                tags=task_data.get("tags", []),
                language=task_data.get("language", "python"),
                pass_criteria={
                    "required_components": task_data.get("required_components", []),
                    "required_patterns": task_data.get("required_patterns", []),
                    "key_decisions": task_data.get("key_decisions", []),
                    "api_endpoints": task_data.get("api_endpoints", []),
                    "database_tables": task_data.get("database_tables", []),
                },
            )
            tasks.append(task)

        except Exception as e:
            logger.error("Error loading %s: %s", file_path, e)

    return tasks


# =============================================================================
# PUBLIC API
# =============================================================================


def load_benchmark(
    benchmark_id: str,
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool = True,
    cache_ttl_hours: int = 24,
    _config: BenchmarkConfig | None = None,
) -> list[BenchmarkTask]:
    """Load tasks from a benchmark.

    Args:
        benchmark_id: Which benchmark to load
        limit: Maximum tasks to load
        offset: Starting offset
        use_cache: Whether to use cached data
        cache_ttl_hours: Cache expiry time
        config: Optional full configuration

    Returns:
        List of BenchmarkTask objects
    """
    # Get benchmark definition
    benchmark = BENCHMARK_DEFINITIONS.get(benchmark_id)
    if not benchmark:
        logger.error("Unknown benchmark: %s", benchmark_id)
        logger.error("  Available: %s", list(BENCHMARK_DEFINITIONS.keys()))
        return []

    logger.info("Loading benchmark: %s", benchmark.name)
    logger.info("    Type: %s", benchmark.benchmark_type.value)
    logger.info("    Size: ~%d tasks", benchmark.size)

    # Check cache
    if use_cache:
        cache_path = get_cache_path(benchmark_id)
        if is_cache_valid(cache_path, cache_ttl_hours):
            cached_data = load_from_cache(benchmark_id)
            if cached_data:
                logger.info("    Loaded from cache")
                tasks = [BenchmarkTask(**t) for t in cached_data]
                # Apply limit/offset to cached data
                tasks = tasks[offset:]
                if limit:
                    tasks = tasks[:limit]
                return tasks

    # Load from source
    tasks = []

    if benchmark.source == DataSource.HUGGINGFACE:
        tasks = _load_from_huggingface(benchmark, limit, offset)
    elif benchmark.source == DataSource.GITHUB:
        tasks = _load_from_github(benchmark, limit, offset)
    elif benchmark.source == DataSource.LOCAL:
        tasks = _load_from_local(benchmark, limit, offset)
    else:
        logger.error("Unsupported source: %s", benchmark.source)

    # Cache results
    if use_cache and tasks:
        save_to_cache([t.to_dict() for t in tasks], benchmark_id)
        logger.info("    Cached %d tasks", len(tasks))

    logger.info("    Loaded %d tasks", len(tasks))
    return tasks


def fetch_task(
    benchmark_id: str,
    task_id: str,
    use_cache: bool = True,
) -> BenchmarkTask | None:
    """Fetch a single task by ID.
        benchmark_id: Which benchmark
        task_id: Task identifier
        use_cache: Whether to use cache

    Returns:
        BenchmarkTask or None if not found
    """
    # Try cache first
    if use_cache:
        cached = load_from_cache(benchmark_id, task_id)
        if cached:
            return BenchmarkTask(**cached)

    # Load all tasks and find the one we want
    # (In production, would use more efficient lookup)
    tasks = load_benchmark(benchmark_id, use_cache=use_cache)
    for task in tasks:
        if task.task_id == task_id:
            # Cache individual task
            if use_cache:
                save_to_cache(task.to_dict(), benchmark_id, task_id)
            return task

    return None


def clear_cache(benchmark_id: str | None = None) -> int:
    """Clear cached benchmark data.

    Args:
        benchmark_id: Specific benchmark to clear, or None for all

    Returns:
        Number of files deleted
    """
    if not CACHE_DIR.exists():
        return 0

    deleted = 0
    for cache_file in CACHE_DIR.glob("*.json"):
        if benchmark_id:
            # Only delete if matches benchmark
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                    if data.get("benchmark_id") != benchmark_id:
                        continue
            except Exception:
                pass

        cache_file.unlink()
        deleted += 1

    return deleted
