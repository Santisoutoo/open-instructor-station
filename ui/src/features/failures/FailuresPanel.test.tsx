/**
 * The Failures panel smoke against a stubbed API: the gate fails closed until the
 * capabilities answer, then the strip, the search box and the catalogue are up.
 */

import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, FailureCatalogueResponse, FailuresStatus } from '../../api/models';
import { setupStore } from '../../store';
import { FailuresPanel } from './FailuresPanel';
import { stubApi } from './testApi';

const CAPABLE: Capabilities = {
  can_set_position: false,
  can_set_aircraft_state: false,
  can_set_weather: false,
  can_inject_failures: true,
  can_spawn_traffic: false,
  can_control_autopilot: false,
  can_set_fuel_payload: false,
  can_control_camera: false,
  can_pushback: false,
  can_control_cockpit: false,
};

const CATALOGUE: FailureCatalogueResponse = {
  adapter: 'fake',
  caveat: null,
  failures: [
    {
      failure_id: 'engine.fire',
      label: 'Engine fire',
      category: 'engine',
      takes_engine_index: true,
      description: 'An engine fire, requiring the fire checklist.',
      supported: true,
      best_effort: false,
      reason: null,
    },
    {
      failure_id: 'gear.stuck',
      label: 'Landing gear stuck',
      category: 'gear',
      takes_engine_index: false,
      description: 'The landing gear jams and no longer responds to the handle.',
      supported: true,
      best_effort: false,
      reason: null,
    },
  ],
};

const EMPTY_STATUS: FailuresStatus = { active: [], armed: [] };

function readyRoutes() {
  return {
    capabilities: { body: CAPABLE },
    'failures/catalogue': { body: CATALOGUE },
    'failures/status': { body: EMPTY_STATUS },
  };
}

function renderPanel(routes: ReturnType<typeof readyRoutes>) {
  stubApi(routes);
  const store = setupStore();
  render(
    <Provider store={store}>
      <FailuresPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FailuresPanel', () => {
  it('fails closed before the capabilities answer, then opens the catalogue', async () => {
    renderPanel(readyRoutes());

    // Fail closed: no search, no catalogue, a stated reason instead.
    expect(screen.queryByRole('searchbox', { name: 'Search failures' })).toBeNull();

    // The capabilities query resolves and the panel opens.
    expect(
      await screen.findByRole('searchbox', { name: 'Search failures' }),
    ).toBeInTheDocument();
    // The engine category opens first; the other categories are reachable headings.
    expect(await screen.findByText('Engine fire')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Landing gear/ })).toBeInTheDocument();
  });

  it('stays closed, with a stated reason, when the adapter cannot inject failures', async () => {
    renderPanel({
      ...readyRoutes(),
      capabilities: { body: { ...CAPABLE, can_inject_failures: false } },
    });

    expect(
      await screen.findByText(/does not declare can_inject_failures/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });
});
