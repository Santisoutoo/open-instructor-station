import { useAppSelector } from '../../store';
import { positionLine } from './format';
import { useDespawnAllTrafficMutation, useDespawnTrafficMutation } from './trafficApi';
import type { TrafficEntity } from './types.mock';

interface ActiveTrafficListProps {
  entities: TrafficEntity[];
  /** True while the traffic gate is closed — despawning also needs the bridge. */
  disabled: boolean;
}

/**
 * Everything currently spawned, one row per entity, with the relative position line
 * recomputed on every render — the movement hook rewrites the cache each second, so the
 * line is live. "Despawn all" is the biggest control here on purpose: when a scenario
 * goes wrong mid-lesson, clearing the sky is the action the instructor reaches for, and
 * it needs no confirmation because spawning it again is just as cheap.
 */
export function ActiveTrafficList({ entities, disabled }: ActiveTrafficListProps) {
  const latest = useAppSelector((state) => state.telemetry.latest);
  const [despawnTraffic] = useDespawnTrafficMutation();
  const [despawnAllTraffic] = useDespawnAllTrafficMutation();

  if (entities.length === 0) {
    return <p className="traffic-empty">No active traffic.</p>;
  }

  return (
    <div className="traffic-active">
      <div className="traffic-active-head">
        <span className="traffic-active-title">
          Active traffic
          <span className="traffic-active-count">{entities.length}</span>
        </span>
        <button
          type="button"
          className="traffic-despawn-all"
          disabled={disabled}
          onClick={() => void despawnAllTraffic()}
        >
          Despawn all
        </button>
      </div>
      <ul className="traffic-list">
        {entities.map((entity) => (
          <li key={entity.id} className="traffic-row">
            <span className="traffic-callsign">{entity.callsign}</span>
            <span className="traffic-kind">{entity.kind}</span>
            <span className="traffic-position">{positionLine(entity, latest)}</span>
            <button
              type="button"
              className="traffic-despawn"
              disabled={disabled}
              onClick={() => void despawnTraffic(entity.id)}
            >
              Despawn
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
