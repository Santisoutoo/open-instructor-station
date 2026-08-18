/**
 * The map's METAR chip: the COMMANDED weather formatted METAR-style (instructor-map.md
 * §7.9, D10). Never a live internet fetch — its one source is the Weather Manager's
 * `GET /api/weather`, read through that manager's own RTK Query surface, and the chip says
 * so on its face so an instructor never mistakes a manually-set CAT III fog for what is
 * actually happening outside the window.
 *
 * Fails closed, hard rule 3 style: it renders NOTHING — not a disabled shell — unless the
 * adapter declares `can_set_weather` and the weather read succeeded. The weather query is
 * skipped outright until the capability is known-true, because `GET /api/weather` itself
 * 501s without it (the same reasoning as `features/weather/gate.ts`), and "I could not find
 * out" counts as unsupported: a capabilities error keeps the chip absent too.
 *
 * Not mounted anywhere yet: the overlays track (#113) owns `MapPanel.tsx` this wave and
 * mounts the chip next to its reference-airport picker.
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { useGetWeatherStateQuery } from '../weather/weatherApi';
import { formatMetar } from './metar';
import './metar.css';

export function MetarChip() {
  const { data: capabilities } = useGetCapabilitiesQuery();
  const supported = capabilities?.can_set_weather === true;
  const { data: weather, isError: weatherFailed } = useGetWeatherStateQuery(undefined, {
    skip: !supported,
  });

  if (!supported || weatherFailed || weather === undefined) {
    return null;
  }

  return (
    <p className="map-metar" role="note" aria-label="Commanded weather">
      <span className="map-metar__string">{formatMetar(weather)}</span>
      <span className="map-metar__source">commanded weather — not a live observation</span>
    </p>
  );
}
