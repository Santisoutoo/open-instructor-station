import { describe, expect, it } from 'vitest';
import reducer, {
  airportLoaded,
  configChanged,
  coordinateHandoffReceived,
  designTabSelected,
  finalPlacementSelected,
  initialPositionDesignState,
  markerDistanceChanged,
  markerSelected,
  procedureFamilySelected,
  procedureLegSelected,
  procedureSelected,
  screenMenuToggled,
  situationReset,
  startAtToggled,
  startRunwaySelected,
  startStandSelected,
  switchesModalToggled,
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

describe('coordinateHandoffReceived', () => {
  const HANDOFF = {
    latitude: 40.46,
    longitude: -3.57,
    altitudeFt: 0,
    headingDeg: 0,
  };

  it('adopts the coordinate into the Custom location tab and opens it', () => {
    const state = reducer(undefined, coordinateHandoffReceived(HANDOFF));
    expect(state.activeTab).toBe('custom');
    expect(state.custom).toEqual({
      origin: 'coordinates',
      latitude: 40.46,
      longitude: -3.57,
      altitudeFt: 0,
      headingDeg: 0,
    });
  });

  it('clears a selected stand, which would otherwise win over the coordinate', () => {
    // `buildPlacementRequest` sends a stand whichever tab is open; a hand-off arriving
    // behind one would be staged and never placed.
    const withStand = reducer(undefined, startStandSelected('A3'));
    expect(
      reducer(withStand, coordinateHandoffReceived(HANDOFF)).selectedStand,
    ).toBeNull();
  });

  it('needs no loaded airport', () => {
    const state = reducer(undefined, coordinateHandoffReceived(HANDOFF));
    expect(state.loadedIcao).toBe('');
    expect(state.custom.latitude).toBe(40.46);
  });
});

describe('screenMenuToggled / startAtToggled / switchesModalToggled', () => {
  it('opening one popover closes the other', () => {
    const menuOpen = reducer(undefined, screenMenuToggled());
    expect(menuOpen.screenMenuOpen).toBe(true);

    const startAtOpen = reducer(menuOpen, startAtToggled());
    expect(startAtOpen.startAtOpen).toBe(true);
    expect(startAtOpen.screenMenuOpen).toBe(false);
  });

  it('the switches placeholder closes, and is closed by, the header popovers', () => {
    const switchesOpen = reducer(undefined, switchesModalToggled());
    expect(switchesOpen.switchesModalOpen).toBe(true);

    const menuOpen = reducer(switchesOpen, screenMenuToggled());
    expect(menuOpen.screenMenuOpen).toBe(true);
    expect(menuOpen.switchesModalOpen).toBe(false);

    const switchesAgain = reducer(menuOpen, switchesModalToggled());
    expect(switchesAgain.switchesModalOpen).toBe(true);
    expect(switchesAgain.screenMenuOpen).toBe(false);
  });
});

describe('markerDistanceChanged', () => {
  it('sets and clears an instructor’s edit to a circuit marker’s distance', () => {
    const edited = reducer(
      undefined,
      markerDistanceChanged({ id: 'base-left', value: 9 }),
    );
    expect(edited.markerDistances).toEqual({ 'base-left': 9 });

    const cleared = reducer(
      edited,
      markerDistanceChanged({ id: 'base-left', value: null }),
    );
    expect(cleared.markerDistances).toEqual({});
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
    state = reducer(state, markerDistanceChanged({ id: 'base-left', value: 9 }));

    const moved = reducer(state, airportLoaded('LEMD'));
    expect(moved.selectedRunway).toBeNull();
    expect(moved.selectedStand).toBeNull();
    expect(moved.procedure).toBeNull();
    expect(moved.config.iasKt).toBeNull();
    expect(moved.markerDistances).toEqual({});
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
