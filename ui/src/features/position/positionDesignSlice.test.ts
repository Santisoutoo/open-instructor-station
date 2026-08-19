import { describe, expect, it } from 'vitest';
import reducer, {
  airportLoaded,
  designTabSelected,
  initialPositionDesignState,
  markerSelected,
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
    const state = reducer(undefined, airportLoaded('lfmn'));
    expect(state.loadedIcao).toBe('LFMN');
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

describe('situationReset', () => {
  it('returns deep-equal to the initial state', () => {
    let state = reducer(undefined, startRunwaySelected('22L'));
    state = reducer(state, markerSelected('base-left'));
    state = reducer(state, designTabSelected('airwork'));

    expect(reducer(state, situationReset())).toEqual(initialPositionDesignState);
  });
});
