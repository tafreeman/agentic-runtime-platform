import ProviderPanel from "../components/settings/ProviderPanel";
import TierBoard from "../components/settings/TierBoard";

/**
 * Settings — provider endpoint management (which backends exist, how they
 * authenticate) and per-tier model routing order + capability tags.
 */
export default function SettingsPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-[18px] p-6">
          <div>
            <h1
              className="text-[24px] font-semibold text-b-text"
              style={{ fontFamily: "var(--b-font-heading)", letterSpacing: "-0.5px" }}
            >
              Settings
            </h1>
            <div className="mt-1 font-mono text-[11px] text-b-text-dim">
              $ provider endpoints · tier routing order · capability tags
            </div>
          </div>

          <ProviderPanel />
          <TierBoard />
        </div>
      </div>
    </div>
  );
}
