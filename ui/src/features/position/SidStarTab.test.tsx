import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import {
  approachFilterSelected,
  initialPositionDesignState,
  procedureSelected,
  type ProcedureFamily,
} from './positionDesignSlice';
import { SidStarTab } from './SidStarTab';
import { stubApi } from './testApi';
import { ICAO, PROCEDURE_I04R, PROCEDURES, positionRoutes } from './testFixtures';

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * `stubApi` answers with the first fragment that matches, and the ident URL contains the
 * list URL — so the specific routes are declared first, ahead of everything
 * `positionRoutes` adds, rather than passed as overrides (an override keeps the list key's
 * position). The list is split by the `kind` query the tab sends, as the server would.
 */
function routes() {
  return {
    [`airports/${ICAO}/procedures/approach/I04R`]: { body: PROCEDURE_I04R },
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
});
