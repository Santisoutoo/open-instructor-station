/**
 * The AI Traffic panel: bridge gate banner, one-tap spawn grid, live active list.
 *
 * The whole panel sits behind one gate (feature-spec §13): traffic is the only manager
 * that needs the in-sim bridge plugin, so when the bridge is absent every control
 * disables — stated, never hidden. The mock manifest reports the bridge as
 * `connected (demo)`; flipping `TRAFFIC_AVAILABLE` in `mock.ts` demos the gated state.
 *
 * Spawned entities live in the RTK Query cache (`getActiveTraffic`), not here, so they
 * survive tab switches; the movement hook advances them once a second while the panel
 * is open and something is flying.
 */

import { ActiveTrafficList } from './ActiveTrafficList';
import { SpawnGrid } from './SpawnGrid';
import { type TrafficGate, trafficGate } from './gate';
import { useGetActiveTrafficQuery, useGetTrafficManifestQuery } from './trafficApi';
import type { TrafficManifest } from './types.mock';
import { useTrafficMovement } from './useTrafficMovement';
import './traffic.css';

function BridgeBanner({
  manifest,
  gate,
}: {
  manifest: TrafficManifest | undefined;
  gate: TrafficGate;
}) {
  return (
    <div
      className={gate.open ? 'traffic-bridge traffic-bridge--open' : 'traffic-bridge'}
    >
      <span className="traffic-bridge__dot" aria-hidden="true" />
      <span className="traffic-bridge__label">Bridge</span>
      <span className="traffic-bridge__state">{manifest?.bridge ?? 'unknown'}</span>
      {!gate.open && <span className="traffic-bridge__reason">{gate.reason}</span>}
    </div>
  );
}

export function TrafficPanel() {
  const { data: manifest, isError } = useGetTrafficManifestQuery();
  const { data: active } = useGetActiveTrafficQuery();
  const gate = trafficGate(manifest, isError);
  const entities = active ?? [];

  useTrafficMovement(gate.open && entities.length > 0);

  return (
    <section className="panel traffic-panel" aria-labelledby="traffic-heading">
      <h2 id="traffic-heading">Traffic</h2>

      <BridgeBanner manifest={manifest} gate={gate} />

      <SpawnGrid disabled={!gate.open} />

      <ActiveTrafficList entities={entities} disabled={!gate.open} />
    </section>
  );
}
