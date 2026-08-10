/**
 * The circuit grid and the finals rail.
 *
 * Two guarantees, and the second one is the dangerous one:
 *
 * - **Tapping a tile stages, it never commits.** The incumbent product teleports on the
 *   first click of a tile, mid-lesson. This grid dispatches into the store and stops.
 * - **The staged request carries only what the instructor actually chose.** Every other
 *   field of `RunwayPlacementRequest` is `| None` on the server so that "the caller said
 *   nothing" stays distinguishable from "the caller said zero" — and `ias_kt` is the one
 *   where the difference is a wreck. A grid that helpfully filled in `ias_kt: 0` would put
 *   a parked aeroplane on a 10 NM final below stall speed, with the geometry perfect
 *   (issue #39). So the request is asserted with `toEqual`, not with `toMatchObject`.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { type AppStore, setupStore } from '../../store';
import { PatternGrid } from './PatternGrid';

function renderGrid(): { store: AppStore } {
  const store = setupStore();
  render(
    <Provider store={store}>
      <PatternGrid icao="ZZZZ" runwayIdent="32L" />
    </Provider>,
  );
  return { store };
}

describe('<PatternGrid />', () => {
  it('offers all seven finals and all eight circuit legs', () => {
    renderGrid();

    const finals = screen.getByRole('group', { name: /final approach distances/i });
    for (const label of ['20 NM', '15 NM', '10 NM', '8 NM', '5 NM', '3 NM', 'Short']) {
      expect(within(finals).getByRole('button', { name: label })).toBeInTheDocument();
    }

    for (const label of [
      /crosswind l/i,
      /upwind l/i,
      /downwind l/i,
      /base l/i,
      /crosswind r/i,
      /upwind r/i,
      /downwind r/i,
      /base r/i,
    ]) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('anchors the grid on the runway end it was given', () => {
    renderGrid();

    expect(screen.getByText('32L')).toBeInTheDocument();
    expect(screen.getByText(/approach from below/i)).toBeInTheDocument();
  });

  it('stages a final without inventing a speed, an altitude or a glideslope', async () => {
    const user = userEvent.setup();
    const { store } = renderGrid();

    await user.click(screen.getByRole('button', { name: '10 NM' }));

    expect(store.getState().position.staged).toEqual({
      type: 'runway',
      airport_icao: 'ZZZZ',
      runway_ident: '32L',
      placement: 'final_10nm',
    });
  });

  it('stages a circuit leg the same way', async () => {
    const user = userEvent.setup();
    const { store } = renderGrid();

    await user.click(screen.getByRole('button', { name: /downwind l/i }));

    expect(store.getState().position.staged).toEqual({
      type: 'runway',
      airport_icao: 'ZZZZ',
      runway_ident: '32L',
      placement: 'left_downwind',
    });
  });

  it('marks exactly one tile as staged and moves the mark when another is tapped', async () => {
    const user = userEvent.setup();
    renderGrid();

    await user.click(screen.getByRole('button', { name: '10 NM' }));
    expect(screen.getByRole('button', { name: '10 NM' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(
      screen.getAllByRole('button', { pressed: true }).map((node) => node.textContent),
    ).toEqual(['10 NM']);

    await user.click(screen.getByRole('button', { name: /base r/i }));
    expect(screen.getByRole('button', { name: '10 NM' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getAllByRole('button', { pressed: true })).toHaveLength(1);
  });

  it('does not talk to the server at all — a tap is not a command', async () => {
    // Nothing here is allowed to reach the simulator. `StagingBar` owns the commit, and
    // it only fires on its own button.
    const user = userEvent.setup();
    const { store } = renderGrid();

    await user.click(screen.getByRole('button', { name: '20 NM' }));

    expect(Object.keys(store.getState().instructorApi.mutations)).toEqual([]);
  });
});
