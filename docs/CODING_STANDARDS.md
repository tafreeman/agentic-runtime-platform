# Python & AI/ML Coding Standards

> Feb 2026

---

## 1. Code Style & Formatting

*Automated consistency, zero debates*

### Black + isort on every save — **Required**

Configure Black (line-length 88) and isort (profile=black) in pyproject.toml. Add pre-commit hooks so unformatted code never reaches the repo. Zero config debates.

**Tools:** Black, isort, pre-commit

### Ruff as your single linter — **Required**

Ruff replaces Flake8, pylint, pycodestyle in a single Rust-powered tool (10-100x faster). Enable rules: E, F, W, I, N, UP, S, B, A, C4, SIM, TCH, RUF. Block merge on errors.

**Tools:** Ruff

### Type hints everywhere + mypy strict — **Required**

Type hints on all function signatures and class attributes. Enable mypy --strict in CI. For ML: annotate tensor shapes in docstrings (e.g., `# shape: (batch, seq_len, d_model)`).

**Tools:** mypy, pyright

### Organized imports: stdlib then third-party then local — **Required**

Group imports: (1) standard library, (2) third-party (numpy, torch, sklearn), (3) local project. One blank line between groups. isort handles this automatically. No wildcard imports.

**Tools:** isort

### pyproject.toml as single config source — **Recommended**

Consolidate all tool configs into pyproject.toml. No scattered setup.cfg, .flake8, mypy.ini. Pin Python version with requires-python. Use hatchling, setuptools, or flit.

---

## 2. Naming & Project Structure

*Predictable, searchable, self-documenting*

### PEP 8 naming with no exceptions — **Required**

snake_case for functions/variables/modules. PascalCase for classes. UPPER_SNAKE for constants. _private prefix for internal APIs. Booleans as questions: `is_trained`, `has_converged`.

### Name by intent, not type — **Required**

Avoid: `df`, `model`, `X_train`. Prefer: `customer_transactions`, `churn_classifier`, `training_features`. Exception: short-lived loop vars and well-known ML conventions (X, y) in small scopes.

### Feature-based project layout — **Recommended**

`src/<project>/` with subpackages by feature. Co-locate tests beside source. ML-specific: separate `/notebooks`, `/configs`, `/data` (gitignored), `/models` (gitignored), `/src` for production.

### No magic numbers, use constants or configs — **Required**

Extract all hyperparameters to config files (YAML/TOML) or dataclasses. Use Hydra, OmegaConf, or Pydantic Settings for config management. Makes experiments reproducible.

**Tools:** Hydra, OmegaConf, Pydantic

### Separate notebooks from production code — **Required**

Notebooks for exploration only, never production logic. Extract reusable code into .py modules immediately. Use nbstripout to strip outputs from committed notebooks.

**Tools:** nbstripout

---

## 3. Error Handling & Logging

*Fail gracefully, debug quickly*

### Never silently swallow exceptions — **Required**

Every except block must: log with context, re-raise, or return meaningful error. `except: pass` is forbidden. For ML: catch specific failures (data loading, GPU OOM) with context to reproduce.

### Structured logging with structlog — **Required**

Use structlog or loguru instead of `print()`. Log as JSON in production. Include: timestamp, severity, experiment_id, model_version. Add GPU memory and training step to ML logs.

**Tools:** structlog, loguru

### Custom exception hierarchy — **Recommended**

Create: `DataValidationError`, `ModelNotTrainedError`, `PipelineTimeoutError`, `InferenceError`. Enables precise handling and better error messages. Map to HTTP codes at API boundaries.

### Validate inputs at boundaries with Pydantic — **Required**

Pydantic BaseModel for API inputs, configs, pipeline interfaces. Validate data schemas before training with pandera. Fail fast: reject bad data before a 3-hour training run.

**Tools:** Pydantic, pandera

### Never log secrets, PII, or model weights — **Required**

Sanitize logs: no API keys, user data, or raw model parameters. Be cautious with training samples containing PII. Audit log output. Compliance requirement (GDPR, CCPA).

---

## 4. Testing & Code Review

*Ship with confidence*

### Test behavior, not implementation — **Required**

Use pytest. Test what code does, not how. Assert output correct for input. Arrange-Act-Assert pattern. For ML: test output shapes, prediction ranges, preprocessing determinism.

**Tools:** pytest

### Testing pyramid: unit, integration, E2E — **Required**

Many fast unit tests, some integration tests (API, DB, pipeline stages), few E2E tests (full train-to-inference). Target 70-80% coverage on business logic. `@pytest.mark.slow` for heavy tests.

**Tools:** pytest-cov

### ML-specific: test pipelines and model contracts — **Required**

Test: data loading schema, deterministic preprocessing (set seeds), model input shapes, valid prediction ranges, saved model reload produces same output. Use fixtures for synthetic data.

**Tools:** pytest fixtures

### CI blocks merge on any failure — **Required**

Every PR triggers: Ruff lint, mypy check, pytest. Single failure blocks merge. Keep unit tests <5 min. Flaky tests are bugs. Use GitHub Actions or GitLab CI.

**Tools:** GitHub Actions

### Small PRs, review for logic not style — **Required**

Style enforced by Black + Ruff. Humans review for: correctness, edge cases, error handling, security, performance. 1 approval required. PRs <400 lines. Use PR templates.

---

## 5. AI/ML Best Practices

*Reproducible, responsible, production-ready*

### Pin seeds everywhere for reproducibility — **Required**

Set seeds: random, numpy, torch, tensorflow, PYTHONHASHSEED. Use deterministic algorithms (`torch.use_deterministic_algorithms`). Log full env: Python version, packages, GPU, CUDA.

**Tools:** random.seed, torch.manual_seed

### Version data, models, configs, and code — **Required**

DVC or MLflow for data/model versioning. Track experiments with W&B, MLflow, or Neptune. Configs alongside code (Hydra). Every experiment reproducible from commit hash + config.

**Tools:** DVC, MLflow, W&B, Hydra

### Separate training, eval, and inference code — **Required**

Clean interfaces: `Trainer.train()`, `Evaluator.evaluate()`, `Predictor.predict()`. Each independently testable. Makes it trivial to swap models or deploy to different targets.

### Validate data quality before and after transforms — **Required**

Use pandera or great_expectations for data schemas. Validate: column types, value ranges, nulls, distribution drift. Run on raw input AND after preprocessing. Fail pipeline on check failure.

**Tools:** pandera, great_expectations

### Treat AI-generated code as untrusted input — **Required**

Always review generated code for correctness, security, and standards adherence. Run full lint, type checks, and tests before accepting changes.

### Document model cards and ethics — **Recommended**

Every deployed model needs a model card: intended use, limitations, training data summary, eval metrics, bias analysis, failure modes. Consider fairness metrics for user-facing models.

**Tools:** Model Cards, SHAP, LIME

### Containerize and pin for deployment — **Required**

Docker for reproducible environments. Pin ALL deps with pip-compile or Poetry lock. Pin CUDA/cuDNN in Dockerfile. No 'latest' tags. Test inference in container before deploy.

**Tools:** Docker, pip-tools, Poetry

---

## Summary

| Section | Total | Required | Recommended |
|---------|-------|----------|-------------|
| Code Style & Formatting | 5 | 4 | 1 |
| Naming & Project Structure | 5 | 4 | 1 |
| Error Handling & Logging | 5 | 4 | 1 |
| Testing & Code Review | 5 | 5 | 0 |
| AI/ML Best Practices | 7 | 6 | 1 |
| **Total** | **27** | **23** | **4** |
