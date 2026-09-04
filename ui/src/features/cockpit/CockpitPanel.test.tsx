/**
 * The integration layer of the Cockpit tab (issue #253): gate → catalog → the Schematic /
 * List decision → one write per commit. `fetch` is stubbed, not the hooks, so what is
 * asserted is the actual request the panel sends — the draft + explicit-confirm rule
 * ("never write on a wheel notch") is only provable at this level, where the wheel, the
 * shared draft and the mutation meet.
 */

import { createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Capabilities, CockpitCatalogManifest } from '../../api/models';
import { setupStore } from '../../store';
import { CockpitPanel } from './CockpitPanel';
import { cockpitCatalogManifestFixture, cockpitStateSnapshotFixture } from './fixtures';
import { callsTo, stubApi, type Answer } from './testApi';

function capabilities(): Capabilities {
  return {
    can_set_position: true,
    can_set_aircraft_state: true,
    can_set_weather: true,
    can_inject_failures: false,
    can_spawn_traffic: false,
    can_control_autopilot: true,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    can_control_cockpit: true,
  };
}

/**
 * The Fake's fixture catalog re-badged as the Zibo: every fixture control id is also a
 * Zibo `mcp` id, so the Zibo layout draws them and the state snapshot fits unchanged.
 */
function ziboManifest(catalogId = 'zibo-b738'): CockpitCatalogManifest {
  const base = cockpitCatalogManifestFixture();
  return {
    ...base,
    adapter: 'xplane',
    aircraft: {
      catalog_id: catalogId,
      label: 'Zibo Mod B737-800X',
      path_hints: ['B737-800X'],
    },
  };
}

function actuated(controlId: string, value: boolean | number): Answer {
  return {
    body: {
      requested: { control_id: controlId, value },
      state: { control_id: controlId, value },
      actions_taken: 1,
      catalog_id: 'zibo-b738',
      revision: 1,
    },
  };
}

function renderPanel(overrides: Record<string, Answer | readonly Answer[]> = {}) {
  const { calls } = stubApi({
    'GET capabilities': { body: capabilities() },
    'GET cockpit/catalog': { body: ziboManifest() },
    'GET cockpit/state': { body: cockpitStateSnapshotFixture() },
    ...overrides,
  });
  const store = setupStore();
  render(
    <Provider store={store}>
      <CockpitPanel />
    </Provider>,
  );
  return { calls, store };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CockpitPanel — schematic integration', () => {
  it('draws the schematic by default for an aircraft with a layout', async () => {
    renderPanel();

    const hit = await screen.findByRole('button', { name: 'Altitude' });
    expect(hit).toHaveClass('schematic__hit');
    expect(screen.getByRole('radio', { name: 'Schematic' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByText('Tap a control on the diagram')).toBeInTheDocument();
  });

  it('falls back to the list, with the toggle disabled and a reason, for an unknown catalog', async () => {
    renderPanel({ 'GET cockpit/catalog': { body: ziboManifest('mystery-jet') } });

    const schematicOption = await screen.findByRole('radio', { name: 'Schematic' });
    expect(schematicOption).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'List' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByText('No schematic for Zibo Mod B737-800X')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Altitude' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Altitude target/)).toBeInTheDocument();
  });

  it('renders the list while a search is active, whatever the view mode', async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole('button', { name: 'Altitude' });

    await user.type(screen.getByRole('searchbox'), 'alt');

    expect(
      screen.queryByRole('radiogroup', { name: 'Cockpit view' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Altitude' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Altitude target/)).toBeInTheDocument();
  });

  it('switches to the list and back through the toggle', async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByRole('button', { name: 'Altitude' });

    await user.click(screen.getByRole('radio', { name: 'List' }));
    expect(screen.queryByRole('button', { name: 'Altitude' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Altitude target/)).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Schematic' }));
    expect(screen.getByRole('button', { name: 'Altitude' })).toBeInTheDocument();
  });

  it('wheel notches edit the shared draft without writing; Enter sends exactly one POST', async () => {
    const { calls } = renderPanel({
      'POST cockpit/actuate': actuated('mcp_alt', 5200),
    });
    const hit = await screen.findByRole('button', { name: 'Altitude' });
    await screen.findByText('5,000 ft');

    fireEvent(hit, createEvent.wheel(hit, { deltaY: -100 }));

    // The slot's draft line and the tray's field both show the same shared draft.
    expect(screen.getByLabelText(/Altitude target/)).toHaveValue(5200);
    expect(callsTo(calls, 'POST', 'cockpit/actuate')).toHaveLength(0);

    fireEvent.keyDown(hit, { key: 'Enter' });

    await waitFor(() => {
      expect(callsTo(calls, 'POST', 'cockpit/actuate')).toHaveLength(1);
    });
    expect(callsTo(calls, 'POST', 'cockpit/actuate')[0]?.body).toEqual({
      control_id: 'mcp_alt',
      value: 5200,
    });
    // The slot readout and the tray's own readout both show the confirmed read-back.
    expect(await screen.findAllByText('5,200 ft')).not.toHaveLength(0);
    expect(screen.getByLabelText(/Altitude target/)).toHaveValue(null);
  });

  it('a tap on a toggle slot writes once with the flipped value', async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel({
      'POST cockpit/actuate': actuated('fd_capt', true),
    });
    const hit = await screen.findByRole('button', { name: 'Flight director (captain)' });
    await screen.findByText('5,000 ft');

    await user.click(hit);

    await waitFor(() => {
      expect(callsTo(calls, 'POST', 'cockpit/actuate')).toHaveLength(1);
    });
    expect(callsTo(calls, 'POST', 'cockpit/actuate')[0]?.body).toEqual({
      control_id: 'fd_capt',
      value: true,
    });
  });

  it('focusing a parked slot shows its reason in the tray and never writes', async () => {
    const user = userEvent.setup();
    const { calls } = renderPanel();
    const hit = await screen.findByRole('button', { name: 'V/S' });
    expect(hit).toHaveAttribute('aria-disabled', 'true');

    await user.click(hit);

    expect(
      screen.getAllByText(/No settable vertical-speed dataref/).length,
    ).toBeGreaterThan(0);
    expect(callsTo(calls, 'POST', 'cockpit/actuate')).toHaveLength(0);
  });

  it('a rejected write keeps the draft for a retry and shows the server detail', async () => {
    const { calls } = renderPanel({
      'POST cockpit/actuate': { status: 409, detail: 'HDG SEL needs a flight director.' },
    });
    const hit = await screen.findByRole('button', { name: 'Altitude' });
    await screen.findByText('5,000 ft');

    fireEvent(hit, createEvent.wheel(hit, { deltaY: -100 }));
    fireEvent.keyDown(hit, { key: 'Enter' });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'HDG SEL needs a flight director.',
    );
    expect(callsTo(calls, 'POST', 'cockpit/actuate')).toHaveLength(1);
    expect(screen.getByLabelText(/Altitude target/)).toHaveValue(5200);
  });

  it('switching panel abandons the draft instead of leaving it on the slot', async () => {
    const user = userEvent.setup();
    renderPanel();
    const hit = await screen.findByRole('button', { name: 'Altitude' });
    await screen.findByText('5,000 ft');

    fireEvent(hit, createEvent.wheel(hit, { deltaY: -100 }));
    expect(screen.getByLabelText(/Altitude target/)).toHaveValue(5200);

    await user.click(screen.getByRole('tab', { name: 'Overhead' }));
    await user.click(screen.getByRole('tab', { name: 'MCP / autopilot' }));

    expect(await screen.findByRole('button', { name: 'Altitude' })).toBeInTheDocument();
    expect(screen.getByText('Tap a control on the diagram')).toBeInTheDocument();
    expect(screen.queryByText(/5,200 ft/)).not.toBeInTheDocument();
  });

  it('a tap on the already-checked view option does not clear the focus', async () => {
    const user = userEvent.setup();
    renderPanel();
    const hit = await screen.findByRole('button', { name: 'Altitude' });
    await user.click(hit);
    expect(screen.getByLabelText(/Altitude target/)).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Schematic' }));

    expect(screen.getByLabelText(/Altitude target/)).toBeInTheDocument();
  });
});
