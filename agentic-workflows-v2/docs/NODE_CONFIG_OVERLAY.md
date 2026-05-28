# Node Configuration Overlay Feature

## Overview

The Node Configuration Overlay enables **real-time, dynamic customization** of agent models, instructions, and generation parameters directly from the workflow execution UI. Users can override step configurations during execution without restarting or modifying YAML files.

## Features

### 🎛️ Configurable Parameters

- **Model Selection**: Choose different models per step (e.g., switch from `ollama:phi4` to `gh:gpt-4o`)
- **System Prompt/Instructions**: Customize the agent's instructions on the fly
- **Generation Parameters**:
  - `temperature` (0.0-2.0): Control creativity/determinism
  - `max_tokens`: Limit response length
  - `top_p` (0.0-1.0): Nucleus sampling control
- **Tool Selection**: Enable/disable specific tools for a step

### 🔄 Live Updates

- Changes apply **immediately** to the next execution of that step
- Persist throughout the entire workflow run
- Changes are tracked in execution metadata
- Server acknowledges config updates via WebSocket

### 🎨 User Interface

- **Settings Button**: Click the gear icon on any agent node to open configuration
- **Overlay Panel**: Right-side sliding panel with organized form fields
- **Copy Prompt**: Quick copy-to-clipboard for custom instructions
- **Reset Option**: Revert to initial configuration
- **Visual Feedback**: Indicates when config has been overridden

## Architecture

### Backend Stack

#### 1. **State Management** (`agentic_v2/langchain/state.py`)
- Added `node_config_overrides` field to `WorkflowState`
- Stores per-step configuration overrides as dict[str, dict]

#### 2. **WebSocket Communication** (`agentic_v2/server/websocket.py`)
- `ConnectionManager` now tracks node config overrides per run
- Handles `node_config_update` messages from frontend
- Methods:
  - `set_node_config()`: Store override for a step
  - `get_node_config()`: Retrieve overrides
  - `clear_node_configs()`: Cleanup when run completes

#### 3. **Agent Creation** (`agentic_v2/langchain/agents.py`)
- Modified `create_agent()` to accept `node_config` parameter
- Node config takes precedence over YAML-defined settings
- Applies parameter overrides:
  - System prompt replacement
  - Model override
  - Temperature, max_tokens, top_p adjustments
  - Tool restrictions

#### 4. **Graph Execution** (`agentic_v2/langchain/graph.py`)
- Updated `_llm_node()` to fetch node config from state
- Passes config to `_get_agent_for_model()`
- Caches agents separately per unique config combination
- Tracks config usage in step metadata

#### 5. **Data Models** (`agentic_v2/contracts/schemas.py`)
- `NodeConfigOverride`: Pydantic model for override data
  - Validates temperature (0-2), top_p (0-1), max_tokens (>0)
  - Optional fields for selective overrides
  - Includes metadata (applied_at, applied_by)
- `NodeConfigUpdateRequest`: WebSocket message schema

### Frontend Stack

#### 1. **Config Overlay Component** (`ui/src/components/live/NodeConfigOverlay.tsx`)
- Right-side sliding panel modal
- Form fields:
  - Select dropdown for models
  - Textarea for system prompt
  - Number inputs for generation parameters
  - Checkbox grid for tool selection
- Actions: Save & Apply, Reset, Cancel
- Copy button for prompt quick access

#### 2. **WebSocket Hook** (`ui/src/hooks/useNodeConfigUpdate.ts`)
- `useNodeConfigUpdate()`: Custom React hook
- Manages WebSocket connection lifecycle
- Auto-reconnect with 3-second backoff
- Formats and sends `node_config_update` messages

#### 3. **StepNode Integration** (`ui/src/components/dag/StepNode.tsx`)
- Settings icon button (gear) on configurable nodes
- Integrates `NodeConfigOverlay` modal
- Passes config data and update callbacks
- Shows overlay only for non-completed agent steps

#### 4. **LivePage Integration** (`ui/src/pages/LivePage.tsx`)
- Initializes `useNodeConfigUpdate()` hook
- Implements `handleConfigUpdate()` callback
- Passes runId and callback to DAG component
- Enables configuration during live execution

#### 5. **DAG Component Updates** (`ui/src/components/dag/WorkflowDAG.tsx`)
- Props: `runId`, `onConfigUpdate`
- Passes to node data for overlay access
- Enables per-node configuration flows

## Message Protocol

### WebSocket Message: Node Config Update

**Client → Server** (via WebSocket):
```json
{
  "type": "node_config_update",
  "step_name": "tier2_reviewer",
  "config": {
    "model": "gh:gpt-4o",
    "system_prompt": "Custom instructions...",
    "temperature": 0.8,
    "max_tokens": 4096,
    "top_p": 0.95,
    "tool_names": ["file_edit", "code_review"]
  }
}
```

**Server → Client** (acknowledgment):
```json
{
  "type": "node_config_ack",
  "step_name": "tier2_reviewer",
  "timestamp": 1708123456.789
}
```

## Usage Flow

### 1. Start Execution
- Run workflow from UI
- DAG visualizes all steps

### 2. Monitor & Configure
- Watch nodes execute in real-time
- When a step is pending/running, click its ⚙️ icon
- Overlay panel slides in from right

### 3. Customize Settings
- Update model, prompt, or parameters
- Changes preview immediately
- Click "**Save & Apply**" to send to backend

### 4. Immediate Effect
- Backend receives update
- Next execution of that step uses new config
- Metadata tracks the override

### 5. Persist Across Retries
- If step fails and retries, new config persists
- Config stays active for the entire run
- Reset or update anytime before step executes

## Examples

### Example 1: Switch Models Mid-Run

**Scenario**: Tier 2 agent is running slow, want to try gpt-4o
1. Click ⚙️ on the step node
2. Select `gh:gpt-4o` from Model dropdown
3. Click "Save & Apply"
4. Next execution uses the faster model

### Example 2: Customize Agent Instructions

**Scenario**: Review step needs stricter criteria
1. Open config overlay
2. Paste custom instructions in System Prompt field:
   ```
   You are a senior code reviewer. Focus strictly on:
   - Security vulnerabilities (CRITICAL)
   - Performance issues (HIGH priority)
   - Architectural violations (MEDIUM)
   
   Reject any code that doesn't meet these standards.
   ```
3. Click "Save & Apply"
4. Agent now uses custom criteria

### Example 3: Reduce Hallucination

**Scenario**: Generation is too creative, want deterministic output
1. Open config overlay
2. Set Temperature to `0.2`
3. Set Top P to `0.8`
4. Click "Save & Apply"
5. Next generation is more deterministic

## State Diagram

```
┌─────────────────────────────────────────────────┐
│          Step Execution Flow                    │
├─────────────────────────────────────────────────┤
│                                                 │
│  [Pending] → [Running] → [Success/Failed]     │
│      ↓         ↓                                 │
│      └─── Can Open Config Overlay ──────┘      │
│            (Before execution)                    │
│      ↓                                           │
│   [WebSocket: node_config_update]               │
│      ↓                                           │
│   [Update state.node_config_overrides]          │
│      ↓                                           │
│   [Next iteration uses new config]              │
│      ↓                                           │
│   [Agent created with overrides]                │
│      ↓                                           │
│   [Metadata tracks config_overridden=true]      │
│                                                 │
└─────────────────────────────────────────────────┘
```

## Caching & Performance

- **Agent Caching**: Agents are cached by (model_id, config_tuple)
- **Config Isolation**: Different configs create separate cache entries
- **Minimal Overhead**: Config checks only on step execution start
- **Metadata Tracking**: Minimal additional memory for overrides

## Limitations & Design Notes

1. **Timing**: Config must be changed **before** step starts execution
2. **Scope**: Applies only within current workflow run
3. **Validation**: Client-side validation only (consider backend validation if needed)
4. **Persistence**: Changes don't persist to YAML files (by design)
5. **Retry Logic**: Overrides survive step retries within same run

## Error Handling

- **WebSocket Disconnect**: Hook auto-reconnects every 3s
- **Invalid Config**: Silently treated as None (use defaults)
- **Model Unavailable**: Falls back to tier-based selection
- **Invalid JSON**: WebSocket keeps connection alive, ignores malformed messages

## Future Enhancements

- [ ] Backend validation of config values
- [ ] Config history/audit log per run
- [ ] Template-based config presets
- [ ] Batch config updates for multiple steps
- [ ] Persist config as "favorites" to YAML
- [ ] Config diff visualization
- [ ] Undo/redo for config changes
- [ ] Export config snapshot with run results

## Testing Checklist

- [ ] Open config overlay on running step
- [ ] Update model selection
- [ ] Update system prompt
- [ ] Adjust generation parameters
- [ ] Toggle tool selection
- [ ] Click Save & Apply
- [ ] Verify step executes with new config
- [ ] Check metadata includes override flags
- [ ] Test WebSocket reconnection
- [ ] Verify config persists across step retries
- [ ] Test UI responsiveness with rapid config changes
