"""Interactive UI helpers for benchmark runner."""

from __future__ import annotations

import json
from pathlib import Path

from tools.agents.benchmarks.datasets import BENCHMARK_DEFINITIONS
from tools.agents.benchmarks.registry import BenchmarkConfig


def load_discovered_models() -> dict[str, list[str]]:
    """Load discovered models from discovery_results.json or run discovery."""
    discovery_file = Path(__file__).parents[3] / "discovery_results.json"

    if discovery_file.exists():
        try:
            data = json.loads(discovery_file.read_text(encoding="utf-8"))
            return data.get("providers", {})
        except Exception:
            pass

    try:
        from tools.llm.model_probe import discover_all_models

        result = discover_all_models(verbose=False)
        return result.get("providers", {})
    except ImportError:
        return {}


def get_available_models_by_provider() -> dict[str, list[str]]:
    """Get all available models grouped by provider."""
    providers = load_discovered_models()
    result = {}

    for provider_name, provider_data in providers.items():
        if isinstance(provider_data, dict):
            available = provider_data.get("available", [])
            if available:
                result[provider_name] = available

    return result


def get_flat_model_list() -> list[str]:
    """Get a flat list of all available models."""
    models = []
    for provider_models in get_available_models_by_provider().values():
        models.extend(provider_models)
    return sorted(set(models))


def print_header(text: str, char: str = "=") -> None:
    """Print a header line."""
    print(f"\n{char * 80}")
    print(f" {text}")
    print(f"{char * 80}")


def print_table(headers: list[str], rows: list[list[str]], widths: list[int]) -> None:
    """Print a formatted table."""
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False))
    print(header_line)
    print("-" * len(header_line))

    for row in rows:
        print(
            " | ".join(str(c).ljust(w)[:w] for c, w in zip(row, widths, strict=False))
        )


def colorize(text: str, color: str) -> str:
    """Add ANSI color codes (for terminals that support it)."""
    colors = {
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "blue": "\033[94m",
        "cyan": "\033[96m",
        "reset": "\033[0m",
    }
    return f"{colors.get(color, '')}{text}{colors.get('reset', '')}"


def prompt_choice(options: list[str], prompt: str = "Select") -> int:
    """Prompt user to select from options."""
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")

    while True:
        try:
            choice = input(f"\n{prompt} [1-{len(options)}]: ").strip()
            if choice.lower() == "q":
                return -1
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print("Invalid choice. Try again (or 'q' to quit).")


def prompt_input(prompt: str, default: str = "") -> str:
    """Prompt for text input with default."""
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no."""
    suffix = "[Y/n]" if default else "[y/N]"
    result = input(f"{prompt} {suffix}: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes", "1", "true")


def select_benchmark() -> str | None:
    """Interactive benchmark selection."""
    print_header("SELECT BENCHMARK")

    groups = {}
    for bid, bdef in BENCHMARK_DEFINITIONS.items():
        type_name = bdef.benchmark_type.value
        if type_name not in groups:
            groups[type_name] = []
        groups[type_name].append((bid, bdef))

    options = []
    for type_name, benchmarks in sorted(groups.items()):
        print(f"\n  {colorize(type_name.upper(), 'cyan')}:")
        for bid, bdef in benchmarks:
            idx = len(options) + 1
            size_str = f"~{bdef.size} tasks"
            print(f"    [{idx}] {bdef.name} ({size_str})")
            print(f"        {bdef.description[:60]}...")
            options.append(bid)

    print("\n    [q] Quit")

    choice = prompt_choice(options, "Select benchmark")
    if choice < 0:
        return None
    return options[choice]


def select_model() -> str | None:
    """Interactive model selection using discovered models."""
    print_header("SELECT MODEL")

    providers = get_available_models_by_provider()

    if not providers:
        print(colorize("  No models discovered. Run model discovery first:", "yellow"))
        print(
            "    python -m tools.llm.model_probe --discover --force -o discovery_results.json"
        )
        print()
        return prompt_input("Enter model ID manually (e.g., 'gh:gpt-4o-mini')")

    provider_display = {
        "github_models": (
            "🌐 GitHub Models",
            ["gh:openai/gpt-4o-mini", "gh:openai/gpt-4o", "gh:microsoft/phi-4"],
        ),
        "local_onnx": (
            "💻 Local ONNX",
            ["local:phi4", "local:phi3.5", "local:mistral"],
        ),
        "ollama": (
            "🦙 Ollama",
            [
                "ollama:deepseek-r1:8b",
                "ollama:qwen2.5-coder:14b",
                "ollama:phi4-reasoning:latest",
            ],
        ),
        "ai_toolkit": (
            "🧰 AI Toolkit",
            ["aitk:phi-4-mini-instruct", "aitk:qwen2.5-coder-7b-instruct"],
        ),
    }

    all_models = []
    print()

    for provider_key, (display_name, recommended) in provider_display.items():
        if provider_key in providers:
            available = providers[provider_key]
            shown = [model for model in recommended if model in available][:3]
            if not shown:
                shown = available[:3]

            print(f"  {display_name} ({len(available)} available)")
            for model in shown:
                idx = len(all_models) + 1
                print(f"    [{idx}] {model}")
                all_models.append(model)
            if len(available) > 3:
                print(f"      ... +{len(available) - 3} more")
            print()

    print(f"  [{len(all_models) + 1}] Browse all models")
    print(f"  [{len(all_models) + 2}] Enter model ID manually")
    print("  [q] Quit")

    while True:
        choice = input(f"\nSelect model [1-{len(all_models) + 2}]: ").strip()

        if choice.lower() == "q":
            return None

        try:
            idx = int(choice)
            if 1 <= idx <= len(all_models):
                return all_models[idx - 1]
            if idx == len(all_models) + 1:
                return browse_all_models(providers)
            if idx == len(all_models) + 2:
                return prompt_input("Enter model ID")
        except ValueError:
            pass

        print("Invalid choice. Try again.")


def browse_all_models(providers: dict[str, list[str]]) -> str | None:
    """Browse complete model list by provider."""
    print_header("ALL AVAILABLE MODELS")

    provider_options = list(providers.keys())
    provider_display_names = {
        "github_models": "GitHub Models",
        "local_onnx": "Local ONNX",
        "ollama": "Ollama",
        "ai_toolkit": "AI Toolkit",
        "openai": "OpenAI",
        "gemini": "Gemini",
        "anthropic": "Anthropic",
    }

    print("\nSelect provider:")
    for i, provider in enumerate(provider_options, 1):
        display = provider_display_names.get(provider, provider)
        print(f"  [{i}] {display} ({len(providers[provider])} models)")
    print("  [q] Back")

    choice = input(f"\nSelect provider [1-{len(provider_options)}]: ").strip()
    if choice.lower() == "q":
        return select_model()

    try:
        provider_idx = int(choice) - 1
        if not (0 <= provider_idx < len(provider_options)):
            return None

        selected_provider = provider_options[provider_idx]
        models = sorted(providers[selected_provider])

        print(
            f"\n{provider_display_names.get(selected_provider, selected_provider)} models:"
        )
        for i, model in enumerate(models, 1):
            print(f"  [{i}] {model}")
        print("  [q] Back")

        model_choice = input(f"\nSelect model [1-{len(models)}]: ").strip()
        if model_choice.lower() == "q":
            return select_model()

        model_idx = int(model_choice) - 1
        if 0 <= model_idx < len(models):
            return models[model_idx]
    except (ValueError, IndexError):
        pass

    return None


def select_workflow() -> str | None:
    """Interactive workflow selection."""
    print_header("SELECT WORKFLOW")

    workflows = [
        ("multi-agent", "Full multi-agent orchestration (recommended)"),
        ("single-agent", "Single agent baseline"),
        ("chain-of-thought", "Chain-of-thought reasoning"),
        ("react", "ReAct pattern"),
    ]

    for i, (workflow_id, description) in enumerate(workflows, 1):
        print(f"  [{i}] {workflow_id:15} - {description}")
    print("  [q] Quit")

    choice = prompt_choice(
        [workflow_id for workflow_id, _ in workflows], "Select workflow"
    )
    if choice < 0:
        return None
    return workflows[choice][0]


def configure_options(config: BenchmarkConfig) -> BenchmarkConfig:
    """Configure optional settings interactively."""
    print_header("CONFIGURE OPTIONS")

    config.limit = (
        int(prompt_input("Task limit (0=all)", str(config.limit or 0))) or None
    )
    config.verbose = prompt_yes_no("Verbose output?", config.verbose)
    config.save_intermediate = prompt_yes_no(
        "Save intermediate outputs?",
        config.save_intermediate,
    )
    config.use_cache = prompt_yes_no("Use cached benchmark data?", config.use_cache)

    return config


def interactive_mode() -> BenchmarkConfig | None:
    """Run interactive configuration flow."""
    print_header("BENCHMARK RUNNER - INTERACTIVE MODE")
    print("Press 'q' at any prompt to quit.\n")

    benchmark_id = select_benchmark()
    if not benchmark_id:
        return None

    model = select_model()
    if not model:
        return None

    workflow = select_workflow()
    if not workflow:
        return None

    config = BenchmarkConfig(
        benchmark_id=benchmark_id,
        model=model,
        workflow=workflow,
    )
    config = configure_options(config)

    print_header("CONFIGURATION SUMMARY")
    print(f"  Benchmark: {colorize(config.benchmark_id, 'cyan')}")
    print(f"  Model:     {colorize(config.model, 'cyan')}")
    print(f"  Workflow:  {colorize(config.workflow, 'cyan')}")
    print(f"  Limit:     {config.limit or 'all tasks'}")
    print(f"  Verbose:   {config.verbose}")
    print(f"  Cache:     {config.use_cache}")

    if not prompt_yes_no("\nProceed with benchmark run?", True):
        return None

    return config
