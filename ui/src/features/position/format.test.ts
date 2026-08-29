import { describe, expect, it } from 'vitest';
import {
  formatAltitudeFt,
  formatDistanceNm,
  formatDegrees,
  formatHeadingTrue,
  formatIlsFrequency,
  formatLatitude,
  formatLongitude,
  formatRunwayLength,
  formatSpeedKt,
  formatSurface,
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

describe('formatDistanceNm', () => {
  it('keeps one decimal', () => {
    expect(formatDistanceNm(3)).toBe('3.0 NM');
    expect(formatDistanceNm(6.25)).toBe('6.3 NM');
  });
});

describe('formatHeadingTrue', () => {
  it('zero-pads to 3 digits and says the degrees are TRUE', () => {
    expect(formatHeadingTrue(40)).toBe('040°T');
    expect(formatHeadingTrue(5)).toBe('005°T');
  });

  it('normalises out-of-range and negative headings', () => {
    expect(formatHeadingTrue(370)).toBe('010°T');
    expect(formatHeadingTrue(-10)).toBe('350°T');
    expect(formatHeadingTrue(360)).toBe('000°T');
  });
});

describe('formatDegrees', () => {
  it('is the bare figure, without a unit', () => {
    expect(formatDegrees(40)).toBe('040');
    expect(formatDegrees(359.6)).toBe('000');
  });
});

describe('formatLatitude / formatLongitude', () => {
  it('prints degrees, minutes and seconds the way a chart does', () => {
    expect(formatLatitude(43.6584)).toBe('43° 39\' 30.24" N');
    expect(formatLongitude(7.2159)).toBe('007° 12\' 57.24" E');
  });

  it('flips the hemisphere rather than printing a minus', () => {
    expect(formatLatitude(-33.5)).toBe('33° 30\' 0.00" S');
    expect(formatLongitude(-3.5677)).toBe('003° 34\' 3.72" W');
  });
});

describe('formatSurface', () => {
  it('reads the enum back in words', () => {
    expect(formatSurface('asphalt')).toBe('Asphalt');
    expect(formatSurface('dry_lakebed')).toBe('Dry lakebed');
  });

  it('says so when the source publishes nothing, rather than guessing asphalt', () => {
    expect(formatSurface(null)).toBe('not published');
    expect(formatSurface('unknown')).toBe('not published');
  });
});
