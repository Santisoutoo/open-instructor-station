import { CapabilityList } from './CapabilityList';
import { TelemetryPanel } from './TelemetryPanel';

/**
 * The right-edge context drawer: full telemetry readouts and the adapter's capability
 * list, exactly the panels the Phase 0/1 shell showed beside the workspace. Docked on a
 * desk, overlaying on a tablet; the header's Context button shows and hides it.
 */
export function ContextDrawer() {
  return (
    <aside className="drawer" aria-label="Telemetry and capabilities">
      <TelemetryPanel />
      <CapabilityList />
    </aside>
  );
}
