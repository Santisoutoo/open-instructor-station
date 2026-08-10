import { CapabilityList } from './components/CapabilityList';
import { ConnectionBadge } from './components/ConnectionBadge';
import { TelemetryPanel } from './components/TelemetryPanel';
import { AircraftControlPanel } from './features/aircraft/AircraftControlPanel';
import { PositionPanel } from './features/position/PositionPanel';
import { useTelemetrySocket } from './features/telemetry/useTelemetrySocket';

/**
 * Shell of the instructor station.
 *
 * The Position panel is the workspace and takes the left two thirds; telemetry and
 * capabilities sit beside it as context, and the whole thing reflows to one column on a
 * tablet held in portrait. That split is the signal-to-noise decision for this surface:
 * placing the aircraft is the job, everything else is there to confirm it worked.
 *
 * The remaining feature panels (weather, failures, traffic, map) land in later phases and
 * each one plugs in here without touching the others.
 */
export default function App() {
  // Single owner of the telemetry WebSocket for the whole app.
  useTelemetrySocket();

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__title">
          <h1>Open Instructor Station</h1>
          <p className="app__subtitle">Phase 1 — position and aircraft control</p>
        </div>
        <ConnectionBadge />
      </header>

      <main className="app__main">
        <div className="app__workspace">
          <PositionPanel />
          <AircraftControlPanel />
        </div>
        <aside className="app__context">
          <TelemetryPanel />
          <CapabilityList />
        </aside>
      </main>

      <footer className="app__footer">
        External instructor station — the simulator is never touched directly.
      </footer>
    </div>
  );
}
