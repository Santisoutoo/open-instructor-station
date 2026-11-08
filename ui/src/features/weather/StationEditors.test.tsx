import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import type { WeatherState } from '../../api/models';
import type { AtmosphereSelection } from './AtmosphereProfile';
import { StationEditors } from './StationEditors';

const INITIAL: WeatherState = {
  wind_layers: [],
  cloud_layers: [],
  visibility_m: 25000,
  qnh_hpa: 920.25,
  temperature_c: 55,
  dewpoint_c: -55,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};
function Harness() {
  const [state, setState] = useState(INITIAL);
  const [selection, onSelect] = useState<AtmosphereSelection | null>(null);
  const [invalid, onInvalidChange] = useState(false);
  return (
    <>
      <StationEditors
        resolved={state}
        selection={selection}
        onSelect={onSelect}
        disabled={false}
        onInvalidChange={onInvalidChange}
        onField={(field, value) =>
          setState((previous) => ({ ...previous, [field]: value }))
        }
      />
      <output data-testid="state">{JSON.stringify(state)}</output>
      <output data-testid="invalid">{String(invalid)}</output>
    </>
  );
}
function state(): WeatherState {
  return JSON.parse(screen.getByTestId('state').textContent ?? '{}') as WeatherState;
}

describe('StationEditors', () => {
  it('adds three ordered wind and cloud layers, blocks a fourth, and removes both lists completely', () => {
    render(<Harness />);
    for (let i = 0; i < 3; i++)
      fireEvent.click(screen.getByRole('button', { name: 'Add wind layer' }));
    expect(state().wind_layers.map((layer) => layer.altitude_ft)).toEqual([
      0, 2000, 4000,
    ]);
    expect(screen.getByRole('button', { name: 'Add wind layer' })).toBeDisabled();
    for (let i = 0; i < 3; i++)
      fireEvent.click(screen.getByRole('button', { name: 'Add cloud layer' }));
    expect(state().cloud_layers.map((layer) => layer.base_ft)).toEqual([
      3000, 6000, 9000,
    ]);
    expect(screen.getByRole('button', { name: 'Add cloud layer' })).toBeDisabled();
    for (let i = 0; i < 3; i++)
      fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(state().cloud_layers).toEqual([]);
    for (let i = 0; i < 3; i++)
      fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(state().wind_layers).toEqual([]);
  });

  it('retains a blank and its invalid status when another layer is selected', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Add wind layer' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Speed (kt)' }), {
      target: { value: '' },
    });
    expect(screen.getByTestId('invalid')).toHaveTextContent('true');
    fireEvent.click(screen.getByRole('button', { name: 'Add cloud layer' }));
    expect(screen.getByTestId('invalid')).toHaveTextContent('true');
    fireEvent.click(screen.getByRole('button', { name: /Wind 1/ }));
    expect(screen.getByRole('spinbutton', { name: 'Speed (kt)' })).toHaveValue(null);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Speed (kt)' }), {
      target: { value: '125.5' },
    });
    expect(state().wind_layers[0]?.speed_kt).toBe(125.5);
    expect(screen.getByTestId('invalid')).toHaveTextContent('false');
  });

  it('rejects neighbor collisions without altering the draft and preserves values beyond old UI limits', () => {
    render(<Harness />);
    expect(screen.getByRole('spinbutton', { name: 'QNH (hPa)' })).toHaveValue(920.25);
    expect(screen.getByRole('spinbutton', { name: 'Temperature (°C)' })).toHaveValue(55);
    expect(screen.getByRole('spinbutton', { name: 'Visibility (m)' })).toHaveValue(25000);
    fireEvent.click(screen.getByRole('button', { name: 'Add wind layer' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add wind layer' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Altitude (ft MSL)' }), {
      target: { value: '50' },
    });
    expect(state().wind_layers[1]?.altitude_ft).toBe(2000);
    expect(screen.getByRole('spinbutton', { name: 'Altitude (ft MSL)' })).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Altitude (ft MSL)' }), {
      target: { value: '100' },
    });
    expect(state().wind_layers[1]?.altitude_ft).toBe(100);
    expect(screen.getByTestId('invalid')).toHaveTextContent('false');
  });
});

describe('layer identity', () => {
  it('drops an invalid removed field without transferring its draft to the following layer', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Add wind layer' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add wind layer' }));
    fireEvent.click(screen.getByRole('button', { name: /Wind 1/ }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Speed (kt)' }), {
      target: { value: '' },
    });
    expect(screen.getByTestId('invalid')).toHaveTextContent('true');
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.getByRole('spinbutton', { name: 'Speed (kt)' })).toHaveValue(15);
    expect(screen.getByTestId('invalid')).toHaveTextContent('false');
  });
});
