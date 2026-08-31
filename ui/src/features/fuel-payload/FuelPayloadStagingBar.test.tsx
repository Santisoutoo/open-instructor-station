/**
 * The staging bar, against a stubbed API.
 *
 * `fetch` is stubbed rather than the RTK Query hooks mocked (the `features/position`
 * precedent, reused here via `testApi.ts`), so the requests the panel actually sends —
 * their URL, their body — are observable and can be asserted. The guarantee under test:
 * a verifiably out-of-envelope preview disables Apply until the instructor explicitly
 * ticks the override, and the confirmation reports the read-back, never the request.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  FuelPayloadApplyResult,
  FuelPayloadManifest,
  FuelPayloadPreview,
  FuelPayloadRequest,
} from '../../api/models';
import { type RootState, setupStore } from '../../store';
import { type Answer, callsTo, stubApi } from '../position/testApi';
import { FuelPayloadStagingBar } from './FuelPayloadStagingBar';

const TRAINING_REQUEST: FuelPayloadRequest = {
  preset: 'training',
  loadout: null,
  override_envelope: false,
};

const FULL_REQUEST: FuelPayloadRequest = {
  preset: 'full',
  loadout: null,
  override_envelope: false,
};

const MANIFEST: FuelPayloadManifest = {
  adapter: 'fake',
  supported: true,
  reason: null,
  icao_type: 'C172',
  limits_source: 'table',
  limits_note: 'Illustrative C172S figures.',
  limits: null,
  tank_count: 2,
  station_count: 3,
  presets: [
    { id: 'empty', label: 'Empty', description: 'Ramp weight, nobody aboard.' },
    { id: 'training', label: 'Training', description: 'Light, safe, middle of the envelope.' },
    { id: 'full', label: 'Full', description: 'Every tank and station at capacity.' },
    { id: 'ferry', label: 'Ferry', description: 'Full tanks, no payload.' },
  ],
};

const TANKS = [
  { tank_index: 0, fuel_kg: 38.0 },
  { tank_index: 1, fuel_kg: 38.0 },
];

const PREVIEW_TRAINING: FuelPayloadPreview = {
  request: TRAINING_REQUEST,
  loadout: { tanks: TANKS, stations: [] },
  mass_and_balance: {
    gross_weight_kg: 840.5,
    fuel_kg: 76.0,
    payload_kg: 21.5,
    cg_arm_in: 40.44,
    limits_source: 'table',
    within_envelope: true,
    violations: [],
  },
  notes: ["Fuel — 50% of 2 tanks (76.0 kg total) — the 'training' preset."],
};

const PREVIEW_FULL_VIOLATED: FuelPayloadPreview = {
  request: FULL_REQUEST,
  loadout: { tanks: TANKS, stations: [] },
  mass_and_balance: {
    gross_weight_kg: 1110.0,
    fuel_kg: 152.0,
    payload_kg: 215.0,
    cg_arm_in: 44.95,
    limits_source: 'table',
    within_envelope: false,
    violations: ['CG at 44.95 in is aft of the 40.15 in aft limit at 1,110 kg.'],
  },
  notes: [],
};

const APPLY_RESULT: FuelPayloadApplyResult = {
  applied: PREVIEW_FULL_VIOLATED.loadout,
  state: {
    loadout: PREVIEW_FULL_VIOLATED.loadout,
    mass_and_balance: PREVIEW_FULL_VIOLATED.mass_and_balance,
  },
  notes: [],
};

function fuelPayloadState(overrides: Partial<RootState['fuelPayload']> = {}) {
  return {
    fuelPayload: {
      selectedPresetId: null,
      overlay: {},
      overrideEnvelope: false,
      staged: null,
      ...overrides,
    },
  };
}

function renderBar(preloaded: Partial<RootState>) {
  const store = setupStore(preloaded);
  render(
    <Provider store={store}>
      <FuelPayloadStagingBar />
    </Provider>,
  );
  return store;
}

const BASE_ROUTES: Record<string, Answer> = {
  'fuel-payload/manifest': { body: MANIFEST },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('<FuelPayloadStagingBar />', () => {
  it('says nothing changes when nothing is staged', () => {
    stubApi(BASE_ROUTES);
    renderBar(fuelPayloadState());

    expect(screen.getByText(/nothing changes until you press/i)).toBeInTheDocument();
  });

  it('previews a staged loadout without applying it', async () => {
    const { calls } = stubApi({
      ...BASE_ROUTES,
      'fuel-payload/preview': { body: PREVIEW_TRAINING },
    });
    renderBar(fuelPayloadState({ selectedPresetId: 'training', staged: TRAINING_REQUEST }));

    await screen.findByText('76 kg');

    expect(callsTo(calls, 'fuel-payload/preview')).toHaveLength(1);
    expect(callsTo(calls, 'fuel-payload/apply')).toHaveLength(0);
  });

  it('disables Apply until the override checkbox is ticked, then re-enables it', async () => {
    const user = userEvent.setup();
    stubApi({ ...BASE_ROUTES, 'fuel-payload/preview': { body: PREVIEW_FULL_VIOLATED } });
    renderBar(fuelPayloadState({ selectedPresetId: 'full', staged: FULL_REQUEST }));

    await screen.findByRole('checkbox', { name: /load anyway/i });

    const applyButton = screen.getByRole('button', { name: /apply loadout/i });
    expect(applyButton).toBeDisabled();

    await user.click(screen.getByRole('checkbox', { name: /load anyway/i }));

    await waitFor(() => {
      expect(applyButton).not.toBeDisabled();
    });
  });

  it('sends the staged request verbatim, including override_envelope', async () => {
    const user = userEvent.setup();
    const { calls } = stubApi({
      ...BASE_ROUTES,
      'fuel-payload/preview': { body: PREVIEW_FULL_VIOLATED },
      'fuel-payload/apply': { body: APPLY_RESULT },
    });
    renderBar(fuelPayloadState({ selectedPresetId: 'full', staged: FULL_REQUEST }));
    await screen.findByRole('checkbox', { name: /load anyway/i });

    await user.click(screen.getByRole('checkbox', { name: /load anyway/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /apply loadout/i })).not.toBeDisabled();
    });
    await user.click(screen.getByRole('button', { name: /apply loadout/i }));

    await waitFor(() => {
      const apply = calls.find((call) => call.url.includes('fuel-payload/apply'));
      expect(apply?.body).toEqual({ ...FULL_REQUEST, override_envelope: true });
    });
  });

  it('confirms the read-back rather than the request', async () => {
    const user = userEvent.setup();
    stubApi({
      ...BASE_ROUTES,
      'fuel-payload/preview': { body: PREVIEW_FULL_VIOLATED },
      'fuel-payload/apply': { body: APPLY_RESULT },
    });
    renderBar(fuelPayloadState({ selectedPresetId: 'full', staged: FULL_REQUEST }));
    await screen.findByRole('checkbox', { name: /load anyway/i });
    await user.click(screen.getByRole('checkbox', { name: /load anyway/i }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /apply loadout/i })).not.toBeDisabled();
    });

    await user.click(screen.getByRole('button', { name: /apply loadout/i }));

    expect(await screen.findByText(/applied — 1110 kg gross, 152 kg fuel/i)).toBeInTheDocument();
  });

  it('renders a failure inline instead of in a modal', async () => {
    const user = userEvent.setup();
    stubApi({
      ...BASE_ROUTES,
      'fuel-payload/preview': { body: PREVIEW_TRAINING },
      'fuel-payload/apply': {
        status: 422,
        detail: "The 'fake' adapter does not declare can_set_fuel_payload.",
      },
    });
    renderBar(fuelPayloadState({ selectedPresetId: 'training', staged: TRAINING_REQUEST }));
    await screen.findByText('76 kg');

    await user.click(screen.getByRole('button', { name: /apply loadout/i }));

    expect(
      await screen.findByText(/does not declare can_set_fuel_payload/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
