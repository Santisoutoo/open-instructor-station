/**
 * `AtmosphereProfile`'s drag/select/keyboard surface — house style of `CircuitDiagram.test.tsx`:
 * literal percentage-string assertions on the overlay buttons' positions.
 *
 * jsdom returns an all-zero `getBoundingClientRect()` by default, which would divide the drag's
 * ft-per-px conversion by zero — every test in this file mocks it to the component's real
 * viewBox size, on `Element.prototype` so it also covers the `<svg>` element (not just
 * `HTMLElement.prototype`, which doesn't).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CloudLayer, WeatherState, WindLayer } from '../../api/models';
import { formatWind } from './format';
import { altitudeToY } from './atmosphereProjection';
import { AtmosphereProfile, type AtmosphereProfileProps, type AtmosphereSelection } from './AtmosphereProfile';

function cloudLayer(overrides: Partial<CloudLayer> = {}): CloudLayer {
  return {
    base_ft: 3000,
    tops_ft: 5000,
    coverage_ratio: 0.75,
    cloud_type: 'cumulus',
    ...overrides,
  };
}

function windLayer(overrides: Partial<WindLayer> = {}): WindLayer {
  return {
    altitude_ft: 2000,
    direction_deg: 270,
    speed_kt: 15,
    gust_increase_kt: 0,
    turbulence_ratio: 0,
    ...overrides,
  };
}

const FIXTURE_STATE: WeatherState = {
  wind_layers: [
    windLayer({ altitude_ft: 2000, direction_deg: 270, speed_kt: 15, gust_increase_kt: 0 }),
    windLayer({ altitude_ft: 6000, direction_deg: 300, speed_kt: 25, gust_increase_kt: 10 }),
  ],
  cloud_layers: [
    cloudLayer({ base_ft: 3000, tops_ft: 5000, coverage_ratio: 0.75, cloud_type: 'cumulus' }),
    cloudLayer({ base_ft: 7000, tops_ft: 8000, coverage_ratio: 1.0, cloud_type: 'stratus' }),
  ],
  visibility_m: 10000,
  qnh_hpa: 1013,
  temperature_c: 15,
  dewpoint_c: 10,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};

// Scale top for this fixture: max(10000, highest of {8000 tops, 6000 wind} + 2000) = 10000.
const SCALE = { topFt: 10000, bottomFt: 0 as const };

function renderProfile(overrides: Partial<AtmosphereProfileProps> = {}) {
  const onWindLayersChange = vi.fn();
  const onCloudLayersChange = vi.fn();
  const onSelect = vi.fn();
  const result = render(
    <AtmosphereProfile
      state={FIXTURE_STATE}
      fieldElevationFt={1000}
      selection={null}
      readOnly={false}
      onWindLayersChange={onWindLayersChange}
      onCloudLayersChange={onCloudLayersChange}
      onSelect={onSelect}
      {...overrides}
    />,
  );
  return { ...result, onWindLayersChange, onCloudLayersChange, onSelect };
}

beforeEach(() => {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
    top: 0,
    left: 0,
    width: 400,
    height: 480,
    right: 400,
    bottom: 480,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
});

describe('rendering counts', () => {
  it('renders one band per cloud layer and one wind visual per wind layer', () => {
    const { container } = renderProfile();
    expect(container.querySelectorAll('.atmo__cloud-band')).toHaveLength(2);
    expect(container.querySelectorAll('.atmo__barb, .atmo__barb-calm')).toHaveLength(2);
  });

  it('renders zero of either for empty lists, scale still present', () => {
    const { container } = renderProfile({
      state: { ...FIXTURE_STATE, wind_layers: [], cloud_layers: [] },
    });
    expect(container.querySelectorAll('.atmo__cloud-band')).toHaveLength(0);
    expect(container.querySelectorAll('.atmo__barb, .atmo__barb-calm')).toHaveLength(0);
    expect(container.querySelectorAll('.atmo__scale line').length).toBeGreaterThan(0);
  });
});

describe('cloud band classes', () => {
  it('maps cloud_type and coverage_ratio to the stated classes, and sets fill-opacity', () => {
    const { container } = renderProfile();
    const bands = container.querySelectorAll('.atmo__cloud-band');
    // Layer 0: cumulus, 0.75 -> 6 octas -> BKN.
    expect(bands[0]?.classList.contains('atmo__cloud-band--cumulus')).toBe(true);
    expect(bands[0]?.classList.contains('atmo__cloud-band--bkn')).toBe(true);
    expect(bands[0]?.getAttribute('fill-opacity')).toBe(String(0.25 + 0.6 * 0.75));
    // Layer 1: stratus, 1.0 -> 8 octas -> OVC.
    expect(bands[1]?.classList.contains('atmo__cloud-band--stratus')).toBe(true);
    expect(bands[1]?.classList.contains('atmo__cloud-band--ovc')).toBe(true);
  });
});

describe('handle positions', () => {
  it('positions the tops handle at its projected altitude, as a literal percentage', () => {
    renderProfile();
    const topsY = altitudeToY(5000, SCALE, 480); // = 240
    const handle = screen.getByRole('button', { name: /Cloud layer 1 tops/ });
    expect(handle.style.top).toBe(`${String((topsY / 480) * 100)}%`);
  });

  it('positions the base handle at its projected altitude, as a literal percentage', () => {
    renderProfile();
    const baseY = altitudeToY(3000, SCALE, 480); // = 336
    const handle = screen.getByRole('button', { name: /Cloud layer 1 base/ });
    expect(handle.style.top).toBe(`${String((baseY / 480) * 100)}%`);
  });

  it('positions a wind handle at its projected altitude', () => {
    renderProfile();
    const y = altitudeToY(6000, SCALE, 480); // = 192
    const handle = screen.getByRole('button', { name: /Wind layer 2/ });
    expect(handle.style.top).toBe(`${String((y / 480) * 100)}%`);
  });
});

describe('terrain and AGL labels', () => {
  it('renders the terrain band and AGL labels when field elevation is known', () => {
    const { container } = renderProfile({ fieldElevationFt: 1000 });
    expect(container.querySelector('.atmo__terrain')).not.toBeNull();
    expect(container.querySelector('.atmo__agl')).not.toBeNull();
  });

  it('renders neither when field elevation is null', () => {
    const { container } = renderProfile({ fieldElevationFt: null });
    expect(container.querySelector('.atmo__terrain')).toBeNull();
    expect(container.querySelector('.atmo__agl')).toBeNull();
  });
});

describe('dragging a cloud tops handle', () => {
  it('emits onCloudLayersChange exactly once, only the dragged layer changed', () => {
    const { onCloudLayersChange, onWindLayersChange } = renderProfile();
    const handle = screen.getByRole('button', { name: /Cloud layer 1 tops/ });

    // topsY(5000ft) = 240px. Moving the pointer up 48px (240 -> 192) raises the altitude by
    // 48 * (10000/480) = 1000ft -> 6000ft, already on a 100ft grid so no further snapping.
    fireEvent.pointerDown(handle, { clientY: 240, pointerId: 1 });
    fireEvent.pointerMove(window, { clientY: 192 });
    fireEvent.pointerUp(window, { clientY: 192 });

    expect(onWindLayersChange).not.toHaveBeenCalled();
    expect(onCloudLayersChange).toHaveBeenCalledTimes(1);
    const emitted = onCloudLayersChange.mock.calls[0]?.[0] as CloudLayer[];
    expect(emitted[0]).toEqual({ ...FIXTURE_STATE.cloud_layers[0], tops_ft: 6000 });
    expect(emitted[1]).toBe(FIXTURE_STATE.cloud_layers[1]);
  });

  it('clamps a drag that would push tops below base + 100ft', () => {
    const { onCloudLayersChange } = renderProfile();
    const handle = screen.getByRole('button', { name: /Cloud layer 1 tops/ });

    // Drag tops (5000ft, y=240) far down: 240 -> 440 is 200px down = -200*(10000/480) ≈ -4167ft
    // -> raw ~833ft, well below base 3000 + 100 -> clamped to 3100.
    fireEvent.pointerDown(handle, { clientY: 240, pointerId: 1 });
    fireEvent.pointerMove(window, { clientY: 440 });
    fireEvent.pointerUp(window, { clientY: 440 });

    expect(onCloudLayersChange).toHaveBeenCalledTimes(1);
    const emitted = onCloudLayersChange.mock.calls[0]?.[0] as CloudLayer[];
    expect(emitted[0]?.tops_ft).toBe(3100);
  });
});

describe('dragging a wind handle', () => {
  it('emits onWindLayersChange exactly once, only altitude changed on that layer', () => {
    const { onWindLayersChange, onCloudLayersChange } = renderProfile();
    const handle = screen.getByRole('button', { name: /Wind layer 2/ });

    // y(6000ft) = 192px. Moving up 48px raises altitude by 1000ft -> 7000ft.
    fireEvent.pointerDown(handle, { clientY: 192, pointerId: 1 });
    fireEvent.pointerMove(window, { clientY: 144 });
    fireEvent.pointerUp(window, { clientY: 144 });

    expect(onCloudLayersChange).not.toHaveBeenCalled();
    expect(onWindLayersChange).toHaveBeenCalledTimes(1);
    const emitted = onWindLayersChange.mock.calls[0]?.[0] as WindLayer[];
    expect(emitted[0]).toBe(FIXTURE_STATE.wind_layers[0]);
    expect(emitted[1]).toEqual({ ...FIXTURE_STATE.wind_layers[1], altitude_ft: 7000 });
  });
});

describe('tap without drag', () => {
  it('selects via the body button with zero change-callback calls', async () => {
    const user = userEvent.setup();
    const { onSelect, onCloudLayersChange, onWindLayersChange } = renderProfile();

    await user.click(screen.getByRole('button', { name: /^Cloud layer 1,/ }));

    expect(onSelect).toHaveBeenCalledWith({ kind: 'cloud', index: 0 });
    expect(onCloudLayersChange).not.toHaveBeenCalled();
    expect(onWindLayersChange).not.toHaveBeenCalled();
  });

  it('a pointerdown+pointerup with no movement on a handle selects but does not commit', () => {
    const { onSelect, onCloudLayersChange } = renderProfile();
    const handle = screen.getByRole('button', { name: /Cloud layer 1 tops/ });

    fireEvent.pointerDown(handle, { clientY: 240, pointerId: 1 });
    fireEvent.pointerUp(window, { clientY: 240 });

    expect(onSelect).toHaveBeenCalledWith({ kind: 'cloud', index: 0 });
    expect(onCloudLayersChange).not.toHaveBeenCalled();
  });
});

describe('selection prop', () => {
  it('marks the selected button aria-pressed and its band selected', () => {
    const selection: AtmosphereSelection = { kind: 'cloud', index: 0 };
    const { container } = renderProfile({ selection });

    const button = screen.getByRole('button', { name: /^Cloud layer 1,/ });
    expect(button.getAttribute('aria-pressed')).toBe('true');
    const bands = container.querySelectorAll('.atmo__cloud-band');
    expect(bands[0]?.classList.contains('atmo__cloud-band--selected')).toBe(true);
    expect(bands[1]?.classList.contains('atmo__cloud-band--selected')).toBe(false);
  });
});

describe('readOnly', () => {
  it('renders no drag handles, but keeps select buttons which still select', async () => {
    const user = userEvent.setup();
    const { container, onSelect } = renderProfile({ readOnly: true });

    expect(container.querySelectorAll('.atmo__handle')).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: /^Cloud layer 1,/ }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'cloud', index: 0 });

    await user.click(screen.getByRole('button', { name: /Wind layer 1/ }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'wind', index: 0 });
  });
});

describe('keyboard', () => {
  it('ArrowUp on a tops handle commits one SNAP_FT step immediately', () => {
    const { onCloudLayersChange } = renderProfile();
    const handle = screen.getByRole('button', { name: /Cloud layer 1 tops/ });

    fireEvent.keyDown(handle, { key: 'ArrowUp' });

    expect(onCloudLayersChange).toHaveBeenCalledTimes(1);
    const emitted = onCloudLayersChange.mock.calls[0]?.[0] as CloudLayer[];
    expect(emitted[0]?.tops_ft).toBe(5100);
  });

  it('ArrowDown on a wind handle commits one SNAP_FT step down', () => {
    const { onWindLayersChange } = renderProfile();
    const handle = screen.getByRole('button', { name: /Wind layer 1/ });

    fireEvent.keyDown(handle, { key: 'ArrowDown' });

    expect(onWindLayersChange).toHaveBeenCalledTimes(1);
    const emitted = onWindLayersChange.mock.calls[0]?.[0] as WindLayer[];
    expect(emitted[0]?.altitude_ft).toBe(1900);
  });
});

describe('wind label text', () => {
  it('renders the gust annotation via the shared formatWind formatter', () => {
    renderProfile();
    const layer = FIXTURE_STATE.wind_layers[1];
    expect(layer).toBeDefined();
    if (layer === undefined) {
      return;
    }
    expect(screen.getByText(formatWind(layer))).toBeInTheDocument();
  });
});
