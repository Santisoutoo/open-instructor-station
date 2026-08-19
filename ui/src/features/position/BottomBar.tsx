import {
  configChanged,
  sendToggled,
  situationReset,
  type AircraftConfigState,
} from './positionDesignSlice';
import { RUNWAYS } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';

function numberField(
  field: keyof AircraftConfigState,
  value: number,
  onChange: (field: keyof AircraftConfigState, value: number) => void,
) {
  return (
    <input
      type="number"
      className="pos-field__input pos-mono"
      value={value}
      onChange={(event) => {
        onChange(field, Number(event.target.value));
      }}
    />
  );
}

export function BottomBar() {
  const dispatch = useAppDispatch();
  const config = useAppSelector((state) => state.positionDesign.config);
  const send = useAppSelector((state) => state.positionDesign.send);
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);

  const runway = selectedRunway !== null ? RUNWAYS[selectedRunway] : null;
  const hasIls = runway !== null && runway.kind === 'runway' && runway.ils !== null;

  function setConfig(field: keyof AircraftConfigState, value: number | boolean) {
    dispatch(configChanged({ field, value }));
  }

  return (
    <div className="pos-bottombar">
      <fieldset className="pos-bottombar__group">
        <legend className="pos-bottombar__group-title">Aircraft configuration · editable</legend>
        <label className="pos-field">
          <span className="pos-field__label">IAS (kt)</span>
          {numberField('iasKt', config.iasKt, setConfig)}
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Pitch (°)</span>
          {numberField('pitchDeg', config.pitchDeg, setConfig)}
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={config.gearDown}
            onChange={(event) => {
              setConfig('gearDown', event.target.checked);
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Gear down
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={config.flapsOn}
            onChange={(event) => {
              setConfig('flapsOn', event.target.checked);
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Flaps
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Flaps %</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            disabled={!config.flapsOn}
            value={config.flapsPercent}
            onChange={(event) => {
              setConfig('flapsPercent', Number(event.target.value));
            }}
          />
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={config.altitudeOverride}
            onChange={(event) => {
              setConfig('altitudeOverride', event.target.checked);
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Override altitude
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Override altitude (ft)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            disabled={!config.altitudeOverride}
            value={config.altitudeOverrideFt}
            onChange={(event) => {
              setConfig('altitudeOverrideFt', Number(event.target.value));
            }}
          />
        </label>
      </fieldset>

      <div className="pos-bottombar__divider" aria-hidden="true" />

      <fieldset className="pos-bottombar__group">
        <legend className="pos-bottombar__group-title">Sent with the position</legend>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.heading}
            onChange={() => {
              dispatch(sendToggled('heading'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Heading
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.course}
            onChange={() => {
              dispatch(sendToggled('course'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Course
        </label>
        <label className={hasIls ? 'pos-checkbox' : 'pos-checkbox pos-checkbox--disabled'}>
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.ilsFrequency}
            disabled={!hasIls}
            onChange={() => {
              dispatch(sendToggled('ilsFrequency'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          ILS frequency
          {!hasIls && <span className="pos-mono pos-bottombar__na"> n/a</span>}
        </label>
      </fieldset>

      <div className="pos-bottombar__spacer" />

      <div className="pos-bottombar__actions">
        <button type="button" className="pos-textaction">
          Show on map
        </button>
        <button type="button" className="pos-textaction">
          Full METAR
        </button>
        <div className="pos-bottombar__commit">
          <button type="button" className="pos-bottombar__set">
            Set position
            <span className="pos-bottombar__set-sub">Moves the aircraft now · sim stays paused</span>
          </button>
        </div>
        <button
          type="button"
          className="pos-textaction pos-textaction--danger-on-hover"
          onClick={() => {
            dispatch(situationReset());
          }}
        >
          Reset situation
        </button>
      </div>
    </div>
  );
}
