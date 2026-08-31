import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import {
  approachFilterSelected,
  initialPositionDesignState,
  procedureLegSelected,
  procedureSelected,
  type ProcedureFamily,
} from './positionDesignSlice';
import type { GeoPosition, ProcedureLayout } from '../../api/models';
import { SidStarTab } from './SidStarTab';
import { stubApi } from './testApi';
import {
  AIRPORT,
  ICAO,
  PROCEDURE_I04R,
  PROCEDURES,
  positionRoutes,
} from './testFixtures';

/**
 * The lazy-loaded 3D view is behind a `Suspense` boundary of its own — mocked to a
 * `data-testid` stand-in that echoes the two props this file's tests need
 * (`selectedSequence`, and since #178 `airportPosition`), rather than pulling the whole
 * `@react-three/fiber`/`@react-three/drei` stub in here too (that belongs to
 * `ProcedureDiagram3D.test.tsx`).
 */
vi.mock('./ProcedureDiagram3D', () => ({
  ProcedureDiagram3D: ({
    selectedSequence,
    airportPosition,
  }: {
    readonly selectedSequence: number | null;
    readonly airportPosition?: GeoPosition | undefined;
  }) => (
    <div
      data-testid="procdiagram3d-stub"
      data-selected-sequence={String(selectedSequence)}
      data-airport-position={
        airportPosition === undefined
          ? 'undefined'
          : `${String(airportPosition.latitude)},${String(airportPosition.longitude)}`
      }
    />
  ),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A minimal but valid layout for I04R — two nodes, one segment, nothing compressed. */
const LAYOUT_I04R: ProcedureLayout = {
  airport_icao: ICAO,
  kind: 'approach',
  ident: 'I04R',
  transition: null,
  approach_type: 'ils',
  anchor: 'runway',
  airport_x_nm: 0.1,
  airport_y_nm: 0.1,
  airport_elevation_ft: 12,
  nodes: [
    {
      sequence: 10,
      ident: 'NERAS',
      x_nm: 0,
      y_nm: -8,
      altitude_ft: 3000,
      altitude_source: 'published',
      positioned: true,
      is_positionable: true,
      is_missed_approach: false,
      is_runway: false,
    },
    {
      sequence: 20,
      ident: 'RW04R',
      x_nm: 0,
      y_nm: 0,
      altitude_ft: 12,
      altitude_source: 'runway',
      positioned: true,
      is_positionable: true,
      is_missed_approach: false,
      is_runway: true,
    },
  ],
  segments: [
    {
      from_sequence: 10,
      to_sequence: 20,
      true_length_nm: 8,
      drawn_length_nm: 8,
      scale: 'to_scale',
      bearing_deg: 180,
    },
  ],
  total_true_length_nm: 8,
  compressed_segment_count: 0,
  long_factor: 3.0,
  nominal_leg_nm: 2.0,
};

/**
 * `stubApi` answers with the first fragment that matches, and the ident URL contains the
 * list URL — so the specific routes are declared first, ahead of everything
 * `positionRoutes` adds, rather than passed as overrides (an override keeps the list key's
 * position). The `/layout` routes are declared before their own procedure-detail route: the
 * detail URL is a substring of the layout URL, so the shorter fragment would otherwise win
 * and hand the layout query a `Procedure` body it cannot read. The list is split by the
 * `kind` query the tab sends, as the server would.
 */
function routes() {
  return {
    [`airports/${ICAO}/procedures/approach/I04R/layout`]: { body: LAYOUT_I04R },
    [`airports/${ICAO}/procedures/approach/I04R`]: { body: PROCEDURE_I04R },
    [`airports/${ICAO}/procedures/approach/R04R/layout`]: {
      body: { ...LAYOUT_I04R, ident: 'R04R', approach_type: 'rnav' },
    },
    [`airports/${ICAO}/procedures/approach/R04R`]: {
      body: { ...PROCEDURE_I04R, ident: 'R04R', approach_type: 'rnav' },
    },
    [`airports/${ICAO}/procedures?kind=sid`]: {
      body: PROCEDURES.filter((procedure) => procedure.kind === 'sid'),
    },
    [`airports/${ICAO}/procedures?kind=approach`]: {
      body: PROCEDURES.filter((procedure) => procedure.kind === 'approach'),
    },
    ...positionRoutes(),
  };
}

function renderTab(family: ProcedureFamily) {
  stubApi(routes());
  const store = setupStore({
    positionDesign: {
      ...initialPositionDesignState,
      icaoInput: ICAO,
      loadedIcao: ICAO,
      activeTab: 'sidstar',
      procedureFamily: family,
    },
  });
  render(
    <Provider store={store}>
      <SidStarTab />
    </Provider>,
  );
  return store;
}

function typeRow() {
  return screen.queryByRole('radiogroup', { name: 'Approach type' });
}

async function openIdentMenu() {
  await userEvent.click(
    screen.getByRole('button', { name: /Choose a procedure|^[A-Z0-9]+$/ }),
  );
  return screen.getByRole('listbox', { name: 'Procedure ident' });
}

describe('the approach-type row', () => {
  it('does not exist under the SID chip — a SID has no approach type', async () => {
    renderTab('sid');
    expect(await screen.findByText('1 in navdata')).toBeInTheDocument();
    expect(typeRow()).not.toBeInTheDocument();
  });

  it('offers only the types this airport publishes, counted, plus All', async () => {
    renderTab('final');
    expect(await screen.findByText('4 in navdata')).toBeInTheDocument();

    const row = typeRow();
    expect(row).toBeInTheDocument();
    const chips = within(row as HTMLElement).getAllByRole('radio');
    expect(chips.map((chip) => chip.textContent)).toEqual([
      'All4',
      'ILS1',
      'RNAV/RNP1',
      'VOR1',
      'Other1',
    ]);
    expect(within(row as HTMLElement).queryByRole('radio', { name: /NDB/ })).toBeNull();
    expect(
      within(row as HTMLElement).getByRole('radio', { name: /All/ }),
    ).toHaveAttribute('aria-checked', 'true');
  });

  it('is hidden when a family publishes a single type — nothing to choose between', async () => {
    renderTab('apptr');
    expect(await screen.findByText('1 in navdata')).toBeInTheDocument();
    expect(typeRow()).not.toBeInTheDocument();
  });
});

describe('picking a type', () => {
  it('narrows the ident list to that type, the count following', async () => {
    renderTab('final');
    await screen.findByText('4 in navdata');

    await userEvent.click(screen.getByRole('radio', { name: /^ILS/ }));

    expect(screen.getByText('1 in navdata')).toBeInTheDocument();
    const list = await openIdentMenu();
    const options = within(list).getAllByRole('option');
    expect(options).toHaveLength(1);
    expect(options[0]?.textContent).toContain('I04R');
    expect(options[0]?.textContent).toContain('ILS');
    expect(within(list).queryByText(/R04R/)).toBeNull();
  });

  it('drops the open procedure, which may no longer be listed', async () => {
    const store = renderTab('final');
    await screen.findByText('4 in navdata');
    act(() => {
      store.dispatch(procedureSelected({ ident: 'R04R', transition: null }));
    });
    // Let its legs arrive before clicking: a re-render landing mid-click would drop it.
    expect(
      await screen.findByText('RNAV/RNP', { selector: '.pos-factrow__value' }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole('radio', { name: /^ILS/ }));

    expect(store.getState().positionDesign.procedure).toBeNull();
  });

  it('says which type is missing rather than "no procedure"', async () => {
    // The chips never offer a type nothing matches, so reach one through the store — the
    // state a refetch could leave behind.
    const store = renderTab('final');
    await screen.findByText('4 in navdata');
    act(() => {
      store.dispatch(approachFilterSelected('ndb'));
    });

    expect(await screen.findByText('0 in navdata')).toBeInTheDocument();
    const list = await openIdentMenu();
    expect(within(list).queryAllByRole('option')).toHaveLength(0);
    expect(list.textContent).toContain('No NDB approach in the navigation data.');
  });
});

describe('an open approach', () => {
  it('badges the ident and reads its type off the server', async () => {
    renderTab('final');
    await screen.findByText('4 in navdata');
    const list = await openIdentMenu();

    await userEvent.click(within(list).getByRole('option', { name: /I04R/ }));

    // The leg row and the facts row both print the constraint, so wait for either.
    expect(await screen.findAllByText('at or above 3000 ft')).not.toHaveLength(0);
    const facts = document.querySelector('.pos-sidstartab__facts');
    expect(facts?.textContent).toContain('Approach type');
    expect(facts?.textContent).toContain('ILS');
  });

  it('draws the to-scale diagram above the leg list, once the layout arrives', async () => {
    renderTab('final');
    await screen.findByText('4 in navdata');
    const list = await openIdentMenu();

    await userEvent.click(within(list).getByRole('option', { name: /I04R/ }));

    expect(
      await screen.findByRole('img', { name: 'Procedure diagram for I04R' }),
    ).toBeInTheDocument();
  });

  it('selecting a node on the diagram picks the same leg the row list would', async () => {
    renderTab('final');
    await screen.findByText('4 in navdata');
    const list = await openIdentMenu();
    await userEvent.click(within(list).getByRole('option', { name: /I04R/ }));
    await screen.findByRole('img', { name: 'Procedure diagram for I04R' });

    await userEvent.click(screen.getByRole('button', { name: 'NERAS' }));

    expect(screen.getByRole('button', { name: 'NERAS' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
});

describe('the 2D/3D diagram selector', () => {
  async function openI04R() {
    const store = renderTab('final');
    await screen.findByText('4 in navdata');
    const list = await openIdentMenu();
    await userEvent.click(within(list).getByRole('option', { name: /I04R/ }));
    await screen.findByRole('img', { name: 'Procedure diagram for I04R' });
    return store;
  }

  it('defaults to 2D, and toggling to 3D and back swaps the rendered branch', async () => {
    await openI04R();

    await userEvent.click(screen.getByRole('button', { name: '3D' }));

    // The Suspense boundary makes the swap asynchronous — a bare queryByTestId would flake.
    expect(await screen.findByTestId('procdiagram3d-stub')).toBeInTheDocument();
    expect(
      screen.queryByRole('img', { name: 'Procedure diagram for I04R' }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '2D' }));

    expect(
      await screen.findByRole('img', { name: 'Procedure diagram for I04R' }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('procdiagram3d-stub')).not.toBeInTheDocument();
  });

  it('the 2D/3D buttons reflect the active mode', async () => {
    await openI04R();

    expect(screen.getByRole('button', { name: '2D' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: '3D' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );

    await userEvent.click(screen.getByRole('button', { name: '3D' }));
    await screen.findByTestId('procdiagram3d-stub');

    expect(screen.getByRole('button', { name: '2D' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByRole('button', { name: '3D' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it("the mocked 3D component receives the loaded airport's position (#178)", async () => {
    await openI04R();

    await userEvent.click(screen.getByRole('button', { name: '3D' }));
    const stub = await screen.findByTestId('procdiagram3d-stub');

    // The airport search answers asynchronously; the prop settles once it lands.
    await waitFor(() => {
      expect(stub).toHaveAttribute(
        'data-airport-position',
        `${String(AIRPORT.position.latitude)},${String(AIRPORT.position.longitude)}`,
      );
    });
  });

  it('the mocked 3D component receives the same selectedSequence a leg-list click would produce', async () => {
    const store = await openI04R();

    await userEvent.click(screen.getByRole('button', { name: '3D' }));
    const stub = await screen.findByTestId('procdiagram3d-stub');
    expect(stub).toHaveAttribute('data-selected-sequence', 'null');

    act(() => {
      store.dispatch(procedureLegSelected(10));
    });

    expect(screen.getByTestId('procdiagram3d-stub')).toHaveAttribute(
      'data-selected-sequence',
      '10',
    );
  });
});
