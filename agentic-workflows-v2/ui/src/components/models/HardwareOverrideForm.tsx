import { useId, useState } from "react";
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
import { useApiAvailability } from "../../hooks/useApiAvailability";
import { describeApiError } from "../../lib/apiErrors";
import { Button } from "../ui/button";
import { apiErrorText } from "../common/apiErrorText";

// Inline "[edit specs]" form for the SYSTEM PROFILE section — lets the user
// pin RAM/CPU/TOPS/accelerator values so recommendations can be previewed for
// hardware other than what was auto-detected. Saving PUTs the sparse override
// and invalidates the recommendation + probe queries so the page re-derives.

const CARD_CLASS = "rounded-lg border border-el-divider bg-el-surface p-4";
const FIELD_CLASS =
  "h-10 w-full rounded-md border border-el-control-border bg-el-raised px-2.5 font-mono text-xs text-el-ink placeholder:text-el-faint focus-ring focus-visible:border-el-focus";
const CAPTION_LABEL = "mb-1 block text-xs font-medium text-el-secondary";

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

  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiDownHintId = useId();
  const busy = saveMutation.isPending || clearMutation.isPending;
  const mutationError = saveMutation.error ?? clearMutation.error;
  // Save / clear write to the API; cancel stays available.
  const mutationsDisabled = busy || apiDown;

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
    <div data-testid="hardware-override-form" className={CARD_CLASS}>
      <div className="mb-3">
        <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">Hardware override</h2>
        <p className="mt-0.5 text-xs text-el-muted">
          Pins these values over live detection. Leave a field empty to keep
          the detected value.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className={CAPTION_LABEL}>RAM (GB)</span>
          <input
            type="number" min="0" step="1"
            data-testid="spec-ram-gb" aria-label="Override RAM in GB"
            value={ramGb}
            onChange={(event) => setRamGb(event.target.value)}
            className={FIELD_CLASS}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>CPU threads</span>
          <input
            type="number" min="0" step="1"
            data-testid="spec-cpu-cores" aria-label="Override logical CPU cores"
            value={cpuCores}
            onChange={(event) => setCpuCores(event.target.value)}
            className={FIELD_CLASS}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>CPU name</span>
          <input
            type="text"
            data-testid="spec-cpu-name" aria-label="Override CPU name"
            value={cpuName}
            onChange={(event) => setCpuName(event.target.value)}
            className={FIELD_CLASS}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>System TOPS</span>
          <input
            type="number" min="0" step="0.1"
            data-testid="spec-system-tops" aria-label="Override system TOPS"
            value={systemTops}
            onChange={(event) => setSystemTops(event.target.value)}
            className={FIELD_CLASS}
          />
        </label>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className={CAPTION_LABEL}>Accelerator kind</span>
          <select
            data-testid="spec-accel-kind" aria-label="Override accelerator kind"
            value={accelKind}
            onChange={(event) =>
              setAccelKind(event.target.value === "npu" ? "npu" : "gpu")
            }
            className={FIELD_CLASS}
          >
            <option value="gpu">gpu</option>
            <option value="npu">npu</option>
          </select>
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>Accelerator name</span>
          <input
            type="text"
            data-testid="spec-accel-name" aria-label="Override accelerator name"
            value={accelName}
            onChange={(event) => setAccelName(event.target.value)}
            placeholder="leave empty for none"
            className={FIELD_CLASS}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>Accelerator memory (GB)</span>
          <input
            type="number" min="0" step="1"
            data-testid="spec-accel-memory" aria-label="Override accelerator memory in GB"
            value={accelMemory}
            onChange={(event) => setAccelMemory(event.target.value)}
            className={FIELD_CLASS}
          />
        </label>
        <label className="block">
          <span className={CAPTION_LABEL}>Accelerator TOPS</span>
          <input
            type="number" min="0" step="0.1"
            data-testid="spec-accel-tops" aria-label="Override accelerator TOPS"
            value={accelTops}
            onChange={(event) => setAccelTops(event.target.value)}
            className={FIELD_CLASS}
          />
        </label>
      </div>

      {mutationError && (
        <div role="alert" className="mt-3 text-xs text-el-danger">
          failed to update hardware override: {apiErrorText(mutationError)}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          data-testid="save-specs"
          aria-label="Save hardware override"
          aria-describedby={apiDown ? apiDownHintId : undefined}
          onClick={handleSave}
          disabled={mutationsDisabled}
        >
          Save
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          data-testid="clear-specs"
          aria-label="Clear hardware override"
          aria-describedby={apiDown ? apiDownHintId : undefined}
          onClick={() => clearMutation.mutate()}
          disabled={mutationsDisabled}
        >
          Clear
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label="Cancel editing hardware specs"
          onClick={onClose}
          disabled={busy}
        >
          Cancel
        </Button>
      </div>
      {apiDown && (
        <p id={apiDownHintId} className="mt-2 text-micro text-el-muted">
          Saving is unavailable: {apiDownReason}
        </p>
      )}
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
      <div className={`${CARD_CLASS} font-mono text-xs text-el-muted`}>
        loading hardware override…
      </div>
    );
  }
  if (error) {
    // Unreachable API: the shell banner already says so — keep this quiet.
    if (describeApiError(error).unreachable) {
      return (
        <div className={`${CARD_CLASS} font-mono text-xs text-el-muted`}>
          hardware override unavailable — {describeApiError(error).summary}
        </div>
      );
    }
    return (
      <div
        role="alert"
        className="rounded-lg border border-el-danger/40 bg-el-danger-soft p-4 font-mono text-xs text-el-danger"
      >
        failed to load hardware override: {apiErrorText(error)}
      </div>
    );
  }
  return (
    <HardwareOverrideFields initial={data?.override ?? null} onClose={onClose} />
  );
}
