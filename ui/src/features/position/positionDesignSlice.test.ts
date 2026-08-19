import { describe, expect, it } from 'vitest';
import reducer, {
  airportLoaded,
  configChanged,
  designTabSelected,
  finalPlacementSelected,
  initialPositionDesignState,
  markerSelected,
  procedureFamilySelected,
  procedureLegSelected,
  procedureSelected,
  screenMenuToggled,
  situationReset,
  startAtToggled,
  startRunwaySelected,
  startStandSelected,
} from './positionDesignSlice';

describe('startRunwaySelected / startStandSelected', () => {
  it('selecting a stand clears the selected runway', () => {
    const withRunway = reducer(undefined, startRunwaySelected('22L'));
    const withStand = reducer(withRunway, startStandSelected('A3'));
    expect(withStand.selectedStand).toBe('A3');
    expect(withStand.selectedRunway).toBeNull();
  });

  it('selecting a runway clears the selected stand', () => {
    const withStand = reducer(undefined, startStandSelected('A3'));
    const withRunway = reducer(withStand, startRunwaySelected('22L'));
    expect(withRunway.selectedRunway).toBe('22L');
    expect(withRunway.selectedStand).toBeNull();
  });

  it('takes whatever ident navdata publishes, not a closed set', () => {
    expect(reducer(undefined, startRunwaySelected('18C')).selectedRunway).toBe('18C');
    expect(reducer(undefined, startRunwaySelected('09')).selectedRunway).toBe('09');
  });
});

describe('screenMenuToggled / startAtToggled', () => {
  it('opening one popover closes the other', () => {
    const menuOpen = reducer(undefined, screenMenuToggled());
    expect(menuOpen.screenMenuOpen).toBe(true);

    const startAtOpen = reducer(menuOpen, startAtToggled());
    expect(startAtOpen.startAtOpen).toBe(true);
    expect(startAtOpen.screenMenuOpen).toBe(false);
  });
});

describe('airportLoaded', () => {
  it('upper-cases the loaded ICAO', () => {
    expect(reducer(undefined, airportLoaded('lfmn')).loadedIcao).toBe('LFMN');
  });

  it('clears everything that only meant something at the previous airport', () => {
    let state = reducer(undefined, airportLoaded('LFMN'));
    state = reducer(state, startRunwaySelected('04R'));
    state = reducer(state, procedureSelected({ ident: 'BADO8A', transition: null }));
    state = reducer(state, configChanged({ field: 'iasKt', value: 90 }));

    const moved = reducer(state, airportLoaded('LEMD'));
    expect(moved.selectedRunway).toBeNull();
    expect(moved.selectedStand).toBeNull();
    expect(moved.procedure).toBeNull();
    expect(moved.config.iasKt).toBeNull();
  });

  it('re-loading the same ICAO is a no-op, so a selection survives it', () => {
    let state = reducer(undefined, airportLoaded('LFMN'));
    state = reducer(state, startRunwaySelected('04R'));
    expect(reducer(state, airportLoaded('lfmn')).selectedRunway).toBe('04R');
  });
});

describe('the procedure selection', () => {
  it('opens a procedure without a leg, then takes the leg’s own sequence', () => {
    const opened = reducer(
      undefined,
      procedureSelected({ ident: 'BADO8A', transition: 'BADOD' }),
    );
    expect(opened.procedure).toEqual({
      ident: 'BADO8A',
      transition: 'BADOD',
      sequence: null,
    });
    expect(reducer(opened, procedureLegSelected(30)).procedure?.sequence).toBe(30);
  });

  it('switching procedure family drops the open procedure with it', () => {
    const opened = reducer(
      undefined,
      procedureSelected({ ident: 'BADO8A', transition: null }),
    );
    expect(reducer(opened, procedureFamilySelected('star')).procedure).toBeNull();
  });
});

describe('designTabSelected', () => {
  it('does not disturb the selected marker', () => {
    const withMarker = reducer(undefined, markerSelected('base-left'));
    const withTab = reducer(withMarker, designTabSelected('sidstar'));
    expect(withTab.activeTab).toBe('sidstar');
    expect(withTab.selectedMarker).toBe('base-left');
  });
});

describe('finalPlacementSelected', () => {
  it('stores the server’s own placement name', () => {
    expect(reducer(undefined, finalPlacementSelected('final_10nm')).finalPlacement).toBe(
      'final_10nm',
    );
  });
});

describe('situationReset', () => {
  it('clears the situation but keeps the loaded airport', () => {
    let state = reducer(undefined, airportLoaded('LFMN'));
    state = reducer(state, startRunwaySelected('22L'));
    state = reducer(state, markerSelected('base-left'));
    state = reducer(state, designTabSelected('airwork'));

    const reset = reducer(state, situationReset());
    expect(reset).toEqual({
      ...initialPositionDesignState,
      icaoInput: 'LFMN',
      loadedIcao: 'LFMN',
    });
  });
});
