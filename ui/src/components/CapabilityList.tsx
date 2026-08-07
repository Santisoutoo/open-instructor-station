import { useGetCapabilitiesQuery } from '../api/instructorApi';
import type { CapabilityKey } from '../api/models';

/**
 * Display order and human labels for the capability flags.
 *
 * Lives next to the component that renders it, not in `api/`: the *flags* are generated
 * from the OpenAPI schema, but how they are worded and ordered on screen is a display
 * decision. `CapabilityKey` keeps the two honest — a flag renamed on the server breaks
 * this table at compile time.
 */
const CAPABILITY_LABELS: ReadonlyArray<readonly [CapabilityKey, string]> = [
  ['can_set_position', 'Set position'],
  ['can_set_aircraft_state', 'Set aircraft state'],
  ['can_set_weather', 'Set weather'],
  ['can_inject_failures', 'Inject failures'],
  ['can_spawn_traffic', 'Spawn traffic'],
  ['can_control_autopilot', 'Control autopilot'],
  ['can_set_fuel_payload', 'Set fuel & payload'],
  ['can_control_camera', 'Control camera'],
  ['can_pushback', 'Pushback'],
];

/**
 * Renders `GET /api/capabilities`, one row per flag.
 *
 * This is the visible proof of hard rule 3, "capabilities, not failures": what the active
 * adapter cannot do is rendered disabled here, and the corresponding panels stay switched
 * off. Nothing in the UI is allowed to call an unsupported endpoint and let it throw.
 *
 * While the flags are unknown (loading or unreachable server) everything is treated as
 * unsupported — failing closed is the safe direction.
 */
export function CapabilityList() {
  const { data, isLoading, isError, error } = useGetCapabilitiesQuery();

  return (
    <section className="panel" aria-labelledby="capabilities-heading">
      <h2 id="capabilities-heading">Adapter capabilities</h2>

      {isLoading && <p className="panel__empty">Querying the adapter…</p>}
      {isError && (
        <p className="panel__error" role="alert">
          Capabilities unavailable — every feature stays disabled.
          {typeof error === 'object' && 'status' in error
            ? ` (${String(error.status)})`
            : null}
        </p>
      )}

      <ul className="capabilities">
        {CAPABILITY_LABELS.map(([key, label]) => {
          const supported = data?.[key] ?? false;
          return (
            <li
              key={key}
              className={`capability capability--${supported ? 'on' : 'off'}`}
              aria-disabled={!supported}
            >
              <span className="capability__indicator" aria-hidden="true">
                {supported ? '●' : '○'}
              </span>
              <span className="capability__label">{label}</span>
              <span className="capability__state">
                {supported ? 'Available' : 'Disabled'}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
