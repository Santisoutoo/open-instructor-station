/**
 * The map's METAR chip: the COMMANDED weather formatted METAR-style (instructor-map.md
 * §7.9, D10). Never a live internet fetch — its one source is the Weather Manager's
 * `GET /api/weather`, read through that manager's own RTK Query surface, and the chip says
 * so on its face so an instructor never mistakes a manually-set CAT III fog for what is
 * actually happening outside the window.
 *
 * Fails closed, hard rule 3 style, in two distinct postures (D10):
 *
 * - While the capabilities are loading or unreadable, or the weather read fails, it
 *   renders NOTHING — "I could not find out" earns no shell at all.
 * - When the capabilities are KNOWN and `can_set_weather` is false, it renders a
 *   *disabled* chip with the reason stated — hard rule 3's "disabled in the UI", D10's
 *   "disabled with a reason when can_set_weather is false thereafter".
 *
 * Either way the weather query is skipped outright until the capability is known-true,
 * because `GET /api/weather` itself 501s without it (the same reasoning as
 * `features/weather/gate.ts`).
 *
 * Mounted by `MapPanel.tsx` next to the reference-airport picker, which passes that
 * airport's elevation so cloud bases render AGL, real-METAR style; `null` (elevation
 * not known yet) leaves them MSL, the wire value verbatim.
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { useGetWeatherStateQuery } from '../weather/weatherApi';
import { formatMetar } from './metar';
import './metar.css';

export function MetarChip({
  fieldElevationFt = null,
}: {
  /** The reference airport's elevation, feet MSL, for AGL cloud bases. */
  fieldElevationFt?: number | null;
}) {
  const { data: capabilities } = useGetCapabilitiesQuery();
  const supported = capabilities?.can_set_weather === true;
  const { data: weather, isError: weatherFailed } = useGetWeatherStateQuery(undefined, {
    skip: !supported,
  });

  if (capabilities === undefined) {
    // Loading, or the capabilities themselves could not be read: no shell at all.
    return null;
  }

  if (!supported) {
    return (
      <p
        className="map-metar map-metar--disabled"
        role="note"
        aria-label="Commanded weather"
        aria-disabled="true"
      >
        <span className="map-metar__string">METAR unavailable</span>
        <span className="map-metar__source">
          This adapter does not declare can_set_weather, so there is no commanded weather
          to show.
        </span>
      </p>
    );
  }

  if (weatherFailed || weather === undefined) {
    return null;
  }

  return (
    <p className="map-metar" role="note" aria-label="Commanded weather">
      <span className="map-metar__string">{formatMetar(weather, fieldElevationFt)}</span>
      <span className="map-metar__source">commanded weather — not a live observation</span>
    </p>
  );
}
