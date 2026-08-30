/**
 * The 64px header: screen-menu trigger, ICAO input + airport name + Load/Search, Start-at
 * trigger, connection dot, theme toggle.
 *
 * "Load" is one of the two places (with the runway strip / Start-at popover) the mirrored
 * dispatch happens: `airportSelected(icao)` fires on the shared `positionSlice` only when
 * the ICAO actually changed, since it wipes the staged placement, the overrides and the
 * whole Weather panel via its `extraReducers`.
 */

import { useRef } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { themeToggled } from '../../store/uiSlice';
import { AirportMenu } from './AirportMenu';
import { ScreenMenu } from './ScreenMenu';
import { StartAtPopover } from './StartAtPopover';
import { startAtLabelOf, startAtPopoverId } from './startAt';
import {
  airportLoaded,
  airportMenuOpened,
  icaoTyped,
  screenMenuToggled,
  startAtToggled,
} from './positionDesignSlice';
import { airportSelected } from './positionSlice';
import { useAirport } from './usePositionData';

export function PositionHeaderBar() {
  const dispatch = useAppDispatch();
  const icaoInput = useAppSelector((state) => state.positionDesign.icaoInput);
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedStand = useAppSelector((state) => state.positionDesign.selectedStand);
  const screenMenuOpen = useAppSelector((state) => state.positionDesign.screenMenuOpen);
  const startAtOpen = useAppSelector(
    (state) =>
      state.positionDesign.startAtOpen && state.positionDesign.startAtAnchor === 'header',
  );
  const airportMenuOpen = useAppSelector((state) => state.positionDesign.airportMenuOpen);
  const connectionStatus = useAppSelector((state) => state.connection.status);
  const demoFeed = useAppSelector((state) => state.ui.demoFeed);
  const theme = useAppSelector((state) => state.ui.theme);
  const legacyIcao = useAppSelector((state) => state.position.selectedIcao);

  const { airport, isFetching, isError } = useAirport();

  const screenMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const startAtTriggerRef = useRef<HTMLButtonElement>(null);
  const icaoInputRef = useRef<HTMLInputElement>(null);

  function load(raw: string) {
    const icao = raw.toUpperCase();
    if (icao === '') {
      return;
    }
    dispatch(airportLoaded(icao));
    if (legacyIcao !== icao) {
      dispatch(airportSelected(icao));
    }
  }

  const connected = connectionStatus === 'connected';
  const startAtLabel = startAtLabelOf(selectedRunway, selectedStand);

  const airportName = isError
    ? 'airport lookup failed'
    : (airport?.name ?? (isFetching ? 'reading navdata…' : 'not in navdata'));

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
          ref={icaoInputRef}
          className="pos-header__icao pos-mono"
          value={icaoInput}
          maxLength={4}
          aria-label="Airport ICAO code"
          aria-expanded={airportMenuOpen}
          aria-controls="pos-airport-menu"
          onChange={(event) => {
            dispatch(icaoTyped(event.target.value.toUpperCase()));
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              load(icaoInput);
            }
          }}
        />
        <span className="pos-header__airport-name">{airportName}</span>
        <button
          type="button"
          className="pos-header__load"
          onClick={() => {
            load(icaoInput);
          }}
        >
          Load
        </button>
        <button
          type="button"
          className="pos-textaction"
          onClick={() => {
            dispatch(airportMenuOpened());
            icaoInputRef.current?.focus();
          }}
        >
          Search
        </button>
        <AirportMenu triggerRef={icaoInputRef} onChoose={load} />
      </div>

      <button
        ref={startAtTriggerRef}
        type="button"
        className="pos-header__startat-trigger"
        aria-haspopup="dialog"
        aria-expanded={startAtOpen}
        aria-controls={startAtPopoverId('header')}
        onClick={() => {
          dispatch(startAtToggled('header'));
        }}
      >
        Start at <span className="pos-mono">{startAtLabel}</span>
      </button>
      <StartAtPopover anchor="header" triggerRef={startAtTriggerRef} />

      <div className="pos-header__spacer" />

      {demoFeed && !connected && <span className="pos-header__demo">Demo data</span>}

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
