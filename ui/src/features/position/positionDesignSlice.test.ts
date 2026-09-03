import { describe, expect, it } from 'vitest';
import { CIRCUIT_LEG_OPTIONS_NM } from './circuitDistances';
import reducer, {
  airportLoaded,
  approachFilterSelected,
  circuitDistanceSelected,
  CIRCUIT_LEG_KINDS,
  configChanged,
  coordinateHandoffReceived,
  designTabSelected,
  diagramModeSelected,
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

describe('screenMenuToggled / startAtToggled', () => {
  it('opening one popover closes the other', () => {
    const menuOpen = reducer(undefined, screenMenuToggled());
    expect(menuOpen.screenMenuOpen).toBe(true);

    const startAtOpen = reducer(menuOpen, startAtToggled('header'));
    expect(startAtOpen.startAtOpen).toBe(true);
    expect(startAtOpen.startAtAnchor).toBe('header');
    expect(startAtOpen.screenMenuOpen).toBe(false);
  });

  it('the other trigger moves the open Start-at popover instead of closing it', () => {
    const fromHeader = reducer(undefined, startAtToggled('header'));
    const moved = reducer(fromHeader, startAtToggled('bottombar'));
    expect(moved.startAtOpen).toBe(true);
    expect(moved.startAtAnchor).toBe('bottombar');

    const closed = reducer(moved, startAtToggled('bottombar'));
    expect(closed.startAtOpen).toBe(false);
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

describe('the approach-type filter', () => {
  it('narrows the chips and drops the open procedure, which may no longer be listed', () => {
    const opened = reducer(
      reducer(undefined, procedureFamilySelected('final')),
      procedureSelected({ ident: 'R04R', transition: null }),
    );
    const narrowed = reducer(opened, approachFilterSelected('ils'));
    expect(narrowed.approachFilter).toBe('ils');
    expect(narrowed.procedure).toBeNull();
  });

  it('is reset by a family switch — the other family may not publish that type', () => {
    const narrowed = reducer(undefined, approachFilterSelected('vor'));
    expect(reducer(narrowed, procedureFamilySelected('apptr')).approachFilter).toBe(
      'all',
    );
  });

  it('is reset by loading another airport — its chips are derived from its own data', () => {
    const narrowed = reducer(
      reducer(undefined, airportLoaded('LEMD')),
      approachFilterSelected('ndb'),
    );
    expect(reducer(narrowed, airportLoaded('LEBL')).approachFilter).toBe('all');
    expect(reducer(narrowed, airportLoaded('LEMD')).approachFilter).toBe('ndb');
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

describe('circuitDistanceSelected', () => {
  it('touches one leg kind only', () => {
    const state = reducer(
      undefined,
      circuitDistanceSelected({ kind: 'base', distanceNm: 10 }),
    );
    expect(state.circuitDistanceNm).toEqual({ downwind: 4, base: 10, vectors: 6 });
  });

  it('starts every leg on a chip its own selector actually offers', () => {
    for (const kind of CIRCUIT_LEG_KINDS) {
      expect(CIRCUIT_LEG_OPTIONS_NM[kind]).toContain(
        initialPositionDesignState.circuitDistanceNm[kind],
      );
    }
  });

  it('is not cleared by loading another airport — it is the instructor’s own preference', () => {
    let state = reducer(undefined, airportLoaded('LFMN'));
    state = reducer(state, circuitDistanceSelected({ kind: 'vectors', distanceNm: 3 }));
    state = reducer(state, airportLoaded('LEMD'));
    expect(state.circuitDistanceNm.vectors).toBe(3);
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

  it('preserves diagramMode — a view preference, not part of the situation', () => {
    // The regression this guards: a naive `{ ...initialPositionDesignState, icaoInput, loadedIcao }`
    // rewrite would silently drop back to '2d', violating the issue's own requirement that the
    // 2D/3D choice survives a reset.
    let state = reducer(undefined, airportLoaded('LFMN'));
    state = reducer(state, diagramModeSelected('3d'));
    expect(state.diagramMode).toBe('3d');

    const reset = reducer(state, situationReset());
    expect(reset.diagramMode).toBe('3d');
  });
});

describe('diagramModeSelected', () => {
  it('sets the field', () => {
    expect(reducer(undefined, diagramModeSelected('3d')).diagramMode).toBe('3d');
    const back = reducer(reducer(undefined, diagramModeSelected('3d')), diagramModeSelected('2d'));
    expect(back.diagramMode).toBe('2d');
  });

  it('is not touched by airportLoaded / clearAirportScopedState — it is a view preference', () => {
    let state = reducer(undefined, diagramModeSelected('3d'));
    state = reducer(state, airportLoaded('LFMN'));
    expect(state.diagramMode).toBe('3d');

    // A second, different airport still runs clearAirportScopedState.
    state = reducer(state, startRunwaySelected('22L'));
    state = reducer(state, airportLoaded('LEMD'));
    expect(state.diagramMode).toBe('3d');
    expect(state.selectedRunway).toBeNull();
  });
});
