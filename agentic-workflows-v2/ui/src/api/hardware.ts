/**
 * Hardware profile-override wire contract — /api/model-finder/profile-override.
 *
 * The model finder normally derives a SystemProfile from live hardware
 * detection. A HardwareOverride lets the user pin selected fields (RAM, CPU,
 * TOPS, accelerators) so recommendations can be previewed for a different
 * machine. Every field is optional; omitted/null fields fall back to the
 * detected value.
 *
 * Endpoints (backend half implemented separately — keep shapes in sync):
 *   GET    /api/model-finder/profile-override -> { override: HardwareOverride | null }
 *   PUT    /api/model-finder/profile-override (body: HardwareOverride)
 *            -> { profile: SystemProfile, override: HardwareOverride }
 *   DELETE /api/model-finder/profile-override
 *            -> { profile: SystemProfile, override: null }
 */

import type { SystemProfile } from "./types";

/** One overridden accelerator (GPU/NPU) entry. */
export interface HardwareAcceleratorOverride {
  kind: "gpu" | "npu";
  name: string;
  memory_gb?: number | null;
  vendor?: string | null;
  tops?: number | null;
}

/** Sparse hardware override — only set fields replace detected values. */
export interface HardwareOverride {
  cpu_name?: string | null;
  cpu_cores_logical?: number | null;
  cpu_cores_physical?: number | null;
  cpu_max_mhz?: number | null;
  ram_gb?: number | null;
  system_tops?: number | null;
  accelerators?: HardwareAcceleratorOverride[] | null;
}

/** GET response — the persisted override, if any. */
export interface HardwareOverrideGetResponse {
  override: HardwareOverride | null;
}

/** PUT response — the re-derived profile plus the accepted override. */
export interface HardwareOverrideUpdateResponse {
  profile: SystemProfile;
  override: HardwareOverride;
}

/** DELETE response — the re-derived (detected) profile, override cleared. */
export interface HardwareOverrideClearResponse {
  profile: SystemProfile;
  override: null;
}
