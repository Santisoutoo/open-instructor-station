import { FactRow } from './FactRow';
import { formatAltitudeFt, formatHeadingM } from './format';
import { customFieldChanged, customOriginSelected } from './positionDesignSlice';
import { AIRPORT_LATITUDE, AIRPORT_LONGITUDE } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';

/** `43° 39' 35.27" N` — the DMS format the design doc's Custom tab asks for. */
function formatDms(value: number, positive: string, negative: string, padWidth: number): string {
  const suffix = value >= 0 ? positive : negative;
  const abs = Math.abs(value);
  const degrees = Math.floor(abs);
  const minutesFull = (abs - degrees) * 60;
  const minutes = Math.floor(minutesFull);
  const seconds = (minutesFull - minutes) * 60;
  return `${String(degrees).padStart(padWidth, '0')}° ${String(minutes).padStart(2, '0')}' ${seconds.toFixed(2)}" ${suffix}`;
}

export function CustomLocationTab() {
  const dispatch = useAppDispatch();
  const custom = useAppSelector((state) => state.positionDesign.custom);

  const latitude = custom.origin === 'coordinates' ? custom.latitude : AIRPORT_LATITUDE;
  const longitude = custom.origin === 'coordinates' ? custom.longitude : AIRPORT_LONGITUDE;

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
            value={custom.altitudeFt}
            onChange={(event) => {
              dispatch(
                customFieldChanged({ field: 'altitudeFt', value: Number(event.target.value) }),
              );
            }}
          />
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Heading (°M)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            value={custom.headingDeg}
            onChange={(event) => {
              dispatch(
                customFieldChanged({ field: 'headingDeg', value: Number(event.target.value) }),
              );
            }}
          />
        </label>
      </div>

      <div className="pos-customtab__origin" role="radiogroup" aria-label="Custom location origin">
        <label className="pos-radio">
          <input
            type="radio"
            name="pos-custom-origin"
            checked={custom.origin === 'runway-relative'}
            onChange={() => {
              dispatch(customOriginSelected('runway-relative'));
            }}
          />
          Relative to the runway landing point
        </label>
        <div className="pos-customtab__row">
          <label className="pos-field">
            <span className="pos-field__label">Bearing (°)</span>
            <input
              type="number"
              className="pos-field__input pos-mono"
              disabled={custom.origin !== 'runway-relative'}
              value={custom.bearingDeg}
              onChange={(event) => {
                dispatch(
                  customFieldChanged({ field: 'bearingDeg', value: Number(event.target.value) }),
                );
              }}
            />
          </label>
          <label className="pos-field">
            <span className="pos-field__label">Distance (NM)</span>
            <input
              type="number"
              className="pos-field__input pos-mono"
              disabled={custom.origin !== 'runway-relative'}
              value={custom.distanceNm}
              onChange={(event) => {
                dispatch(
                  customFieldChanged({ field: 'distanceNm', value: Number(event.target.value) }),
                );
              }}
            />
          </label>
        </div>

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
            <span className="pos-field__label">Latitude</span>
            <input
              type="text"
              className="pos-field__input pos-mono"
              disabled={custom.origin !== 'coordinates'}
              readOnly
              value={formatDms(custom.latitude, 'N', 'S', 2)}
            />
          </label>
          <label className="pos-field">
            <span className="pos-field__label">Longitude</span>
            <input
              type="text"
              className="pos-field__input pos-mono"
              disabled={custom.origin !== 'coordinates'}
              readOnly
              value={formatDms(custom.longitude, 'E', 'W', 3)}
            />
          </label>
        </div>
      </div>

      <div className="pos-customtab__facts">
        <FactRow
          label="Resolved position"
          value={`${formatDms(latitude, 'N', 'S', 2)} / ${formatDms(longitude, 'E', 'W', 3)}`}
        />
        <FactRow label="Altitude" value={formatAltitudeFt(custom.altitudeFt)} />
        <FactRow label="Heading" value={formatHeadingM(custom.headingDeg)} />
        <FactRow label="Airspace" value="inside LFMN CTR" accent />
      </div>
    </div>
  );
}
