/**
 * Submitting the incursion form must emit the exact `runway_incursion` request body —
 * `toEqual`, every field explicit (design §8.6) — and must refuse to submit without a
 * named runway, because the server would only 404 what the form already knows is
 * missing.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { RunwayIncursionForm } from './RunwayIncursionForm';

function renderForm(disabled = false) {
  const onSpawn = vi.fn();
  render(<RunwayIncursionForm disabled={disabled} onSpawn={onSpawn} />);
  return { onSpawn };
}

describe('RunwayIncursionForm', () => {
  it('will not spawn without both an airport and a runway', async () => {
    const user = userEvent.setup();
    renderForm();
    const submit = screen.getByRole('button', { name: /spawn runway incursion/i });

    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/airport icao/i), 'LEMD');
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/^runway$/i), '32L');
    expect(submit).toBeEnabled();
  });

  it('spawns with the documented defaults stated explicitly', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.type(screen.getByLabelText(/airport icao/i), 'lemd');
    await user.type(screen.getByLabelText(/^runway$/i), '32l');
    await user.click(screen.getByRole('button', { name: /spawn runway incursion/i }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    expect(onSpawn).toHaveBeenCalledWith({
      type: 'runway_incursion',
      airport_icao: 'LEMD',
      runway_ident: '32L',
      cross_at_along_track_nm: 0,
      lead_time_before_user_arrival_s: 8,
      from_side: 'left',
      vehicle_speed_kt: null,
      kind: 'ground_vehicle',
      callsign: 'GND01',
    });
  });

  it('sends exactly what the instructor typed, including a negative lead time', async () => {
    // A negative lead time is the worst-case incursion — still crossing when the user
    // arrives — and must reach the server as typed, never clamped client-side.
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.type(screen.getByLabelText(/airport icao/i), 'LEMD');
    await user.type(screen.getByLabelText(/^runway$/i), '32L');
    const crossAt = screen.getByLabelText(/crossing offset/i);
    await user.clear(crossAt);
    await user.type(crossAt, '0.5');
    const leadTime = screen.getByLabelText(/lead time/i);
    await user.clear(leadTime);
    await user.type(leadTime, '-3');
    await user.type(screen.getByLabelText(/vehicle speed/i), '25');
    await user.click(screen.getByRole('button', { name: 'right' }));
    await user.click(screen.getByRole('button', { name: 'aircraft' }));
    const callsign = screen.getByLabelText(/callsign/i);
    await user.clear(callsign);
    await user.type(callsign, 'TWY07');
    await user.click(screen.getByRole('button', { name: /spawn runway incursion/i }));

    expect(onSpawn).toHaveBeenCalledWith({
      type: 'runway_incursion',
      airport_icao: 'LEMD',
      runway_ident: '32L',
      cross_at_along_track_nm: 0.5,
      lead_time_before_user_arrival_s: -3,
      from_side: 'right',
      vehicle_speed_kt: 25,
      kind: 'aircraft',
      callsign: 'TWY07',
    });
  });

  it('disables the spawn button while the gate is closed', () => {
    renderForm(true);

    expect(
      screen.getByRole('button', { name: /spawn runway incursion/i }),
    ).toBeDisabled();
  });
});
