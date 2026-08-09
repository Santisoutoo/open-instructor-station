/**
 * SID, STAR and approach procedures, and their legs.
 *
 * The rule under test is the one the module docstring states and the whole ARINC 424 gotcha
 * in `CLAUDE.md` exists for: **an unpositionable leg is shown, not hidden, and is not
 * offered.** A `CA` leg ends at an altitude rather than at a fix, so it has no defensible
 * coordinate — but an instructor reading a SID needs to see the climb leg to make sense of
 * the ones around it. Hiding it would make the procedure look like it starts in mid-air;
 * offering it would place an aeroplane at a coordinate nobody published.
 *
 * The other thing pinned here is that the staged request carries **nothing but the leg's
 * identity**. `altitude_ft` and `ias_kt` are `| None` on the server precisely so the leg's
 * own published constraint wins; a panel that sent `altitude_ft: 0` would put an aeroplane
 * on a STAR at sea level.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Procedure, ProcedureLeg, ProcedureSummary } from '../../api/models';
import { type AppStore, setupStore } from '../../store';
import { ProcedureList } from './ProcedureList';
import { type ApiCall, type Answer, callsTo, positionState, stubApi } from './testApi';

function summary(overrides: Partial<ProcedureSummary> = {}): ProcedureSummary {
  return {
    airport_icao: 'ZZZZ',
    kind: 'sid',
    ident: 'BARD3B',
    runway_idents: ['32L'],
    leg_count: 3,
    positionable_leg_count: 2,
    ...overrides,
  };
}

function leg(overrides: Partial<ProcedureLeg> & { sequence: number }): ProcedureLeg {
  return {
    path_terminator: 'TF',
    is_positionable: true,
    is_flyover: false,
    is_initial_approach_fix: false,
    is_final_approach_fix: false,
    is_missed_approach_point: false,
    is_missed_approach_leg: false,
    is_end_of_procedure: false,
    ...overrides,
  };
}

function waypoint(ident: string) {
  return {
    ident,
    kind: 'fix' as const,
    position: { latitude: 40.6, longitude: -3.4, altitude_ft: 0 },
  };
}

/**
 * A SID whose first leg is a `CA` — climb to an altitude. Straight out of the gotcha list:
 * it has a path terminator with no fix, so it is displayed and not offered.
 */
const BARD3B: Procedure = {
  airport_icao: 'ZZZZ',
  kind: 'sid',
  ident: 'BARD3B',
  runway_idents: ['32L'],
  legs: [
    leg({
      sequence: 10,
      path_terminator: 'CA',
      is_positionable: false,
      unpositionable_reason: 'A CA leg ends at an altitude, not at a fix.',
      altitude: {
        descriptor: '+',
        min_ft: 3000,
        min_is_flight_level: false,
        max_is_flight_level: false,
        display: 'at or above 3,000 ft',
      },
    }),
    leg({ sequence: 20, fix: waypoint('GOXOL') }),
    leg({
      sequence: 30,
      path_terminator: 'CF',
      fix: waypoint('BARDI'),
      speed: { descriptor: '-', max_kt: 250, display: 'at or below 250 kt' },
    }),
  ],
};

function renderProcedures(routes: Record<string, Answer>): {
  store: AppStore;
  calls: ApiCall[];
} {
  const { calls } = stubApi(routes);
  const store = setupStore(
    positionState({ selectedIcao: 'ZZZZ', activeTab: 'procedures' }),
  );
  render(
    <Provider store={store}>
      <ProcedureList icao="ZZZZ" />
    </Provider>,
  );
  return { store, calls };
}

const LISTED: Record<string, Answer> = {
  '/procedures/sid/BARD3B': { body: BARD3B },
  '/procedures': {
    body: [
      summary(),
      summary({
        ident: 'BARD3B',
        transition: 'ADUXO',
        leg_count: 2,
        positionable_leg_count: 2,
      }),
      summary({ kind: 'star', ident: 'RBO1A' }),
      summary({ kind: 'approach', ident: 'I32L', approach_type: 'ils' }),
    ],
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<ProcedureList />', () => {
  it('groups procedures by kind and says how many legs are placeable', async () => {
    renderProcedures(LISTED);

    expect(await screen.findByRole('heading', { name: 'SID' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'STAR' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Approach' })).toBeInTheDocument();
    expect(screen.getAllByText('2/3 placeable').length).toBeGreaterThan(0);
  });

  it('treats two transitions of one procedure as two separate rows', async () => {
    // BARD3B and BARD3B/ADUXO are different routes. Opening one must not open the other.
    const user = userEvent.setup();
    renderProcedures(LISTED);

    const rows = await screen.findAllByRole('button', { name: /BARD3B/ });
    expect(rows).toHaveLength(2);

    await user.click(rows[0] as HTMLElement);

    expect(rows[0]).toHaveAttribute('aria-expanded', 'true');
    expect(rows[1]).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows an unpositionable leg with the server’s own reason, and no Stage button', async () => {
    const user = userEvent.setup();
    renderProcedures(LISTED);

    await user.click(
      (await screen.findAllByRole('button', { name: /BARD3B/ }))[0] as HTMLElement,
    );
    const climb = (await screen.findByText('CA')).closest('tr');
    expect(climb).not.toBeNull();

    const row = within(climb as HTMLElement);
    expect(
      row.getByText('A CA leg ends at an altitude, not at a fix.'),
    ).toBeInTheDocument();
    expect(row.queryByRole('button', { name: /stage/i })).not.toBeInTheDocument();
    // Still listed: a SID without its climb leg reads as starting in mid-air.
    expect(row.getByText('10')).toBeInTheDocument();
  });

  it('renders the published constraints verbatim rather than reformatting them', async () => {
    const user = userEvent.setup();
    renderProcedures(LISTED);

    await user.click(
      (await screen.findAllByRole('button', { name: /BARD3B/ }))[0] as HTMLElement,
    );

    expect(await screen.findByText('at or above 3,000 ft')).toBeInTheDocument();
    expect(screen.getByText('at or below 250 kt')).toBeInTheDocument();
  });

  it('stages a leg by its identity alone, leaving its constraints to the server', async () => {
    const user = userEvent.setup();
    const { store, calls } = renderProcedures(LISTED);

    await user.click(
      (await screen.findAllByRole('button', { name: /BARD3B/ }))[0] as HTMLElement,
    );
    const goxol = (await screen.findByText('GOXOL')).closest('tr') as HTMLElement;
    await user.click(within(goxol).getByRole('button', { name: /stage/i }));

    expect(store.getState().position.staged).toEqual({
      type: 'procedure_leg',
      airport_icao: 'ZZZZ',
      kind: 'sid',
      ident: 'BARD3B',
      transition: null,
      sequence: 20,
    });
    expect(callsTo(calls, '/position/apply')).toEqual([]);
  });

  it('closes a procedure that is tapped again', async () => {
    const user = userEvent.setup();
    const { store } = renderProcedures(LISTED);

    const row = (
      await screen.findAllByRole('button', { name: /BARD3B/ })
    )[0] as HTMLElement;
    await user.click(row);
    await user.click(row);

    expect(store.getState().position.openProcedure).toBeNull();
    expect(row).toHaveAttribute('aria-expanded', 'false');
  });

  it('says so when the procedures could not be read', async () => {
    renderProcedures({ '/procedures': { status: 500, detail: 'CIFP is unreadable.' } });

    expect(
      await screen.findByText(/procedures of ZZZZ could not be read/i),
    ).toBeInTheDocument();
  });

  it('says so when the airport publishes none', async () => {
    renderProcedures({ '/procedures': { body: [] } });

    expect(await screen.findByText(/no published procedures/i)).toBeInTheDocument();
  });

  it('reports a procedure whose legs fail to load, rather than an empty table', async () => {
    const user = userEvent.setup();
    renderProcedures({
      '/procedures/sid/BARD3B': { status: 500, detail: 'The CIFP record is truncated.' },
      '/procedures': { body: [summary()] },
    });

    await user.click(await screen.findByRole('button', { name: /BARD3B/ }));

    expect(await screen.findByText(/BARD3B could not be read/i)).toBeInTheDocument();
  });
});
