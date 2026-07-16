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
        <div className="mx-auto max-w-6xl space-y-8 p-6">
          <div>
            <h1 className="font-display text-[36px] font-medium text-el-ink">Provider and tier settings</h1>
            <p className="mt-2 text-[14px] text-el-muted">Compatibility surface; production navigation consolidates this work under Models.</p>
          </div>
          <ProviderPanel />
          <TierBoard />
        </div>
      </div>
    </div>
  );
}
