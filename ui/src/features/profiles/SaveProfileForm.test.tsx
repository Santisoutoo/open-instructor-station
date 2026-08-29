/**
 * `SaveProfileForm` against a stubbed API: disabled with the stated reason when nothing is
 * staged in Position (D11), and the composed `TrainingProfileCreate` body matches the
 * staged placement + overrides + locally-built failure list exactly.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FailureCatalogueResponse, PlacementRequest } from '../../api/models';
import { type RootState, setupStore } from '../../store';
import { SaveProfileForm } from './SaveProfileForm';
import { callsTo, stubApi } from './testApi';

const STAGED_PLACEMENT: Extract<PlacementRequest, { type: 'coordinate' }> = {
  type: 'coordinate',
  position: { latitude: 40.0, longitude: -3.0, altitude_ft: 3000 },
  heading_deg: 90,
  ias_kt: 120,
};

const CATALOGUE: FailureCatalogueResponse = {
  adapter: 'fake',
  caveat: null,
  failures: [
    {
      failure_id: 'airframe.smoke',
      label: 'Smoke in cockpit',
      category: 'airframe',
      takes_engine_index: false,
      description: 'Smoke fills the cockpit.',
      supported: true,
      best_effort: false,
      reason: null,
    },
    {
      failure_id: 'engine.failure',
      label: 'Engine failure',
      category: 'engine',
      takes_engine_index: true,
      description: 'Total loss of engine power.',
      supported: true,
      best_effort: false,
      reason: null,
    },
  ],
};

function buildState(overrides: Partial<RootState['position']> = {}): Partial<RootState> {
  return {
    position: {
      selectedIcao: null,
      selectedRunwayIdent: null,
      activeTab: 'coordinate',
      openProcedure: null,
      staged: STAGED_PLACEMENT,
      setupOverrides: {},
      recentIcaos: [],
      ...overrides,
    },
  };
}

function renderForm(preloadedState?: Partial<RootState>) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <SaveProfileForm />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SaveProfileForm', () => {
  it('is disabled with a stated reason when nothing is staged in Position', () => {
    stubApi({ 'failures/catalogue': { body: CATALOGUE } });
    renderForm();

    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled();
    expect(
      screen.getByText(/Stage a placement in Position first/),
    ).toBeInTheDocument();
  });

  it('is disabled with a stated reason when a placement is staged but no name is given', () => {
    stubApi({ 'failures/catalogue': { body: CATALOGUE } });
    renderForm(buildState());

    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled();
    expect(screen.getByText('Give the profile a name.')).toBeInTheDocument();
  });

  it('composes the exact TrainingProfileCreate body from staged placement + overrides + failures', async () => {
    const { calls } = stubApi({
      'failures/catalogue': { body: CATALOGUE },
      profiles: {
        body: {
          format_version: 1,
          profile_id: 'a'.repeat(32),
          name: 'Circuit practice',
          description: '',
          author: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          scenario: { name: 'Circuit practice', description: '', tags: [] },
        },
      },
    });
    renderForm(buildState({ setupOverrides: { flaps_ratio: 0.5 } }));

    await userEvent.type(screen.getByLabelText('Name'), 'Circuit practice');

    // Add one immediate failure through the inline builder.
    await userEvent.selectOptions(
      await screen.findByLabelText('Failure'),
      'airframe.smoke',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));

    expect(screen.getByRole('button', { name: 'Save profile' })).not.toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    const posted = callsTo(calls, '/api/profiles').find((call) => call.method === 'POST');
    expect(posted?.body).toEqual({
      name: 'Circuit practice',
      description: '',
      author: null,
      scenario: {
        name: 'Circuit practice',
        description: 'Circuit practice',
        tags: [],
        position: STAGED_PLACEMENT,
        aircraft_state: { flaps_ratio: 0.5 },
        weather: null,
        failures: {
          immediate: [{ failure_id: 'airframe.smoke', engine_index: null }],
          armed: [],
        },
        traffic: null,
      },
    });
  });

  it('an engine-indexed failure always carries a valid engine index -- never a blank one', async () => {
    /**
     * Regression: the engine-index field used to default to '', so adding an indexed
     * failure without ever touching the field silently produced `engine_index: null`
     * -- an entry the server would 422 on save, with no earlier feedback. It now
     * defaults to 1, matching `FailureRow.tsx`'s own established pattern.
     */
    const { calls } = stubApi({
      'failures/catalogue': { body: CATALOGUE },
      profiles: {
        body: {
          format_version: 1,
          profile_id: 'a'.repeat(32),
          name: 'V1 cut',
          description: '',
          author: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          scenario: { name: 'V1 cut', description: '', tags: [] },
        },
      },
    });
    renderForm(buildState());

    await userEvent.type(screen.getByLabelText('Name'), 'V1 cut');

    // Add the indexed failure WITHOUT touching the engine-index field.
    await userEvent.selectOptions(await screen.findByLabelText('Failure'), 'engine.failure');
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    const posted = callsTo(calls, '/api/profiles').find((call) => call.method === 'POST');
    const body = posted?.body as { scenario: { failures: { immediate: unknown[] } } };
    expect(body.scenario.failures.immediate).toEqual([
      { failure_id: 'engine.failure', engine_index: 1 },
    ]);
  });
});
