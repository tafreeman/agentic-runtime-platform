import { useState, useCallback, useEffect } from "react";
import {
  X,
  Save,
  RotateCcw,
  Copy,
  Settings2,
} from "lucide-react";

interface NodeConfig {
  model?: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  tool_names?: string[];
}

interface NodeConfigOverlayProps {
  stepName: string;
  isOpen: boolean;
  onClose: () => void;
  initialConfig?: NodeConfig;
  onSave: (config: NodeConfig) => void;
  availableModels?: string[];
  availableTools?: string[];
}

export default function NodeConfigOverlay({
  stepName,
  isOpen,
  onClose,
  initialConfig = {},
  onSave,
  availableModels = [
    "gh:gpt-4o",
    "gh:gpt-4o-mini",
    "ollama:phi4",
    "ollama:llama3.2:latest",
  ],
  availableTools = [],
}: Readonly<NodeConfigOverlayProps>) {
  const [config, setConfig] = useState<NodeConfig>(initialConfig);
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    setConfig(initialConfig);
    setHasChanges(false);
  }, [initialConfig, isOpen]);

  const handleConfigChange = useCallback(
    (key: keyof NodeConfig, value: any) => {
      setConfig((prev) => ({
        ...prev,
        [key]: value === "" ? undefined : value,
      }));
      setHasChanges(true);
    },
    []
  );

  const handleReset = useCallback(() => {
    setConfig(initialConfig);
    setHasChanges(false);
  }, [initialConfig]);

  const handleSave = useCallback(() => {
    onSave(config);
    setHasChanges(false);
  }, [config, onSave]);

  const handleCopyPrompt = useCallback(async () => {
    if (config.system_prompt) {
      try {
        await navigator.clipboard.writeText(config.system_prompt);
      } catch (err) {
        console.error("Failed to copy prompt", err);
      }
    }
  }, [config.system_prompt]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end">
      {/* Backdrop */}
      <button
        type="button"
        className="absolute inset-0 cursor-default border-0 bg-black/30 backdrop-blur-sm"
        aria-label="Close configuration overlay"
        onClick={onClose}
      />

      {/* Overlay Panel */}
      <div className="relative h-screen max-h-screen w-full max-w-2xl overflow-hidden bg-white shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white px-6 py-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <Settings2 className="h-5 w-5 text-gray-600" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                Configure Step
              </h2>
              <p className="text-sm text-gray-500">{stepName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="rounded-lg p-2 hover:bg-gray-100 transition-colors"
            title="Close"
          >
            <X className="h-5 w-5 text-gray-600" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {/* Model Selection */}
          <div>
            <label htmlFor="node-config-model" className="block text-sm font-medium text-gray-900 mb-2">
              Model
            </label>
            <select
              id="node-config-model"
              value={config.model || ""}
              onChange={(e) => handleConfigChange("model", e.target.value)}
              className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-colors"
            >
              <option value="">Use Default (tier-based)</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-500">
              Leave empty to use default model for this agent tier
            </p>
          </div>

          {/* System Prompt */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label htmlFor="node-config-system-prompt" className="block text-sm font-medium text-gray-900">
                System Prompt / Instructions
              </label>
              {config.system_prompt && (
                <button
                  onClick={handleCopyPrompt}
                  type="button"
                  className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                  title="Copy prompt to clipboard"
                >
                  <Copy className="h-3 w-3" />
                  Copy
                </button>
              )}
            </div>
            <textarea
              id="node-config-system-prompt"
              value={config.system_prompt || ""}
              onChange={(e) =>
                handleConfigChange("system_prompt", e.target.value)
              }
              placeholder="Leave empty to use default instructions..."
              rows={6}
              className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-mono focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-colors resize-none"
            />
            <p className="mt-1 text-xs text-gray-500">
              Override the system prompt for this agent
            </p>
          </div>

          {/* Generation Parameters */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* Temperature */}
            <div>
              <label htmlFor="node-config-temperature" className="block text-sm font-medium text-gray-900 mb-2">
                Temperature
              </label>
              <input
                id="node-config-temperature"
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={config.temperature ?? ""}
                onChange={(e) =>
                  handleConfigChange(
                    "temperature",
                    e.target.value ? Number.parseFloat(e.target.value) : undefined
                  )
                }
                placeholder="0.7"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-colors"
              />
              <p className="mt-1 text-xs text-gray-500">
                0.0 (deterministic) - 2.0 (creative)
              </p>
            </div>

            {/* Max Tokens */}
            <div>
              <label className="block text-sm font-medium text-gray-900 mb-2">
                Max Tokens
              </label>
              <input
                type="number"
                min="1"
                step="100"
                value={config.max_tokens ?? ""}
                onChange={(e) =>
                  handleConfigChange(
                    "max_tokens",
                    e.target.value ? Number.parseInt(e.target.value, 10) : undefined
                  )
                }
                placeholder="4096"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-colors"
              />
              <p className="mt-1 text-xs text-gray-500">Maximum response length</p>
            </div>

            {/* Top P */}
            <div>
              <label className="block text-sm font-medium text-gray-900 mb-2">
                Top P
              </label>
              <input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={config.top_p ?? ""}
                onChange={(e) =>
                  handleConfigChange(
                    "top_p",
                    e.target.value ? Number.parseFloat(e.target.value) : undefined
                  )
                }
                placeholder="1.0"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-colors"
              />
              <p className="mt-1 text-xs text-gray-500">
                Nucleus sampling (0.0 - 1.0)
              </p>
            </div>
          </div>

          {/* Tools Selection */}
          {availableTools.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-900 mb-2">
                Available Tools
              </label>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {availableTools.map((tool) => (
                  <label
                    key={tool}
                    className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 cursor-pointer hover:bg-gray-50 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={
                        !config.tool_names ||
                        config.tool_names.includes(tool)
                      }
                      onChange={(e) => {
                        const current = config.tool_names || availableTools;
                        const updated = e.target.checked
                          ? [...new Set([...current, tool])]
                          : current.filter((t) => t !== tool);
                        handleConfigChange(
                          "tool_names",
                          updated.length > 0 ? updated : undefined
                        );
                      }}
                      className="rounded border-gray-300"
                    />
                    <span className="text-xs text-gray-700">{tool}</span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Select which tools this agent can use
              </p>
            </div>
          )}

          {/* Info Box */}
          <div className="rounded-lg bg-blue-50 border border-blue-200 p-3">
            <p className="text-xs text-blue-900">
              <strong>Note:</strong> Configuration changes are applied immediately
              to the next execution of this step. Changes persist for the entire
              workflow run.
            </p>
          </div>
        </div>

        {/* Footer / Actions */}
        <div className="flex-shrink-0 border-t border-gray-200 bg-gray-50 px-6 py-4 flex items-center justify-between">
          <button
            onClick={handleReset}
            type="button"
            disabled={!hasChanges}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RotateCcw className="h-4 w-4" />
            Reset
          </button>

          <div className="flex gap-2">
            <button
              onClick={onClose}
              type="button"
              className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              type="button"
              disabled={!hasChanges}
              className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Save className="h-4 w-4" />
              Save & Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
