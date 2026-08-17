/**
 * Spherical geodesy for the map: haversine distance, initial bearing, destination
 * point, and the measure-tool readout format.
 *
 * Pure functions on a spherical Earth. The measure tool is an instructor's eyeball
 * check ("how far out is he?"), not navigation: at map scales the spherical error
 * (< 0.5%) is far below what a glance at the readout can resolve. Anything that must
 * be exact goes through the server's geodesy, never through this file.
 */

export interface LatLon {
  lat: number;
  lon: number;
}

/** Mean Earth radius in nautical miles. */
export const EARTH_RADIUS_NM = 3440.065;

const DEG = Math.PI / 180;

/** Great-circle distance in nautical miles (haversine). */
export function distanceNm(a: LatLon, b: LatLon): number {
  const dLat = (b.lat - a.lat) * DEG;
  const dLon = (b.lon - a.lon) * DEG;
  const sinLat = Math.sin(dLat / 2);
  const sinLon = Math.sin(dLon / 2);
  const h =
    sinLat * sinLat + Math.cos(a.lat * DEG) * Math.cos(b.lat * DEG) * sinLon * sinLon;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial great-circle bearing from `a` to `b`, degrees true, normalised to [0, 360). */
export function initialBearingDeg(a: LatLon, b: LatLon): number {
  const dLon = (b.lon - a.lon) * DEG;
  const latA = a.lat * DEG;
  const latB = b.lat * DEG;
  const y = Math.sin(dLon) * Math.cos(latB);
  const x =
    Math.cos(latA) * Math.sin(latB) - Math.sin(latA) * Math.cos(latB) * Math.cos(dLon);
  const bearing = Math.atan2(y, x) / DEG;
  return ((bearing % 360) + 360) % 360;
}

/** The point `distance` NM from `origin` on the given initial bearing. */
export function destinationPoint(
  origin: LatLon,
  bearingDeg: number,
  distance: number,
): LatLon {
  const delta = distance / EARTH_RADIUS_NM;
  const theta = bearingDeg * DEG;
  const lat1 = origin.lat * DEG;
  const lon1 = origin.lon * DEG;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(delta) + Math.cos(lat1) * Math.sin(delta) * Math.cos(theta),
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(theta) * Math.sin(delta) * Math.cos(lat1),
      Math.cos(delta) - Math.sin(lat1) * Math.sin(lat2),
    );
  return {
    lat: lat2 / DEG,
    lon: ((lon2 / DEG + 540) % 360) - 180,
  };
}

/**
 * The measure chip's readout: `12.4 NM · 227°`. Bearing is zero-padded aviation
 * style, matching the telemetry heading format.
 */
export function formatMeasure(distance: number, bearingDeg: number): string {
  const normalised = ((Math.round(bearingDeg) % 360) + 360) % 360;
  return `${distance.toFixed(1)} NM · ${String(normalised).padStart(3, '0')}°`;
}
