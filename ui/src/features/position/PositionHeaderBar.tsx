/**
 * The 64px header: screen-menu trigger, ICAO input + airport name + Load/Search/Random,
 * Start-at trigger, connection dot, theme toggle.
 *
 * "Load" is the other place (with the runway strip / Start-at popover) the design doc's
 * mirrored dispatch happens: `airportSelected(icao)` fires on the legacy `positionSlice`
 * only when the ICAO actually changed, since it wipes the staged placement, overrides and
 * the whole Weather panel via its `extraReducers`.
 */

import { useRef } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { themeToggled } from '../../store/uiSlice';
import { ScreenMenu } from './ScreenMenu';
import { StartAtPopover } from './StartAtPopover';
import { AIRPORT_NAME } from './sampleData';
import { airportLoaded, icaoTyped, screenMenuToggled, startAtToggled } from './positionDesignSlice';
import { airportSelected } from './positionSlice';

export function PositionHeaderBar() {
  const dispatch = useAppDispatch();
  const icaoInput = useAppSelector((state) => state.positionDesign.icaoInput);
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedStand = useAppSelector((state) => state.positionDesign.selectedStand);
  const screenMenuOpen = useAppSelector((state) => state.positionDesign.screenMenuOpen);
  const startAtOpen = useAppSelector((state) => state.positionDesign.startAtOpen);
  const connectionStatus = useAppSelector((state) => state.connection.status);
  const demoFeed = useAppSelector((state) => state.ui.demoFeed);
  const theme = useAppSelector((state) => state.ui.theme);
  const legacyIcao = useAppSelector((state) => state.position.selectedIcao);

  const screenMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const startAtTriggerRef = useRef<HTMLButtonElement>(null);

  function handleLoad() {
    const icao = icaoInput.toUpperCase();
    dispatch(airportLoaded(icao));
    if (legacyIcao !== icao) {
      dispatch(airportSelected(icao));
    }
  }

  const connected = connectionStatus === 'connected';
  const startAtLabel =
    selectedStand !== null
      ? `Stand ${selectedStand}`
      : selectedRunway !== null
        ? `Runway ${selectedRunway}`
        : 'Not set';

  return (
    <header className="pos-header">
      <button
        ref={screenMenuTriggerRef}
        type="button"
        className="pos-header__menu-trigger"
        aria-haspopup="menu"
        aria-expanded={screenMenuOpen}
        aria-controls="pos-screen-menu"
        onClick={() => {
          dispatch(screenMenuToggled());
        }}
      >
        Position ▾
      </button>
      <ScreenMenu triggerRef={screenMenuTriggerRef} />

      <div className="pos-header__airport">
        <input
          className="pos-header__icao pos-mono"
          value={icaoInput}
          maxLength={4}
          aria-label="Airport ICAO code"
          onChange={(event) => {
            dispatch(icaoTyped(event.target.value.toUpperCase()));
          }}
        />
        <span className="pos-header__airport-name">{AIRPORT_NAME}</span>
        <button type="button" className="pos-header__load" onClick={handleLoad}>
          Load
        </button>
        <button type="button" className="pos-textaction">
          Search
        </button>
        <button type="button" className="pos-textaction">
          Random
        </button>
      </div>

      <button
        ref={startAtTriggerRef}
        type="button"
        className="pos-header__startat-trigger"
        aria-haspopup="dialog"
        aria-expanded={startAtOpen}
        aria-controls="pos-startat-popover"
        onClick={() => {
          dispatch(startAtToggled());
        }}
      >
        Start at <span className="pos-mono">{startAtLabel}</span>
      </button>
      <StartAtPopover triggerRef={startAtTriggerRef} />

      <div className="pos-header__spacer" />

      {demoFeed && <span className="pos-header__demo">Demo data</span>}

      <div className="pos-header__connection" role="status" aria-live="polite">
        <span
          className={
            connected
              ? 'pos-dot pos-dot--accent'
              : 'pos-dot pos-dot--caution pos-header__connection-dot--blink'
          }
          aria-hidden="true"
        />
        <span>{connected ? 'X-Plane connected' : 'X-Plane connecting'}</span>
      </div>

      <button
        type="button"
        className="pos-textaction"
        onClick={() => {
          dispatch(themeToggled());
        }}
      >
        {theme === 'dark' ? 'Light' : 'Dark'}
      </button>
    </header>
  );
}
