# Workflow Execution Fixtures

This directory contains sample workflow execution artifacts for documentation and testing purposes.

## About Workflow Runs

The agentic workflows engine generates JSON run logs in `runs/` directory during execution. These files contain:
- Workflow execution metadata (run_id, status, timing)
- Step-by-step execution details
- Model usage and token counts
- Input/output data for each step

## Why are run logs not committed?

Run logs are excluded from git (via `.gitignore`) because:
- They are generated artifacts, not source code
- They can be large and create noisy diffs
- They accumulate rapidly during development
- They vary by environment and execution context

## Representative Samples

This fixtures directory contains minimal representative samples for:
- Documentation purposes
- Understanding the output format
- Testing parsing logic

Actual run logs from your executions will be stored in `runs/` but not committed to the repository.
