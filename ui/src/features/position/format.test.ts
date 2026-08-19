import { describe, expect, it } from 'vitest';
import {
  formatAltitudeFt,
  formatDistanceNm,
  formatFlightLevel,
  formatHeadingM,
  formatIlsFrequency,
  formatRunwayLength,
  formatSpeedKt,
} from './format';

describe('formatAltitudeFt', () => {
  it('rounds to the foot and groups thousands', () => {
    expect(formatAltitudeFt(4184.357192657228)).toBe('4,184 ft');
    expect(formatAltitudeFt(1000)).toBe('1,000 ft');
  });

  it('survives an altitude below sea level', () => {
    expect(formatAltitudeFt(-350.6)).toBe('-351 ft');
  });
});

describe('formatSpeedKt', () => {
  it('rounds to the knot', () => {
    expect(formatSpeedKt(119.6)).toBe('120 kt');
    expect(formatSpeedKt(0)).toBe('0 kt');
  });
});

describe('formatRunwayLength', () => {
  it('converts metres to feet with the exact international foot', () => {
    expect(formatRunwayLength(1852)).toBe('1,852 m · 6,076 ft');
  });

  it('reads a real runway both ways round', () => {
    expect(formatRunwayLength(4100)).toBe('4,100 m · 13,451 ft');
    expect(formatRunwayLength(610)).toBe('610 m · 2,001 ft');
  });
});

describe('formatIlsFrequency', () => {
  it('renders kilohertz as the megahertz an instructor tunes', () => {
    expect(formatIlsFrequency(110300)).toBe('110.30');
    expect(formatIlsFrequency(109100)).toBe('109.10');
  });

  it('keeps the odd 50 kHz channel', () => {
    expect(formatIlsFrequency(111950)).toBe('111.95');
  });
});

describe('formatFlightLevel', () => {
  it('zero-pads below FL100', () => {
    expect(formatFlightLevel(50)).toBe('FL050');
  });

  it('leaves three-digit levels alone', () => {
    expect(formatFlightLevel(300)).toBe('FL300');
    expect(formatFlightLevel(100)).toBe('FL100');
  });
});

describe('formatDistanceNm', () => {
  it('keeps one decimal', () => {
    expect(formatDistanceNm(3)).toBe('3.0 NM');
    expect(formatDistanceNm(6.25)).toBe('6.3 NM');
  });
});

describe('formatHeadingM', () => {
  it('zero-pads to 3 digits', () => {
    expect(formatHeadingM(40)).toBe('040°M');
    expect(formatHeadingM(5)).toBe('005°M');
  });

  it('normalises out-of-range and negative headings', () => {
    expect(formatHeadingM(370)).toBe('010°M');
    expect(formatHeadingM(-10)).toBe('350°M');
  });
});
