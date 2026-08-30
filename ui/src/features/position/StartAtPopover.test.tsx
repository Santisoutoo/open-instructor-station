import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { PositionHeaderBar } from './PositionHeaderBar';
import { initialPositionDesignState } from './positionDesignSlice';
import { stubApi } from './testApi';
import { ICAO, positionRoutes, STANDS } from './testFixtures';

// The airport diagram is a MapLibre map now; jsdom has no WebGL (see test/maplibreStub).
vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

afterEach(() => {
  vi.unstubAllGlobals();
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
  const trigger = screen.getByRole('button', { name: /^Start at/ });
  await userEvent.click(trigger);
  return { store, trigger };
}

describe('StartAtPopover', () => {
  it('Escape closes the popover and returns focus to the trigger', async () => {
    stubApi(positionRoutes());
    const { trigger } = await renderOpenPopover();

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('a pointer press outside the popover closes it', async () => {
    stubApi(positionRoutes());
    await renderOpenPopover();

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // `pointerdown`, not `click`: the close must beat the other anchor's trigger to the
    // punch (see Popover.tsx) — this pins the event the implementation listens on.
    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
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

  it('selects the same stand from the diagram and from the list', async () => {
    stubApi(positionRoutes());
    const { store } = await renderOpenPopover();

    await userEvent.click(await screen.findByRole('button', { name: 'Stand A1' }));

    expect(store.getState().positionDesign.selectedStand).toBe('A1');
    expect(screen.getByRole('button', { name: 'Stand A1' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // The list row carries the same id without the diagram's aria-label.
    const listRow = screen
      .getAllByRole('button')
      .find(
        (element) =>
          element.getAttribute('aria-label') === null &&
          element.textContent?.startsWith('A1') === true,
      );
    expect(listRow).toBeDefined();
  });

  it('renders every stand even when navdata repeats a parking name', async () => {
    // Real apt.dat does this: LFMN publishes dozens of stands all named "Apron K parking".
    // Duplicate React keys leave stale diagram buttons behind, so the key must not be the
    // name alone — the console.error assertion is what actually pins that.
    const a1 = STANDS.find((entry) => entry.name === 'A1');
    if (a1 === undefined) {
      throw new Error('fixture stand A1 is missing');
    }
    const duplicate = { ...a1, position: { ...a1.position, latitude: 43.661 } };
    const consoleError = vi.spyOn(console, 'error');
    stubApi(
      positionRoutes({
        [`airports/${ICAO}/parking`]: { body: [...STANDS, duplicate] },
      }),
    );
    await renderOpenPopover();

    expect(await screen.findByText('5 of 5')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Stand A1' })).toHaveLength(2);
    const keyComplaints = consoleError.mock.calls.filter((call) =>
      String(call[0]).includes('same key'),
    );
    expect(keyComplaints).toEqual([]);
    consoleError.mockRestore();
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
