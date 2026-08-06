import { useGetCapabilitiesQuery } from '../api/instructorApi';
import { CAPABILITY_LABELS } from '../api/types';

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
