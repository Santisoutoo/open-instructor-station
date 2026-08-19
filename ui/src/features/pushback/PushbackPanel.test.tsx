/**
 * The panel end to end, pre-wiring: the gate fails closed, the stage-then-execute
 * flow arms and disarms honestly, and — the load-bearing assertion — what the
 * callbacks emit is the EXACT wire shape (`direction`/`distance_m`/`angle_deg`),
 * asserted with deep equality so no field can silently default or stow away. The
 * callbacks stand in for the RTK Query hooks until the wiring wave.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Capabilities } from '../../api/models';
import { PushbackPanel } from './PushbackPanel';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: false,
    can_set_aircraft_state: false,
    can_set_weather: false,
    can_inject_failures: false,
    can_spawn_traffic: false,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: true,
    ...overrides,
  };
}

// 'absent' models "no answer yet/ever" — an explicit `undefined` argument would be
// swallowed by the default parameter.
function renderPanel(
  caps: Capabilities | 'absent' = capabilities(),
  capabilitiesError = false,
) {
  const onPreview = vi.fn();
  const onExecute = vi.fn();
  render(
    <PushbackPanel
      capabilities={caps === 'absent' ? undefined : caps}
      capabilitiesError={capabilitiesError}
      onPreview={onPreview}
      onExecute={onExecute}
    />,
  );
  return { onPreview, onExecute };
}

describe('PushbackPanel', () => {
  it('previews the one-tap default — straight back, 20 m — as the exact wire shape', () => {
    const { onPreview } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(onPreview).toHaveBeenCalledWith({
      direction: 'straight',
      distance_m: 20,
      angle_deg: 0,
    });
  });

  it('stages a right arc and executes exactly what was staged (D5 field for field)', () => {
    const { onPreview, onExecute } = renderPanel();

    // Execute is disarmed until something is staged.
    const executeButton = screen.getByRole('button', { name: 'Execute pushback' });
    expect(executeButton).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Nose right' }));
    fireEvent.change(screen.getByRole('slider', { name: 'Pushback distance' }), {
      target: { value: '30' },
    });
    fireEvent.change(screen.getByRole('slider', { name: 'Pushback turn angle' }), {
      target: { value: '60' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    const request = { direction: 'right', distance_m: 30, angle_deg: 60 };
    expect(onPreview).toHaveBeenCalledWith(request);

    expect(executeButton).toBeEnabled();
    fireEvent.click(executeButton);
    expect(onExecute).toHaveBeenCalledTimes(1);
    expect(onExecute).toHaveBeenCalledWith(request);
  });

  it('disarms Execute again on any edit after staging — a stale preview never runs', () => {
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    const executeButton = screen.getByRole('button', { name: 'Execute pushback' });
    expect(executeButton).toBeEnabled();

    fireEvent.change(screen.getByRole('slider', { name: 'Pushback distance' }), {
      target: { value: '40' },
    });

    expect(executeButton).toBeDisabled();
  });

  it('zeroes the angle in the emitted request when returning to straight', () => {
    const { onPreview } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Nose left' }));
    fireEvent.click(screen.getByRole('button', { name: 'Straight' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(onPreview).toHaveBeenCalledWith({
      direction: 'straight',
      distance_m: 20,
      angle_deg: 0,
    });
  });

  it('fails closed while the capabilities are loading: reason shown, all controls dead', () => {
    renderPanel('absent', false);

    expect(screen.getByRole('status')).toHaveTextContent(/waiting/i);
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Execute pushback' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Nose right' })).toBeDisabled();
    expect(screen.getByRole('slider', { name: 'Pushback distance' })).toBeDisabled();
  });

  it('fails closed without can_pushback and names the missing capability', () => {
    renderPanel(capabilities({ can_pushback: false }));

    expect(screen.getByRole('status')).toHaveTextContent('can_pushback');
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
  });
});
