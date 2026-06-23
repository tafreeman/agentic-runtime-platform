import { useState, useCallback, useEffect, useRef } from "react";
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
  const firstFocusableRef = useRef<HTMLSelectElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setConfig(initialConfig);
    setHasChanges(false);
  }, [initialConfig, isOpen]);

  // Focus first control when panel opens
  useEffect(() => {
    if (isOpen) {
      firstFocusableRef.current?.focus();
    }
  }, [isOpen]);

  // Close on Escape and trap focus within panel
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      if (e.key === "Tab" && panelRef.current) {
        const focusable = Array.from(
          panelRef.current.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        ).filter((el) => !el.hasAttribute("disabled"));

        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (!first || !last) return;

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

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
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="node-config-title"
        className="relative h-screen max-h-screen w-full max-w-2xl overflow-hidden bg-b-bg1 shadow-2xl flex flex-col animate-in slide-in-from-right duration-300"
        style={{ borderLeft: "var(--b-bw) solid rgb(var(--b-clay))" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-b-line bg-b-bg2 px-6 py-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <Settings2 className="h-5 w-5 text-b-clay" />
            <div>
              <h2
                id="node-config-title"
                className="text-[17px] font-semibold text-b-text"
                style={{ fontFamily: "var(--b-font-heading)" }}
              >
                Configure Step
              </h2>
              <p className="font-mono text-[11px] text-b-text-dim">{stepName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="btn btn-ghost rounded-b-sm p-2"
            aria-label="Close configuration panel"
          >
            <X aria-hidden="true" className="h-5 w-5 text-b-text-mid" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {/* Model Selection */}
          <div>
            <label htmlFor="node-config-model" className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim mb-2">
              Model
            </label>
            <select
              id="node-config-model"
              ref={firstFocusableRef}
              value={config.model || ""}
              onChange={(e) => handleConfigChange("model", e.target.value)}
              className="w-full rounded-b-sm border border-b-line bg-b-bg0 px-4 py-2 text-sm text-b-text focus:border-b-clay focus:ring-1 focus:ring-b-clay/50 transition-colors"
            >
              <option value="">Use Default (tier-based)</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-b-text-dim">
              Leave empty to use default model for this agent tier
            </p>
          </div>

          {/* System Prompt */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label htmlFor="node-config-system-prompt" className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">
                System Prompt / Instructions
              </label>
              {config.system_prompt && (
                <button
                  onClick={handleCopyPrompt}
                  type="button"
                  className="inline-flex items-center gap-1 rounded-b-sm px-2 py-1 text-xs text-b-text-mid hover:bg-b-bg2 transition-colors"
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
              className="w-full rounded-b-sm border border-b-line bg-b-bg0 px-4 py-2 text-sm font-mono text-b-text focus:border-b-clay focus:ring-1 focus:ring-b-clay/50 transition-colors resize-none"
            />
            <p className="mt-1 text-xs text-b-text-dim">
              Override the system prompt for this agent
            </p>
          </div>

          {/* Generation Parameters */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* Temperature */}
            <div>
              <label htmlFor="node-config-temperature" className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim mb-2">
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
                className="w-full rounded-b-sm border border-b-line bg-b-bg0 px-3 py-2 text-sm text-b-text focus:border-b-clay focus:ring-1 focus:ring-b-clay/50 transition-colors"
              />
              <p className="mt-1 text-xs text-b-text-dim">
                0.0 (deterministic) - 2.0 (creative)
              </p>
            </div>

            {/* Max Tokens */}
            <div>
              <label htmlFor="node-config-max-tokens" className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim mb-2">
                Max Tokens
              </label>
              <input
                id="node-config-max-tokens"
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
                className="w-full rounded-b-sm border border-b-line bg-b-bg0 px-3 py-2 text-sm text-b-text focus:border-b-clay focus:ring-1 focus:ring-b-clay/50 transition-colors"
              />
              <p className="mt-1 text-xs text-b-text-dim">Maximum response length</p>
            </div>

            {/* Top P */}
            <div>
              <label htmlFor="node-config-top-p" className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim mb-2">
                Top P
              </label>
              <input
                id="node-config-top-p"
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
                className="w-full rounded-b-sm border border-b-line bg-b-bg0 px-3 py-2 text-sm text-b-text focus:border-b-clay focus:ring-1 focus:ring-b-clay/50 transition-colors"
              />
              <p className="mt-1 text-xs text-b-text-dim">
                Nucleus sampling (0.0 - 1.0)
              </p>
            </div>
          </div>

          {/* Tools Selection */}
          {availableTools.length > 0 && (
            <fieldset>
              <legend className="block font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim mb-2">
                Available Tools
              </legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {availableTools.map((tool) => (
                  <label
                    key={tool}
                    className="flex items-center gap-2 rounded-b-sm border border-b-line bg-b-bg0 px-3 py-2 cursor-pointer hover:bg-b-bg2 transition-colors"
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
                      className="rounded-b-sm border-b-line"
                    />
                    <span className="font-mono text-[11px] text-b-text-mid">{tool}</span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-b-text-dim">
                Select which tools this agent can use
              </p>
            </fieldset>
          )}

          {/* Info Box */}
          <div className="rounded-b-sm border border-b-blue/40 bg-b-blue/10 p-3">
            <p className="font-mono text-[11px] text-b-blue">
              <strong>Note:</strong> Configuration changes are applied immediately
              to the next execution of this step. Changes persist for the entire
              workflow run.
            </p>
          </div>
        </div>

        {/* Footer / Actions */}
        <div className="flex-shrink-0 border-t border-b-line bg-b-bg2 px-6 py-4 flex items-center justify-between">
          <button
            onClick={handleReset}
            type="button"
            disabled={!hasChanges}
            className="btn btn-ghost inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RotateCcw className="h-4 w-4" />
            Reset
          </button>

          <div className="flex gap-2">
            <button
              onClick={onClose}
              type="button"
              className="btn btn-ghost"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              type="button"
              disabled={!hasChanges}
              className="btn btn-primary inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
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
