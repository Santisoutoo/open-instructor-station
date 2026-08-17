/**
 * The Scenarios panel against a stubbed API: the catalogue renders per-row availability
 * with its stated reason, the two-tap run posts to the real endpoint and shows the
 * server's own pending checklist immediately, and the bar can be dismissed without
 * touching the server (there is no cancel endpoint — design §10.6).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ScenarioManifest, ScenarioRunStatus } from '../../api/models';
import { setupStore } from '../../store';
import { ScenariosPanel } from './ScenariosPanel';
import { type Answer, stubApi } from './testApi';

const ENGINE_FAILURE_ID = 'engine-failure-after-v1';
const BIRD_STRIKE_ID = 'bird-strike';
const TCAS_ID = 'tcas-resolution-advisory';

const MANIFEST: ScenarioManifest = {
  adapter: 'fake',
  load_errors: [],
  scenarios: [
    {
      id: ENGINE_FAILURE_ID,
      name: 'Engine failure after V1',
      description: 'Takeoff roll on runway 36. Engine 1 fails just after V1.',
      tags: ['failure', 'takeoff', 'engine'],
      available: true,
      reason: null,
    },
    {
      id: BIRD_STRIKE_ID,
      name: 'Bird strike',
      description: 'Impact on climb-out, engine damage on a trigger.',
      tags: ['failure'],
      available: true,
      reason: null,
    },
    {
      id: TCAS_ID,
      name: 'TCAS resolution advisory',
      description: 'Converging traffic forcing a climb or descend RA.',
      tags: ['traffic'],
      available: false,
      reason:
        "Unavailable on this adapter — the 'fake' adapter does not declare " +
        "can_spawn_traffic, so 'tcas-resolution-advisory' cannot run.",
    },
  ],
};

const PENDING_RUN: ScenarioRunStatus = {
  scenario_id: ENGINE_FAILURE_ID,
  status: 'running',
  steps: [
    { name: 'weather', status: 'pending', detail: null, error: null },
    { name: 'aircraft_state', status: 'pending', detail: null, error: null },
    { name: 'position', status: 'pending', detail: null, error: null },
    { name: 'failures', status: 'pending', detail: null, error: null },
  ],
  started_at: '2026-08-17T12:00:00Z',
  finished_at: null,
};

interface RouteOverrides {
  manifest?: Answer;
  currentRun?: Answer;
  postRun?: { id: string; answer: Answer };
}

/**
 * Routes are handed to `stubApi` most-specific-first: `scenarios/{id}/run` (a POST) before
 * `scenarios/run` (the GET poll) before the bare `scenarios` fallback (the manifest) — the
 * bare fragment is a substring of every one of the others, so it must be checked last.
 */
function renderPanel(overrides: RouteOverrides = {}) {
  const routes: Record<string, Answer> = {};
  if (overrides.postRun !== undefined) {
    routes[`scenarios/${overrides.postRun.id}/run`] = overrides.postRun.answer;
  }
  routes['scenarios/run'] = overrides.currentRun ?? { body: null };
  routes.scenarios = overrides.manifest ?? { body: MANIFEST };

  stubApi(routes);
  const store = setupStore();
  render(
    <Provider store={store}>
      <ScenariosPanel />
    </Provider>,
  );
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ScenariosPanel', () => {
  it('renders every shipped scenario, tags as chips', async () => {
    renderPanel();

    const names = await screen.findAllByRole('heading', { level: 3 });
    expect(names.map((node) => node.textContent)).toEqual([
      'Engine failure after V1',
      'Bird strike',
      'TCAS resolution advisory',
    ]);
    // "failure" tags two of the three cards; the other two chips are unique to one.
    expect(screen.getAllByText('failure')).toHaveLength(2);
    expect(screen.getByText('takeoff')).toBeInTheDocument();
  });

  it('shows the unavailable card disabled, with the server-stated reason', async () => {
    renderPanel();

    const tcas = await screen.findByRole('button', {
      name: /TCAS resolution advisory/,
    });
    expect(tcas).toBeDisabled();
    expect(screen.getByText(/does not declare can_spawn_traffic/)).toBeInTheDocument();
  });

  it('runs a scenario on the second tap and shows the server checklist immediately', async () => {
    renderPanel({ postRun: { id: ENGINE_FAILURE_ID, answer: { body: PENDING_RUN } } });

    const card = await screen.findByRole('button', { name: /Engine failure after V1/ });
    fireEvent.click(card);
    fireEvent.click(screen.getByRole('button', { name: 'Run scenario' }));

    // The bar renders straight from the mutation's own response, before any poll.
    expect(
      await screen.findByText('Engine failure after V1', { selector: 'span' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Set weather')).toBeInTheDocument();
    expect(screen.getByText('Position aircraft')).toBeInTheDocument();

    // Only one scenario runs at a time (D9): every other card's Run button says so.
    fireEvent.click(screen.getByRole('button', { name: /Bird strike/ }));
    expect(screen.getByRole('button', { name: 'A scenario is running…' })).toBeDisabled();
  });

  it('dismisses the bar client-side, without a second request', async () => {
    renderPanel({ currentRun: { body: PENDING_RUN } });

    expect(
      await screen.findByRole('status', { name: 'Active scenario' }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

    expect(screen.queryByRole('status', { name: 'Active scenario' })).toBeNull();
  });

  it('renders a completed run found on mount, with its finished steps', async () => {
    const completed: ScenarioRunStatus = {
      ...PENDING_RUN,
      status: 'completed',
      steps: PENDING_RUN.steps.map((step) => ({ ...step, status: 'done' })),
      finished_at: '2026-08-17T12:00:30Z',
    };
    renderPanel({ currentRun: { body: completed } });

    expect(await screen.findByText('Scenario complete')).toBeInTheDocument();
  });

  it('surfaces a 409 from the run endpoint as a panel error', async () => {
    renderPanel({
      postRun: {
        id: ENGINE_FAILURE_ID,
        answer: {
          status: 409,
          detail: "A scenario is already running ('bird-strike'); wait for it to finish.",
        },
      },
    });

    const card = await screen.findByRole('button', { name: /Engine failure after V1/ });
    fireEvent.click(card);
    fireEvent.click(screen.getByRole('button', { name: 'Run scenario' }));

    expect(await screen.findByText(/A scenario is already running/)).toBeInTheDocument();
  });
});
