/**
 * Custom location: a coordinate, an altitude and a heading, sent as a
 * `CoordinatePlacementRequest`.
 *
 * **The mockup's "relative to the runway landing point" origin is offered and disabled**,
 * with the reason on screen — hard rule 3's "disabled in the UI, never left to throw". The
 * placement union has no bearing-and-distance-from-a-runway member, and working the
 * coordinate out here would mean geodesy in the browser, which is exactly what
 * `core.geodesy` exists to stop. If that placement is added server-side, this radio is one
 * line away from working.
 *
 * The fields fall back to the loaded airport's own position, elevation and the selected
 * runway's course until the instructor types over them, so the tab opens somewhere real
 * rather than at 0°N 0°E.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { FactRow } from './FactRow';
import {
  formatAltitudeFt,
  formatHeadingTrue,
  formatLatitude,
  formatLongitude,
} from './format';
import { customFieldChanged, customOriginSelected } from './positionDesignSlice';
import { useAirport, useSelectedRunway } from './usePositionData';

/** An empty box means "use the fallback"; anything else is the instructor's own number. */
function numberOrNull(raw: string): number | null {
  return raw.trim() === '' ? null : Number(raw);
}

export function CustomLocationTab() {
  const dispatch = useAppDispatch();
  const custom = useAppSelector((state) => state.positionDesign.custom);
  const { airport } = useAirport();
  const runway = useSelectedRunway();

  const latitude = custom.latitude ?? airport?.position.latitude ?? null;
  const longitude = custom.longitude ?? airport?.position.longitude ?? null;
  const altitudeFt = custom.altitudeFt ?? airport?.elevation_ft ?? null;
  const headingDeg = custom.headingDeg ?? runway?.true_bearing_deg ?? null;

  function change(field: 'altitudeFt' | 'headingDeg' | 'latitude' | 'longitude') {
    return (raw: string) => {
      dispatch(customFieldChanged({ field, value: numberOrNull(raw) }));
    };
  }

  return (
    <div
      id="pos-tabpanel-custom"
      role="tabpanel"
      aria-labelledby="pos-tab-custom"
      className="pos-customtab"
    >
      <div className="pos-customtab__row">
        <label className="pos-field">
          <span className="pos-field__label">Altitude (ft MSL)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            value={altitudeFt ?? ''}
            onChange={(event) => {
              change('altitudeFt')(event.target.value);
            }}
          />
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Heading (°T)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            value={headingDeg === null ? '' : Math.round(headingDeg)}
            onChange={(event) => {
              change('headingDeg')(event.target.value);
            }}
          />
        </label>
      </div>

      <div
        className="pos-customtab__origin"
        role="radiogroup"
        aria-label="Custom location origin"
      >
        <label className="pos-radio pos-radio--disabled">
          <input
            type="radio"
            name="pos-custom-origin"
            disabled
            checked={custom.origin === 'runway-relative'}
            onChange={() => {
              dispatch(customOriginSelected('runway-relative'));
            }}
          />
          Relative to the runway landing point
          <span className="pos-customtab__unavailable">
            the station has no bearing-and-distance placement to send
          </span>
        </label>

        <label className="pos-radio">
          <input
            type="radio"
            name="pos-custom-origin"
            checked={custom.origin === 'coordinates'}
            onChange={() => {
              dispatch(customOriginSelected('coordinates'));
            }}
          />
          At coordinates
        </label>
        <div className="pos-customtab__row">
          <label className="pos-field">
            <span className="pos-field__label">Latitude (°)</span>
            <input
              type="number"
              step="0.0001"
              className="pos-field__input pos-mono"
              value={latitude ?? ''}
              onChange={(event) => {
                change('latitude')(event.target.value);
              }}
            />
          </label>
          <label className="pos-field">
            <span className="pos-field__label">Longitude (°)</span>
            <input
              type="number"
              step="0.0001"
              className="pos-field__input pos-mono"
              value={longitude ?? ''}
              onChange={(event) => {
                change('longitude')(event.target.value);
              }}
            />
          </label>
        </div>
      </div>

      <div className="pos-customtab__facts">
        <FactRow
          label="Resolved position"
          value={
            latitude === null || longitude === null
              ? 'no airport loaded'
              : `${formatLatitude(latitude)} / ${formatLongitude(longitude)}`
          }
        />
        <FactRow
          label="Altitude"
          value={altitudeFt === null ? '—' : formatAltitudeFt(altitudeFt)}
        />
        <FactRow
          label="Heading"
          value={headingDeg === null ? '—' : formatHeadingTrue(headingDeg)}
        />
      </div>
    </div>
  );
}
