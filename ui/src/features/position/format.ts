/**
 * Value formatters for the Position screen. The first four are lifted verbatim from the
 * old `placements.ts` — same behaviour, same test cases, ported rather than re-derived. The
 * rest are new, for values the screen shows that the old panel never did (flight levels,
 * circuit distances, headings, coordinates, surfaces).
 *
 * Formatting only. Nothing here converts a unit that changes a *meaning* — a true heading
 * stays true, and it is labelled true, because the wire says
 * `Placement.heading_deg` is true degrees and there is no magnetic variation on this side
 * of the API to convert it with.
 */

import type { Runway } from '../../api/models';

/** Formats an altitude for a tile: `4184.4` -> `"4,184 ft"`. */
export function formatAltitudeFt(value: number): string {
  return `${Math.round(value).toLocaleString('en-GB')} ft`;
}

/** Formats a speed: `120` -> `"120 kt"`. */
export function formatSpeedKt(value: number): string {
  return `${Math.round(value).toLocaleString('en-GB')} kt`;
}

/** Formats a runway length in metres as both metres and feet, the way charts do. */
export function formatRunwayLength(metres: number): string {
  const feet = Math.round(metres / 0.3048);
  return `${Math.round(metres).toLocaleString('en-GB')} m · ${feet.toLocaleString('en-GB')} ft`;
}

/** Formats an ILS frequency: `110300` kHz -> `"110.30"`. */
export function formatIlsFrequency(khz: number): string {
  return (khz / 1000).toFixed(2);
}

/** Formats a circuit/approach distance to one decimal: `3` -> `"3.0 NM"`. */
export function formatDistanceNm(nm: number): string {
  return `${nm.toFixed(1)} NM`;
}

/** Formats a course or heading in TRUE degrees, zero-padded: `40` -> `"040°T"`. */
export function formatHeadingTrue(deg: number): string {
  return `${formatDegrees(deg)}°T`;
}

/** The bare zero-padded degree figure: `40` -> `"040"`, `-5` -> `"355"`. */
export function formatDegrees(deg: number): string {
  const normalised = Math.round(((deg % 360) + 360) % 360);
  return String(normalised % 360).padStart(3, '0');
}

/** `43° 39' 35.27" N` — degrees, minutes and seconds, as a chart prints them. */
function formatDms(
  value: number,
  positive: string,
  negative: string,
  padWidth: number,
): string {
  const suffix = value >= 0 ? positive : negative;
  const abs = Math.abs(value);
  const degrees = Math.floor(abs);
  const minutesFull = (abs - degrees) * 60;
  const minutes = Math.floor(minutesFull);
  const seconds = (minutesFull - minutes) * 60;
  return `${String(degrees).padStart(padWidth, '0')}° ${String(minutes).padStart(2, '0')}' ${seconds.toFixed(2)}" ${suffix}`;
}

export function formatLatitude(value: number): string {
  return formatDms(value, 'N', 'S', 2);
}

export function formatLongitude(value: number): string {
  return formatDms(value, 'E', 'W', 3);
}

/**
 * The runway surface as navdata publishes it, in words: `"dry_lakebed"` -> `"Dry lakebed"`.
 *
 * `null` is a real answer — apt.dat does not always publish one — and it says so rather
 * than guessing asphalt.
 */
export function formatSurface(surface: Runway['surface']): string {
  if (surface == null || surface === 'unknown') {
    return 'not published';
  }
  const words = surface.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
