/**
 * Value formatters for the Position screen. The first four are lifted verbatim from the
 * old `placements.ts` (deleted by the v3 replica) — same behaviour, same test cases, ported
 * rather than re-derived. The rest are new, for values the v3 screen shows that the old
 * panel never did (flight levels, circuit distances, magnetic headings).
 */

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

/** Formats a flight level: `50` -> `"FL050"`, `300` -> `"FL300"`. */
export function formatFlightLevel(hundredsOfFeet: number): string {
  return `FL${String(Math.round(hundredsOfFeet)).padStart(3, '0')}`;
}

/** Formats a circuit/approach distance to one decimal: `3` -> `"3.0 NM"`. */
export function formatDistanceNm(nm: number): string {
  return `${nm.toFixed(1)} NM`;
}

/** Formats a magnetic heading, zero-padded to 3 digits: `40` -> `"040°M"`. */
export function formatHeadingM(deg: number): string {
  const normalised = Math.round(((deg % 360) + 360) % 360);
  return `${String(normalised).padStart(3, '0')}°M`;
}
