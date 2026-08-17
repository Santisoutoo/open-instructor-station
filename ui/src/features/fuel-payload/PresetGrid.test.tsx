/**
 * Each tile stages the exact `FuelPayloadRequest` a preset resolves to — no manual
 * overlay, no override — and every tile disables with the manifest's reason when the
 * airframe's capacities are unknown (§2.2 / §9.5 of the design).
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import type { FuelPayloadManifest } from '../../api/models';
import { setupStore } from '../../store';
import { PresetGrid } from './PresetGrid';

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

function renderGrid(manifest: FuelPayloadManifest, disabled = false) {
  const store = setupStore();
  render(
    <Provider store={store}>
      <PresetGrid manifest={manifest} disabled={disabled} />
    </Provider>,
  );
  return store;
}

describe('<PresetGrid />', () => {
  it('stages the exact request for each preset tapped', async () => {
    const user = userEvent.setup();
    const store = renderGrid(MANIFEST);

    await user.click(screen.getByRole('button', { name: /training/i }));

    expect(store.getState().fuelPayload.staged).toEqual({
      preset: 'training',
      loadout: null,
      override_envelope: false,
    });

    await user.click(screen.getByRole('button', { name: /^ferry/i }));

    expect(store.getState().fuelPayload.staged).toEqual({
      preset: 'ferry',
      loadout: null,
      override_envelope: false,
    });
  });

  it('marks the staged tile pressed', async () => {
    const user = userEvent.setup();
    renderGrid(MANIFEST);

    await user.click(screen.getByRole('button', { name: /^full/i }));

    expect(screen.getByRole('button', { name: /^full/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: /training/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('disables every tile with the manifest reason when capacities are unknown', () => {
    renderGrid({ ...MANIFEST, limits_source: 'unknown' });

    for (const label of [/empty/i, /training/i, /^full/i, /^ferry/i]) {
      expect(screen.getByRole('button', { name: label })).toBeDisabled();
    }
    expect(
      screen.getAllByText(/needs the airframe's known tank and station capacities/i),
    ).toHaveLength(4);
  });

  it('disables every tile when the panel gate itself is closed', () => {
    renderGrid(MANIFEST, true);

    expect(screen.getByRole('button', { name: /training/i })).toBeDisabled();
  });
});
