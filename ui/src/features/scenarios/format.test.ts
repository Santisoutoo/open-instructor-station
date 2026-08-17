import { describe, expect, it } from 'vitest';
import type { ScenarioRunStatus } from '../../api/models';
import { elapsedSeconds, formatElapsed, formatSeconds, formatStepName, runKey } from './format';

describe('elapsedSeconds', () => {
  it('floors to whole seconds', () => {
    expect(elapsedSeconds(0, 1999)).toBe(1);
  });

  it('clamps a clock running behind the start at zero', () => {
    expect(elapsedSeconds(5000, 3000)).toBe(0);
  });
});

describe('formatSeconds', () => {
  it('zero-pads both fields', () => {
    expect(formatSeconds(0)).toBe('00:00');
    expect(formatSeconds(5)).toBe('00:05');
    expect(formatSeconds(65)).toBe('01:05');
  });

  it('lets minutes grow past the hour rather than wrapping', () => {
    expect(formatSeconds(3600)).toBe('60:00');
  });
});

describe('formatElapsed', () => {
  it('formats the difference between start and now', () => {
    const startedAt = 10_000;
    expect(formatElapsed(startedAt, startedAt)).toBe('00:00');
    expect(formatElapsed(startedAt, startedAt + 61_000)).toBe('01:01');
    expect(formatElapsed(startedAt, startedAt + 600_500)).toBe('10:00');
  });
});

describe('formatStepName', () => {
  it('labels every step the engine can report, in the fixed execution order', () => {
    expect(formatStepName('weather')).toBe('Set weather');
    expect(formatStepName('aircraft_state')).toBe('Configure aircraft');
    expect(formatStepName('position')).toBe('Position aircraft');
    expect(formatStepName('failures')).toBe('Arm failures');
    expect(formatStepName('traffic')).toBe('Spawn traffic');
  });
});

describe('runKey', () => {
  it('combines the scenario id and the server-stamped start time', () => {
    const run = {
      scenario_id: 'wind-shear',
      started_at: '2026-08-17T12:00:00Z',
    } as ScenarioRunStatus;
    expect(runKey(run)).toBe('wind-shear:2026-08-17T12:00:00Z');
  });

  it('tells apart two runs of the same scenario started at different times', () => {
    const first = { scenario_id: 'wind-shear', started_at: 'T1' } as ScenarioRunStatus;
    const second = { scenario_id: 'wind-shear', started_at: 'T2' } as ScenarioRunStatus;
    expect(runKey(first)).not.toBe(runKey(second));
  });
});
