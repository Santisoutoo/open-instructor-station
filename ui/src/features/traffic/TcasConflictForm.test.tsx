/**
 * Submitting the TCAS form must emit the exact `tcas_conflict` request body — every
 * field explicit, `toEqual` not `toMatchObject`, so no picker can silently default a
 * field (design §8.6). The severity sentences are asserted too: they are the plain
 * language the instructor reads before deciding what to do to the student.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SEVERITY_SENTENCES } from './presets';
import { TcasConflictForm } from './TcasConflictForm';

function renderForm(disabled = false) {
  const onSpawn = vi.fn();
  render(<TcasConflictForm disabled={disabled} onSpawn={onSpawn} />);
  return { onSpawn };
}

describe('TcasConflictForm', () => {
  it('spawns a head-on RA with every default stated explicitly', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.click(screen.getByRole('button', { name: /spawn tcas conflict/i }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    expect(onSpawn).toHaveBeenCalledWith({
      type: 'tcas_conflict',
      severity: 'head_on_ra',
      relative_bearing_deg: 180,
      miss_side: 'left',
      vertical_offset: 'above',
      closure_ias_kt: null,
      kind: 'aircraft',
      callsign: 'TFC01',
    });
  });

  it('sends exactly what the instructor picked', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.click(screen.getByRole('button', { name: 'TA only' }));
    const bearing = screen.getByLabelText(/relative bearing/i);
    await user.clear(bearing);
    await user.type(bearing, '90');
    await user.click(screen.getByRole('button', { name: 'right' }));
    await user.click(screen.getByRole('button', { name: 'below' }));
    await user.type(screen.getByLabelText(/closure ias/i), '210');
    const callsign = screen.getByLabelText(/callsign/i);
    await user.clear(callsign);
    await user.type(callsign, 'ACA123');
    await user.click(screen.getByRole('button', { name: 'ground vehicle' }));
    await user.click(screen.getByRole('button', { name: /spawn tcas conflict/i }));

    expect(onSpawn).toHaveBeenCalledWith({
      type: 'tcas_conflict',
      severity: 'ta_only',
      relative_bearing_deg: 90,
      miss_side: 'right',
      vertical_offset: 'below',
      closure_ias_kt: 210,
      kind: 'ground_vehicle',
      callsign: 'ACA123',
    });
  });

  it('shows the plain-language sentence for the selected severity', async () => {
    const user = userEvent.setup();
    renderForm();

    // The default preset's sentence is on screen before any interaction.
    expect(screen.getByText(SEVERITY_SENTENCES.head_on_ra)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'TA only' }));
    expect(screen.getByText(SEVERITY_SENTENCES.ta_only)).toBeInTheDocument();
    expect(screen.queryByText(SEVERITY_SENTENCES.head_on_ra)).toBeNull();
  });

  it('every severity sentence states its timing in seconds', () => {
    // The sentences restate TCAS_SEVERITY_PROFILES: 100 s to CPA for both RAs, 90 s
    // for the TA — a pin on the table in core/traffic.py, not a re-derivation.
    expect(SEVERITY_SENTENCES.head_on_ra).toContain('100 s');
    expect(SEVERITY_SENTENCES.crossing_ra).toContain('100 s');
    expect(SEVERITY_SENTENCES.ta_only).toContain('90 s');
    expect(SEVERITY_SENTENCES.ta_only).toContain('500 ft');
  });

  it('will not spawn with an out-of-range bearing', async () => {
    const user = userEvent.setup();
    renderForm();

    const bearing = screen.getByLabelText(/relative bearing/i);
    await user.clear(bearing);
    await user.type(bearing, '360');

    expect(screen.getByRole('button', { name: /spawn tcas conflict/i })).toBeDisabled();
  });

  it('disables the spawn button while the gate is closed', () => {
    renderForm(true);

    expect(screen.getByRole('button', { name: /spawn tcas conflict/i })).toBeDisabled();
  });
});
