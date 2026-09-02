---
title: CLI reference
description: Current agentic command paths, inputs, defaults, and exit behavior.
tags:
  - reference
  - cli
---

# CLI reference

The `agentic` command is installed by the `agentic-workflows-v2` package:

```bash
pip install -e "./agentic-workflows-v2[server,langchain]"
agentic --help
```

Run commands from the repository root or pass explicit paths. Relative workflow
paths, input files, output files, and checkpoint directories are resolved from
the current directory.

## Command map

| Command | Purpose |
|---|---|
| `agentic run` | Run a named or path-based YAML workflow |
| `agentic compare` | Run one workflow through multiple execution adapters |
| `agentic orchestrate` | Build and run a workflow from a task description |
| `agentic resume` | Read a saved execution checkpoint and report changed files |
| `agentic list` | List workflows, agents, tools, or execution adapters |
| `agentic validate` | Validate a workflow without running it |
| `agentic serve` | Start the FastAPI server and packaged UI |
| `agentic version` | Print package and runtime version information |
| `agentic devex` | Run development checks |

## `agentic run`

```text
agentic run [OPTIONS] WORKFLOW
```

`WORKFLOW` is either a built-in workflow name such as `code_review` or a path
to a YAML file.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--input`, `-i` | path | none | JSON file containing workflow inputs |
| `--output`, `-o` | path | none | Write the run result as JSON |
| `--dry-run` | flag | off | Validate and print the execution plan without running steps |
| `--verbose`, `-v` | flag | off | Print step-level details |
| `--adapter`, `-a` | text | `langchain` | Use `langchain` or `native` |

The input option accepts a file path:

```bash
agentic run code_review --input review-input.json --adapter native
```

The command exits non-zero when validation fails or the workflow cannot be
run. A workflow result whose overall status is failed is also reported as a
failed command.

## `agentic compare`

```text
agentic compare [OPTIONS] WORKFLOW
```

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--input`, `-i` | path | required | JSON input file used for every adapter |
| `--adapters` | comma-separated text | `native,langchain` | Adapter names to run |

```bash
agentic compare code_review \
  --input review-input.json \
  --adapters native,langchain
```

The command prints status, step count, and elapsed time for each adapter. It
exits non-zero if any adapter fails, because a one-sided result is not a valid
comparison.

## `agentic orchestrate`

```text
agentic orchestrate [OPTIONS] TASK
```

`TASK` is a text description. The command generates and executes a workflow
through the runtime's dynamic orchestration path. It does not use the default
LangGraph path for named YAML workflows.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--max-parallel`, `--max-steps` | integer | `3` | Maximum number of steps dispatched at the same time |
| `--verbose`, `-v` | flag | off | Print planning and execution details |

```bash
agentic orchestrate "Summarize the changed Python modules" --max-parallel 2
```

This command needs a usable model provider unless `AGENTIC_NO_LLM=1` is set.
Placeholder mode tests orchestration flow, not the quality of the generated
plan.

## `agentic resume`

```text
agentic resume [OPTIONS] NAME
```

`NAME` is the checkpoint file stem.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--checkpoint-dir` | path | `.agentic_checkpoints` | Directory containing checkpoint JSON files |
| `--fork` | text | none | Create a divergent checkpoint with this name after loading |

```bash
agentic resume my_run --checkpoint-dir ./checkpoints
agentic resume my_run --checkpoint-dir ./checkpoints --fork experiment_a
```

The command restores an `ExecutionContext`, compares tracked files with their
saved state, and reports which files changed. It does not restore a model's
hidden conversation state.

## `agentic list`

```text
agentic list [COMPONENT_TYPE]
```

`COMPONENT_TYPE` is one of:

- `workflows` (default)
- `agents`
- `tools`
- `adapters`

```bash
agentic list
agentic list tools
```

## `agentic validate`

```text
agentic validate [OPTIONS] WORKFLOW
```

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--verbose`, `-v` | flag | off | Print workflow counts and the execution plan |

Validation checks YAML syntax, the workflow schema, missing dependencies,
cycles, and LangGraph compilation. The compilation check requires the
`langchain` extra even when you intend to execute the workflow with the native
adapter.

```bash
agentic validate code_review --verbose
agentic validate ./workflows/custom.yaml
```

## `agentic serve`

```text
agentic serve [OPTIONS]
```

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--port`, `-p` | integer | `8000` | HTTP port |
| `--dev` | flag | off | Enable server auto-reload |
| `--no-open` | flag | off | Do not open a browser |

```bash
agentic serve --port 8010 --dev --no-open
```

The repository's `just dev` launcher uses backend port `8010` and Vite port
`5173`. The standalone CLI uses port `8000` unless you override it.

## `agentic version`

```bash
agentic version
```

Prints the installed runtime version and basic environment information.

## `agentic devex`

### Port checks

```bash
agentic devex port-guard --backend-port 8010 --frontend-port 5173
```

The command's built-in defaults are `8012` and `5174`, which differ from
`just dev`. Pass the ports explicitly when checking the standard development
launcher.

### Workspace tests

```bash
agentic devex workspace-test-runner
agentic devex workspace-test-runner --coverage
agentic devex workspace-test-runner --package agentic-workflows-v2
```

| Option | Default | Meaning |
|---|---|---|
| `--skip-integration` / `--no-skip-integration` | skip | Exclude or include tests marked `integration` |
| `--coverage` / `--no-coverage` | no coverage | Add coverage reporting |
| `--package` | all | Limit the run to `agentic-workflows-v2`, `agentic-v2-eval`, or `tools` |

### Workflow linter

```bash
agentic devex workflow-linter code_review
agentic devex workflow-linter ./workflow.yaml --strict
```

`--strict` treats warnings as violations.

## Environment behavior

- Settings are read from process environment variables and the repository
  `.env` file. See [Configuration](configuration.md).
- `AGENTIC_NO_LLM=1` installs fixed-response model substitutes for both
  execution engines. It does not install missing optional packages.
- Named YAML runs default to `langchain`; runtime-generated DAGs use the native
  engine.
- Paths are relative to the shell's current directory.

## Getting help

Every group and command supports `--help`:

```bash
agentic --help
agentic run --help
agentic devex workspace-test-runner --help
```

Typer's generated help is the source of truth for installed command options.
This page records the command behavior in the current repository.
