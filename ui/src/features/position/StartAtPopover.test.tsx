import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ParkingStand } from '../../api/models';
import { setupStore } from '../../store';
import { PositionHeaderBar } from './PositionHeaderBar';
import { initialPositionDesignState } from './positionDesignSlice';
import { stubApi } from './testApi';
import { ICAO, positionRoutes } from './testFixtures';

// The popover now transitively imports `maplibre-gl` via `StartAtMap` → `useMapLibre`,
// regardless of whether the stub's `Map` ever fires `'load'` in this jsdom render.
vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

// `StartAtMap` is mocked so `StartAtPopover.tsx`'s own `stands` prop can be captured by
// reference across renders — a full render never reaches `useStartAtMarkers`'s effects
// anyway (jsdom's maplibre-gl stub never fires `'load'`), so this is strictly additive: no
// existing assertion in this file depends on the real `StartAtMap`/marker DOM.
let capturedStands: readonly (readonly ParkingStand[])[] = [];
vi.mock('./StartAtMap', () => ({
  StartAtMap: ({ stands }: { readonly stands: readonly ParkingStand[] }) => {
    capturedStands = [...capturedStands, stands];
    return null;
  },
}));

afterEach(() => {
  vi.unstubAllGlobals();
  capturedStands = [];
});

async function renderOpenPopover() {
  const store = setupStore({
    positionDesign: { ...initialPositionDesignState, icaoInput: ICAO, loadedIcao: ICAO },
  });
  render(
    <Provider store={store}>
      <PositionHeaderBar />
    </Provider>,
  );
  const trigger = screen.getByRole('button', { name: /^Start position/ });
  await userEvent.click(trigger);
  return { store, trigger };
}

describe('StartAtPopover', () => {
  it('the trigger reads "Start position", not the old runway-shaped "Start at"', () => {
    stubApi(positionRoutes());
    const store = setupStore({
      positionDesign: { ...initialPositionDesignState, icaoInput: ICAO, loadedIcao: ICAO },
    });
    render(
      <Provider store={store}>
        <PositionHeaderBar />
      </Provider>,
    );

    expect(screen.getByRole('button', { name: /^Start position/ })).toBeInTheDocument();
  });

  it('Escape closes the popover and returns focus to the trigger', async () => {
    stubApi(positionRoutes());
    const { trigger } = await renderOpenPopover();

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('lists the airport’s real runway ends, badging the one with an ILS', async () => {
    stubApi(positionRoutes());
    await renderOpenPopover();

    expect(await screen.findByText('04R·ILS')).toBeInTheDocument();
    // '22L' also labels the strip's far threshold in the diagram, so ask the list itself.
    const list = screen.getByRole('dialog').querySelector('.pos-startat__list');
    expect(list?.textContent).toContain('22L');
    expect(list?.textContent).not.toContain('22L·ILS');
  });

  it('narrows the stand list by the server’s own parking kind, count following', async () => {
    stubApi(positionRoutes());
    await renderOpenPopover();

    expect(await screen.findByText('4 of 4')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Tie-downs' }));

    expect(screen.getByText('1 of 4')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stand A1' })).not.toBeInTheDocument();
  });

  it('selects a stand from the list — the map click path is proven by useStartAtMarkers.test.tsx', async () => {
    // In jsdom, the maplibre-gl stub's Map never fires 'load' (by its own docstring), so
    // useMapLibre's map handle never leaves null here and StartAtMap never mounts a DOM
    // marker inside a full StartAtPopover render — the map-click path is genuinely
    // unreachable at this render level. `useStartAtMarkers.test.tsx` proves that a click on
    // a map marker dispatches through the identical onSelectStand callback the list row
    // below calls, by constructing a StubMap directly and bypassing the 'load' gate.
    stubApi(positionRoutes());
    const { store } = await renderOpenPopover();

    await userEvent.click(await screen.findByRole('button', { name: 'Stand A1' }));

    expect(store.getState().positionDesign.selectedStand).toBe('A1');
    expect(store.getState().positionDesign.selectedRunway).toBeNull();
  });

  it('keeps the same stands reference across an unrelated re-render while a filter is active', async () => {
    // Regression: `shownStands` used to be a bare `.filter()` with no memoisation, so any
    // re-render — even one caused by selecting a runway, nothing to do with parking — handed
    // `StartAtMap`/`useStartAtMarkers` a brand-new array reference and made their
    // `[map, runways, stands]`-keyed effects believe the stands had changed.
    stubApi(positionRoutes());
    await renderOpenPopover();

    // Activate the `.filter()` branch — the one that previously allocated fresh each render.
    await userEvent.click(screen.getByRole('button', { name: 'Tie-downs' }));
    const afterFilter = capturedStands.at(-1);
    expect(afterFilter).toBeDefined();

    // An unrelated re-render: selecting a runway from the sidebar dispatches into Redux and
    // re-renders StartAtPopover, but must not produce a new `stands` reference.
    await userEvent.click(screen.getByRole('button', { name: '04R·ILS' }));

    expect(capturedStands.at(-1)).toBe(afterFilter);
  });

  it('says so, rather than showing an empty box, when the parking cannot be read', async () => {
    stubApi(
      positionRoutes({
        [`airports/${ICAO}/parking`]: { status: 500, detail: 'apt.dat unreadable' },
      }),
    );
    await renderOpenPopover();

    expect(
      await screen.findByText(/parking of LFMN could not be read/),
    ).toBeInTheDocument();
  });
});
