import { CapabilityList } from './components/CapabilityList';
import { ConnectionBadge } from './components/ConnectionBadge';
import { TelemetryPanel } from './components/TelemetryPanel';
import { AircraftControlPanel } from './features/aircraft/AircraftControlPanel';
import { useTelemetrySocket } from './features/telemetry/useTelemetrySocket';

/**
 * Shell of the instructor station: header + live telemetry + adapter capabilities +
 * the Aircraft Control panel. The remaining feature panels (position, weather, failures,
 * traffic, map) land in later phases and each one plugs in here without touching the
 * others.
 */
export default function App() {
  // Single owner of the telemetry WebSocket for the whole app.
  useTelemetrySocket();

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__title">
          <h1>Open Instructor Station</h1>
          <p className="app__subtitle">Phase 1 — aircraft control</p>
        </div>
        <ConnectionBadge />
      </header>

      <main className="app__main">
        <TelemetryPanel />
        <CapabilityList />
        <AircraftControlPanel />
      </main>

      <footer className="app__footer">
        External instructor station — the simulator is never touched directly.
      </footer>
    </div>
  );
}
