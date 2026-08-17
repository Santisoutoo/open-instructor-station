import { describe, expect, it } from 'vitest';
import { elapsedSeconds, formatElapsed, formatSeconds } from './format';

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
