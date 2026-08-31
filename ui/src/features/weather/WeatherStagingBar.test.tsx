/**
 * The staging bar in isolation: label variants (staged preset vs. manual weather) and the
 * Apply-disabled state — the panel-level flows through `WeatherPanel.test.tsx` already cover
 * the wiring, this is just the component's own render contract.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { WeatherState } from '../../api/models';
import { WeatherStagingBar } from './WeatherStagingBar';

const RESOLVED: WeatherState = {
  wind_layers: [
    { altitude_ft: 0, direction_deg: 270, speed_kt: 5, gust_increase_kt: 0, turbulence_ratio: 0 },
  ],
  cloud_layers: [],
  visibility_m: 10000,
  qnh_hpa: 1016,
  temperature_c: 19,
  dewpoint_c: 7,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};

interface RenderOverrides {
  presetLabel?: string;
  disabledReason?: string | null;
}

function renderBar(overrides: RenderOverrides = {}) {
  const onApply = vi.fn();
  const onDismiss = vi.fn();
  render(
    <WeatherStagingBar
      {...(overrides.presetLabel !== undefined ? { presetLabel: overrides.presetLabel } : {})}
      resolved={RESOLVED}
      applying={false}
      disabledReason={overrides.disabledReason ?? null}
      errorText={null}
      onApply={onApply}
      onDismiss={onDismiss}
    />,
  );
  return { onApply, onDismiss };
}

describe('WeatherStagingBar', () => {
  it('shows "Staged: {label}" when a preset is staged', () => {
    renderBar({ presetLabel: 'CAVOK' });
    expect(screen.getByText('Staged: CAVOK')).toBeInTheDocument();
  });

  it('shows "Manual weather" when nothing was staged from a preset', () => {
    renderBar();
    expect(screen.getByText('Manual weather')).toBeInTheDocument();
  });

  it('fires onApply and onDismiss', async () => {
    const user = userEvent.setup();
    const { onApply, onDismiss } = renderBar({ presetLabel: 'CAVOK' });
    await user.click(screen.getByRole('button', { name: 'Apply weather' }));
    expect(onApply).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('disables Apply and shows the reason when disabledReason is set', () => {
    renderBar({ disabledReason: 'No changes yet — edit a field to apply.' });
    expect(screen.getByRole('button', { name: 'Apply weather' })).toBeDisabled();
    expect(screen.getByText('No changes yet — edit a field to apply.')).toBeInTheDocument();
  });

  it('leaves Apply enabled when disabledReason is null', () => {
    renderBar({ presetLabel: 'CAVOK', disabledReason: null });
    expect(screen.getByRole('button', { name: 'Apply weather' })).toBeEnabled();
  });
});
