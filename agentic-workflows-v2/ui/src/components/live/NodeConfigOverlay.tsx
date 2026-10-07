import { useState, useCallback, useEffect, useId, useRef } from "react";
import {
  X,
  Save,
  RotateCcw,
  Copy,
  Settings2,
} from "lucide-react";
import { Button } from "../ui/button";
import { useApiAvailability } from "../../hooks/useApiAvailability";

/** Shared field chrome: 4px radius, hairline, surface fill, AA focus ring. */
const FIELD_CLASS =
  "focus-ring w-full rounded-md border border-el-control-border bg-el-surface py-2 text-sm text-el-ink transition-colors focus:border-el-focus";

/** Field label: small tracked overline above the control. */
const LABEL_CLASS =
  "mb-2 block font-mono text-micro uppercase tracking-[0.5px] text-el-muted";

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

/**
 * Stable default: the reset effect below keys on initialConfig's identity, so
 * a fresh `{}` per render would wipe every pending edit on the next render.
 */
const EMPTY_CONFIG: NodeConfig = {};

export default function NodeConfigOverlay({
  stepName,
  isOpen,
  onClose,
  initialConfig = EMPTY_CONFIG,
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
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiDownReasonId = useId();
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
        className="absolute inset-0 cursor-default border-0 bg-el-ink/25 backdrop-blur-[1px] dark:bg-el-canvas/75"
        aria-label="Close configuration overlay"
        onClick={onClose}
      />

      {/* Overlay Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="node-config-title"
        className="relative flex h-screen max-h-screen w-full max-w-2xl flex-col overflow-hidden border-l border-el-divider bg-el-raised shadow-(--el-shadow-raised)"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-el-divider bg-el-subtle px-6 py-4">
          <div className="flex items-center gap-3">
            <Settings2 aria-hidden="true" className="h-5 w-5 text-el-secondary" />
            <div>
              <h2
                id="node-config-title"
                className="font-display text-[17px] font-semibold text-el-ink"
              >
                Configure Step
              </h2>
              <p className="font-mono text-micro text-el-secondary">{stepName}</p>
            </div>
          </div>
          <Button
            onClick={onClose}
            type="button"
            variant="ghost"
            size="icon"
            className="rounded-md text-el-secondary hover:text-el-ink"
            aria-label="Close configuration panel"
          >
            <X aria-hidden="true" />
          </Button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {/* Model Selection */}
          <div>
            <label htmlFor="node-config-model" className={LABEL_CLASS}>
              Model
            </label>
            <select
              id="node-config-model"
              ref={firstFocusableRef}
              value={config.model || ""}
              onChange={(e) => handleConfigChange("model", e.target.value)}
              className={`${FIELD_CLASS} px-4`}
            >
              <option value="">Use Default (tier-based)</option>
              {availableModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-el-muted">
              Leave empty to use default model for this agent tier
            </p>
          </div>

          {/* System Prompt */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label htmlFor="node-config-system-prompt" className="block font-mono text-micro uppercase tracking-[0.5px] text-el-muted">
                System Prompt / Instructions
              </label>
              {config.system_prompt && (
                <button
                  onClick={handleCopyPrompt}
                  type="button"
                  className="focus-ring inline-flex min-h-9 items-center gap-1 rounded-md px-2 text-xs text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink"
                  title="Copy prompt to clipboard"
                >
                  <Copy aria-hidden="true" className="h-3 w-3" />
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
              className={`${FIELD_CLASS} resize-none px-4 font-mono`}
            />
            <p className="mt-1 text-xs text-el-muted">
              Override the system prompt for this agent
            </p>
          </div>

          {/* Generation Parameters */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* Temperature */}
            <div>
              <label htmlFor="node-config-temperature" className={LABEL_CLASS}>
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
                className={`${FIELD_CLASS} px-3`}
              />
              <p className="mt-1 text-xs text-el-muted">
                0.0 (deterministic) - 2.0 (creative)
              </p>
            </div>

            {/* Max Tokens */}
            <div>
              <label htmlFor="node-config-max-tokens" className={LABEL_CLASS}>
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
                className={`${FIELD_CLASS} px-3`}
              />
              <p className="mt-1 text-xs text-el-muted">Maximum response length</p>
            </div>

            {/* Top P */}
            <div>
              <label htmlFor="node-config-top-p" className={LABEL_CLASS}>
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
                className={`${FIELD_CLASS} px-3`}
              />
              <p className="mt-1 text-xs text-el-muted">
                Nucleus sampling (0.0 - 1.0)
              </p>
            </div>
          </div>

          {/* Tools Selection */}
          {availableTools.length > 0 && (
            <fieldset>
              <legend className={LABEL_CLASS}>
                Available Tools
              </legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {availableTools.map((tool) => (
                  <label
                    key={tool}
                    className="flex min-h-9 cursor-pointer items-center gap-2 rounded-md border border-el-divider bg-el-surface px-3 py-2 transition-colors hover:bg-el-hover"
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
                      className="focus-ring rounded-sm border-el-divider accent-el-action"
                    />
                    <span className="font-mono text-micro text-el-secondary">{tool}</span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-el-muted">
                Select which tools this agent can use
              </p>
            </fieldset>
          )}

          {/* Info Box */}
          <div className="rounded-md border border-el-info/40 bg-el-info-soft p-3">
            <p className="font-mono text-micro text-el-info">
              <strong>Note:</strong> Configuration changes are applied immediately
              to the next execution of this step. Changes persist for the entire
              workflow run.
            </p>
          </div>
        </div>

        {/* Footer / Actions */}
        <div className="shrink-0 border-t border-el-divider bg-el-subtle px-6 py-4">
          <div className="flex items-center justify-between gap-2">
            <Button
              onClick={handleReset}
              type="button"
              variant="outline"
              disabled={!hasChanges}
              className="rounded-md"
            >
              <RotateCcw aria-hidden="true" />
              Reset
            </Button>

            <div className="flex gap-2">
              <Button
                onClick={onClose}
                type="button"
                variant="ghost"
                className="rounded-md"
              >
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                type="button"
                disabled={!hasChanges || apiDown}
                aria-describedby={apiDown ? apiDownReasonId : undefined}
                className="rounded-md bg-el-action text-el-action-ink"
              >
                <Save aria-hidden="true" />
                Save & Apply
              </Button>
            </div>
          </div>
          {apiDown && (
            <p
              id={apiDownReasonId}
              className="mt-2 text-right text-micro text-el-muted"
            >
              {apiDownReason}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
