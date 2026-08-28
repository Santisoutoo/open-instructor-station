/**
 * The right rail: what will be applied, what to watch out for, and where the numbers come
 * from.
 *
 * Every value is the server's — `POST /api/position/preview` resolved the geometry and said
 * in `notes` where each figure came from, and the rail renders those notes verbatim so an
 * instructor can tell a charted altitude from a category default. The old "sample data" tag
 * is gone with the sample data.
 */

import { useAppSelector } from '../../store';
import { airacLabel } from './gate';
import { applyRows } from './applyRows';
import { checks } from './checks';
import { errorMessage } from './errors';
import { formatMetar } from '../map/metar';
import {
  useGroundElevationFt,
  useIls,
  useLoadedIcao,
  useSelectedRunway,
  useStagedPlacement,
  useWeather,
  tailwindOn,
} from './usePositionData';
import { useGetNavdataStatusQuery } from '../../api/instructorApi';

export function ApplyRail() {
  const design = useAppSelector((state) => state.positionDesign);
  const icao = useLoadedIcao();
  const runway = useSelectedRunway();
  const { hasIls } = useIls(runway?.ident ?? null);
  const { wind, weather } = useWeather();
  const { preview, merged, setup, isError, error, isFetching } = useStagedPlacement();
  const { data: status } = useGetNavdataStatusQuery();
  const groundElevationFt = useGroundElevationFt();

  const rows = applyRows({ preview, merged, overridden: setup.overridden });
  const checkList = checks({
    runwayIdent: runway?.ident ?? null,
    reciprocalIdent: runway?.opposite_ident ?? null,
    tailwindKt: tailwindOn(runway, wind),
    hasIls,
    sendIls: design.send.ilsFrequency,
    standName: design.selectedStand,
    activeTab: design.activeTab,
    marker: design.selectedMarker,
    finalPlacement: design.finalPlacement,
    markerDistances: design.markerDistances,
    gearDown: merged.gear_down ?? null,
    iasKt: merged.ias_kt ?? preview?.placement.ias_kt ?? null,
    altitudeFt: merged.altitude_ft ?? preview?.placement.position.altitude_ft ?? null,
    groundElevationFt,
    altitudeOverride: design.config.altitudeOverride,
    altitudeOverrideFt: design.config.altitudeOverrideFt,
  });

  const airac = airacLabel(status);
  const provider = status?.provider ?? 'unknown provider';

  return (
    <aside className="pos-rail" aria-label="Will be applied">
      <div className="pos-rail__head">
        <h2 className="pos-rail__title">Will be applied</h2>
        {isFetching && <span className="pos-tag">resolving…</span>}
      </div>

      {isError && (
        <p className="pos-rail__error">
          {errorMessage(error, 'This placement could not be worked out.')}
        </p>
      )}

      <ul className="pos-rail__rows">
        {rows.map((row) => (
          <li key={row.label} className="pos-rail__row">
            <span className="pos-rail__row-label">{row.label}</span>
            <span
              className={
                row.colour === 'caution'
                  ? 'pos-mono pos-rail__row-value pos-rail__row-value--caution'
                  : row.colour === 'dim'
                    ? 'pos-mono pos-rail__row-value pos-rail__row-value--dim'
                    : 'pos-mono pos-rail__row-value'
              }
            >
              {row.value}
            </span>
            <span
              className={
                row.colour === 'caution'
                  ? 'pos-rail__row-tag pos-rail__row-tag--caution'
                  : 'pos-rail__row-tag'
              }
            >
              {row.tag}
            </span>
          </li>
        ))}
      </ul>

      {preview !== undefined && preview.notes.length > 0 && (
        <ul className="pos-rail__notes" aria-label="Where these numbers came from">
          {preview.notes.map((note) => (
            <li key={note} className="pos-rail__note">
              {note}
            </li>
          ))}
        </ul>
      )}

      <div className="pos-rail__checks">
        <h3 className="pos-rail__checks-title">Checks</h3>
        {checkList.length === 0 ? (
          <p className="pos-rail__check-note">Nothing to flag on this placement.</p>
        ) : (
          <ul className="pos-rail__checks-list">
            {checkList.map((check, index) => (
              <li key={`${check.text}-${String(index)}`} className="pos-rail__check">
                <span className={`pos-dot pos-dot--${check.dot}`} aria-hidden="true" />
                <div className="pos-rail__check-body">
                  <p className="pos-rail__check-text">{check.text}</p>
                  <p className="pos-rail__check-note">{check.note}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="pos-rail__footer">
        {weather === undefined ? (
          <p className="pos-rail__metar pos-mono">no commanded weather</p>
        ) : (
          <p className="pos-mono pos-rail__metar">
            {icao === '' ? '' : `${icao} `}
            {formatMetar(weather)}
          </p>
        )}
        <p className="pos-rail__footer-note">
          Navdata {provider}
          {airac === null ? '' : ` · ${airac}`} · commanded weather, not an observation
        </p>
      </div>
    </aside>
  );
}
