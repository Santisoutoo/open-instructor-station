/**
 * Submitting the taxi form must emit the exact `taxi_traffic` request body (design
 * §8.6): the ordered route as `GeoPosition`s with `altitude_ft: 0` — ground points —
 * and never fewer than the model's own two-point minimum, because one point is a
 * parking spot, not a route.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MIN_ROUTE_POINTS } from './presets';
import { TaxiTrafficForm } from './TaxiTrafficForm';

function renderForm(disabled = false) {
  const onSpawn = vi.fn();
  render(<TaxiTrafficForm disabled={disabled} onSpawn={onSpawn} />);
  return { onSpawn };
}

async function fillPoint(
  user: ReturnType<typeof userEvent.setup>,
  index: number,
  lat: string,
  lon: string,
): Promise<void> {
  await user.type(screen.getByLabelText(`Point ${String(index)} latitude`), lat);
  await user.type(screen.getByLabelText(`Point ${String(index)} longitude`), lon);
}

describe('TaxiTrafficForm', () => {
  it('starts with the two-point minimum and will not spawn while they are blank', () => {
    renderForm();

    expect(MIN_ROUTE_POINTS).toBe(2);
    expect(screen.getByLabelText('Point 1 latitude')).toHaveValue(null);
    expect(screen.getByLabelText('Point 2 latitude')).toHaveValue(null);
    expect(screen.getByRole('button', { name: /spawn taxi traffic/i })).toBeDisabled();
  });

  it('spawns a two-point route as ground GeoPositions, defaults stated', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await fillPoint(user, 1, '40.49', '-3.56');
    await fillPoint(user, 2, '40.5', '-3.57');
    await user.click(screen.getByRole('button', { name: /spawn taxi traffic/i }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    expect(onSpawn).toHaveBeenCalledWith({
      type: 'taxi_traffic',
      route: [
        { latitude: 40.49, longitude: -3.56, altitude_ft: 0 },
        { latitude: 40.5, longitude: -3.57, altitude_ft: 0 },
      ],
      speed_kt: null,
      kind: 'aircraft',
      callsign: 'TAXI01',
    });
  });

  it('sends an added third point, a stated speed and the picked kind', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await fillPoint(user, 1, '40.49', '-3.56');
    await fillPoint(user, 2, '40.5', '-3.57');
    await user.click(screen.getByRole('button', { name: /add point/i }));
    await fillPoint(user, 3, '40.51', '-3.58');
    await user.type(screen.getByLabelText(/taxi speed/i), '8');
    await user.click(screen.getByRole('button', { name: 'ground vehicle' }));
    const callsign = screen.getByLabelText(/callsign/i);
    await user.clear(callsign);
    await user.type(callsign, 'FOL12');
    await user.click(screen.getByRole('button', { name: /spawn taxi traffic/i }));

    expect(onSpawn).toHaveBeenCalledWith({
      type: 'taxi_traffic',
      route: [
        { latitude: 40.49, longitude: -3.56, altitude_ft: 0 },
        { latitude: 40.5, longitude: -3.57, altitude_ft: 0 },
        { latitude: 40.51, longitude: -3.58, altitude_ft: 0 },
      ],
      speed_kt: 8,
      kind: 'ground_vehicle',
      callsign: 'FOL12',
    });
  });

  it('never lets the route drop below two points', () => {
    renderForm();

    expect(screen.getByRole('button', { name: /remove point 1/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /remove point 2/i })).toBeDisabled();
  });

  it('will not spawn an out-of-range coordinate', async () => {
    const user = userEvent.setup();
    renderForm();

    await fillPoint(user, 1, '91', '-3.56');
    await fillPoint(user, 2, '40.5', '-3.57');

    expect(screen.getByRole('button', { name: /spawn taxi traffic/i })).toBeDisabled();
  });

  it('disables the spawn button while the gate is closed', () => {
    renderForm(true);

    expect(screen.getByRole('button', { name: /spawn taxi traffic/i })).toBeDisabled();
  });
});
