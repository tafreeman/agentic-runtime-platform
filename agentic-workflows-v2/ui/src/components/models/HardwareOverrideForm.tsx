import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteHardwareOverride,
  getHardwareOverride,
  putHardwareOverride,
} from "../../api/client";
import type {
  HardwareAcceleratorOverride,
  HardwareOverride,
} from "../../api/hardware";

// Inline "[edit specs]" form for the SYSTEM PROFILE section — lets the user
// pin RAM/CPU/TOPS/accelerator values so recommendations can be previewed for
// hardware other than what was auto-detected. Saving PUTs the sparse override
// and invalidates the recommendation + probe queries so the page re-derives.

const CARD_STYLE = {
  borderWidth: "var(--b-bw)",
  borderRadius: "var(--b-rad-lg)",
} as const;
const FIELD_CLASS =
  "w-full border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:border-b-clay focus:outline-none";
const FIELD_STYLE = { borderRadius: "var(--b-rad-sm)" } as const;
const CAPTION_LABEL =
  "mb-1 block font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint";

/** Parse a numeric field: empty → null, non-numeric → null (field ignored). */
function toNumberOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** Parse an integer field: empty/non-numeric → null. */
function toIntOrNull(raw: string): number | null {
  const value = toNumberOrNull(raw);
  return value === null ? null : Math.trunc(value);
}

/** Numeric value → editable string ("" when unset). */
function numToField(value: number | null | undefined): string {
  return value == null ? "" : String(value);
}

interface HardwareOverrideFieldsProps {
  readonly initial: HardwareOverride | null;
  readonly onClose: () => void;
}

function HardwareOverrideFields({
  initial,
  onClose,
}: HardwareOverrideFieldsProps) {
  const queryClient = useQueryClient();
  const initialAccelerator = initial?.accelerators?.[0] ?? null;

  const [ramGb, setRamGb] = useState(numToField(initial?.ram_gb));
  const [cpuCores, setCpuCores] = useState(
    numToField(initial?.cpu_cores_logical),
  );
  const [cpuName, setCpuName] = useState(initial?.cpu_name ?? "");
  const [systemTops, setSystemTops] = useState(numToField(initial?.system_tops));
  const [accelKind, setAccelKind] = useState<"gpu" | "npu">(
    initialAccelerator?.kind ?? "gpu",
  );
  const [accelName, setAccelName] = useState(initialAccelerator?.name ?? "");
  const [accelMemory, setAccelMemory] = useState(
    numToField(initialAccelerator?.memory_gb),
  );
  const [accelTops, setAccelTops] = useState(numToField(initialAccelerator?.tops));

  // Both mutations change what the recommendation scorer and the probe see,
  // so both server-derived queries are invalidated on success.
  const invalidateDerived = () => {
    void queryClient.invalidateQueries({ queryKey: ["model-recommendations"] });
    void queryClient.invalidateQueries({ queryKey: ["model-probe"] });
    void queryClient.invalidateQueries({ queryKey: ["hardware-override"] });
  };

  const saveMutation = useMutation({
    mutationFn: (body: HardwareOverride) => putHardwareOverride(body),
    onSuccess: () => {
      invalidateDerived();
      onClose();
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => deleteHardwareOverride(),
    onSuccess: () => {
      invalidateDerived();
      onClose();
    },
  });

  const busy = saveMutation.isPending || clearMutation.isPending;
  const mutationError = saveMutation.error ?? clearMutation.error;

  const handleSave = () => {
    const cores = toIntOrNull(cpuCores);
    const ram = toNumberOrNull(ramGb);
    const tops = toNumberOrNull(systemTops);
    const name = cpuName.trim();
    const acceleratorName = accelName.trim();
    const acceleratorMemory = toNumberOrNull(accelMemory);
    const acceleratorTops = toNumberOrNull(accelTops);
    const accelerator: HardwareAcceleratorOverride | null =
      acceleratorName === ""
        ? null
        : {
            kind: accelKind,
            name: acceleratorName,
            ...(acceleratorMemory !== null
              ? { memory_gb: acceleratorMemory }
              : {}),
            ...(acceleratorTops !== null ? { tops: acceleratorTops } : {}),
          };
    const override: HardwareOverride = {
      ...(name !== "" ? { cpu_name: name } : {}),
      ...(cores !== null ? { cpu_cores_logical: cores } : {}),
      ...(ram !== null ? { ram_gb: ram } : {}),
      ...(tops !== null ? { system_tops: tops } : {}),
      ...(accelerator !== null ? { accelerators: [accelerator] } : {}),
    };
    saveMutation.mutate(override);
  };

  return (
    <div
      data-testid="hardware-override-form"
      className="border-b-line bg-b-bg1 p-4"
      style={CARD_STYLE}
    >
      <div className="mb-3 font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint">
        HARDWARE OVERRIDE · pins these values over live detection
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className={CAPTION_LABEL}>ram (gb)</span>
          <input
            type="number" min="0" step="1"
            data-testid="spec-ram-gb" aria-label="Override RAM in GB"
            value={ramGb}
            onChange={(event) => setRamGb(event.target.value)}
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>cpu threads</span>
          <input
            type="number" min="0" step="1"
            data-testid="spec-cpu-cores" aria-label="Override logical CPU cores"
            value={cpuCores}
            onChange={(event) => setCpuCores(event.target.value)}
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>cpu name</span>
          <input
            type="text"
            data-testid="spec-cpu-name" aria-label="Override CPU name"
            value={cpuName}
            onChange={(event) => setCpuName(event.target.value)}
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>system tops</span>
          <input
            type="number" min="0" step="0.1"
            data-testid="spec-system-tops" aria-label="Override system TOPS"
            value={systemTops}
            onChange={(event) => setSystemTops(event.target.value)}
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className={CAPTION_LABEL}>accelerator kind</span>
          <select
            data-testid="spec-accel-kind" aria-label="Override accelerator kind"
            value={accelKind}
            onChange={(event) =>
              setAccelKind(event.target.value === "npu" ? "npu" : "gpu")
            }
            className={FIELD_CLASS} style={FIELD_STYLE}
          >
            <option value="gpu">gpu</option>
            <option value="npu">npu</option>
          </select>
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>accelerator name</span>
          <input
            type="text"
            data-testid="spec-accel-name" aria-label="Override accelerator name"
            value={accelName}
            onChange={(event) => setAccelName(event.target.value)}
            placeholder="leave empty for none"
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>accel memory (gb)</span>
          <input
            type="number" min="0" step="1"
            data-testid="spec-accel-memory" aria-label="Override accelerator memory in GB"
            value={accelMemory}
            onChange={(event) => setAccelMemory(event.target.value)}
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>accel tops</span>
          <input
            type="number" min="0" step="0.1"
            data-testid="spec-accel-tops" aria-label="Override accelerator TOPS"
            value={accelTops}
            onChange={(event) => setAccelTops(event.target.value)}
            className={FIELD_CLASS} style={FIELD_STYLE}
          />
        </label>
      </div>

      {mutationError && (
        <div
          role="alert"
          className="mt-3 font-mono text-[10px] text-b-red"
        >
          failed to update hardware override: {mutationError.message}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="save-specs"
          aria-label="Save hardware override"
          onClick={handleSave}
          disabled={busy}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          save
        </button>
        <button
          type="button"
          data-testid="clear-specs"
          aria-label="Clear hardware override"
          onClick={() => clearMutation.mutate()}
          disabled={busy}
          className="btn-ghost disabled:cursor-not-allowed disabled:opacity-50"
        >
          clear override
        </button>
        <button
          type="button"
          aria-label="Cancel editing hardware specs"
          onClick={onClose}
          disabled={busy}
          className="btn-ghost disabled:cursor-not-allowed disabled:opacity-50"
        >
          cancel
        </button>
      </div>
    </div>
  );
}

interface HardwareOverrideFormProps {
  readonly onClose: () => void;
}

/**
 * Loads the persisted override, then hands off to the editable fields.
 * Rendering the fields only after the GET settles lets useState initializers
 * prefill from the fetched values without effect-based state adoption.
 */
export default function HardwareOverrideForm({
  onClose,
}: HardwareOverrideFormProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["hardware-override"],
    queryFn: getHardwareOverride,
  });

  if (isLoading) {
    return (
      <div
        className="border-b-line bg-b-bg1 p-4 font-mono text-[10px] text-b-text-dim"
        style={CARD_STYLE}
      >
        loading hardware override…
      </div>
    );
  }
  if (error) {
    return (
      <div
        role="alert"
        className="border-b-red/40 bg-b-bg1 p-4 font-mono text-[11px] text-b-red"
        style={CARD_STYLE}
      >
        failed to load hardware override: {error.message}
      </div>
    );
  }
  return (
    <HardwareOverrideFields initial={data?.override ?? null} onClose={onClose} />
  );
}
