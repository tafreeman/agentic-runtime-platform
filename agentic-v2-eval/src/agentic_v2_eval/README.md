# Agentic V2 Evaluation Module

## Overview
This module provides a flexible evaluation framework for agentic workflows, supporting rubric-based scoring, batch and streaming runners, and multiple report formats.

## Features
- Scorer framework with YAML rubrics
- Accuracy, quality, and performance metrics
- Batch and streaming evaluation runners
- JSON, Markdown, and HTML reporters
- Extensible for custom metrics and rubrics

## Usage Example
```python
from src.agentic_v2_eval.scorer import Scorer
scorer = Scorer('src/agentic_v2_eval/rubrics/default.yaml')
results = {'Accuracy': 0.8, 'Completeness': 0.9, 'Efficiency': 0.7}
score = scorer.score(results)
print(f"Weighted score: {score}")
```

## API Reference
- `Scorer`: Loads rubric and computes weighted scores
- `run_batch_evaluation`: Runs batch evaluation
- `run_streaming_evaluation`: Runs streaming evaluation
- `generate_json_report`, `generate_markdown_report`, `generate_html_report`: Output results

## Extending
Add new metrics in `metrics/`, new rubrics in `rubrics/`, or custom reporters in `reporters/`.
