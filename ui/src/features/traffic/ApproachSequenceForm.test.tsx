/**
 * Submitting the approach-sequence form must emit the exact `approach_sequence`
 * request body (design §8.6). The distances list is the interesting control: it
 * defaults to core's `APPROACH_SEQUENCE_DEFAULT_DISTANCES_NM` (12, 8, 4), rows are
 * removable down to one and addable up to the request model's cap of eight.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApproachSequenceForm } from './ApproachSequenceForm';
import { DEFAULT_DISTANCES_NM, MAX_DISTANCES } from './presets';

function renderForm(disabled = false) {
  const onSpawn = vi.fn();
  render(<ApproachSequenceForm disabled={disabled} onSpawn={onSpawn} />);
  return { onSpawn };
}

describe('ApproachSequenceForm', () => {
  it('will not spawn without both an airport and a runway', async () => {
    const user = userEvent.setup();
    renderForm();
    const submit = screen.getByRole('button', { name: /spawn approach sequence/i });

    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/airport icao/i), 'LEMD');
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/^runway$/i), '32L');
    expect(submit).toBeEnabled();
  });

  it('defaults the distances to 12, 8, 4 NM — the core default, restated', () => {
    renderForm();

    expect(DEFAULT_DISTANCES_NM).toEqual([12, 8, 4]);
    expect(screen.getByLabelText(/^distance 1/i)).toHaveValue(12);
    expect(screen.getByLabelText(/^distance 2/i)).toHaveValue(8);
    expect(screen.getByLabelText(/^distance 3/i)).toHaveValue(4);
  });

  it('spawns the default three-ship sequence with every field explicit', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.type(screen.getByLabelText(/airport icao/i), 'lemd');
    await user.type(screen.getByLabelText(/^runway$/i), '32l');
    await user.click(screen.getByRole('button', { name: /spawn approach sequence/i }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    expect(onSpawn).toHaveBeenCalledWith({
      type: 'approach_sequence',
      airport_icao: 'LEMD',
      runway_ident: '32L',
      distances_nm: [12, 8, 4],
      ias_kt: null,
      category: 'B',
      kind: 'aircraft',
      callsign_prefix: 'SEQ',
    });
  });

  it('sends an edited distance list exactly as edited', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.type(screen.getByLabelText(/airport icao/i), 'LEMD');
    await user.type(screen.getByLabelText(/^runway$/i), '32L');
    await user.click(screen.getByRole('button', { name: /remove distance 3/i }));
    const second = screen.getByLabelText(/^distance 2/i);
    await user.clear(second);
    await user.type(second, '6');
    await user.type(screen.getByLabelText(/ias kt/i), '140');
    await user.click(screen.getByRole('button', { name: 'C' }));
    await user.click(screen.getByRole('button', { name: /spawn approach sequence/i }));

    expect(onSpawn).toHaveBeenCalledWith({
      type: 'approach_sequence',
      airport_icao: 'LEMD',
      runway_ident: '32L',
      distances_nm: [12, 6],
      ias_kt: 140,
      category: 'C',
      kind: 'aircraft',
      callsign_prefix: 'SEQ',
    });
  });

  it('will not spawn while a distance row is blank', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/airport icao/i), 'LEMD');
    await user.type(screen.getByLabelText(/^runway$/i), '32L');
    await user.click(screen.getByRole('button', { name: /add aircraft/i }));

    expect(
      screen.getByRole('button', { name: /spawn approach sequence/i }),
    ).toBeDisabled();
  });

  it('caps the list at the request model’s eight aircraft', async () => {
    const user = userEvent.setup();
    renderForm();
    const add = screen.getByRole('button', { name: /add aircraft/i });

    for (let i = DEFAULT_DISTANCES_NM.length; i < MAX_DISTANCES; i += 1) {
      await user.click(add);
    }

    expect(MAX_DISTANCES).toBe(8);
    expect(add).toBeDisabled();
  });

  it('keeps the last distance row — a sequence of zero aircraft is not a sequence', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.click(screen.getByRole('button', { name: /remove distance 3/i }));
    await user.click(screen.getByRole('button', { name: /remove distance 2/i }));

    expect(screen.getByRole('button', { name: /remove distance 1/i })).toBeDisabled();
  });

  it('disables the spawn button while the gate is closed', () => {
    renderForm(true);

    expect(
      screen.getByRole('button', { name: /spawn approach sequence/i }),
    ).toBeDisabled();
  });
});
