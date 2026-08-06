/**
 * Display formatting for telemetry values.
 *
 * Locale is pinned to `en-US` on purpose: the readout must look identical on the
 * instructor's tablet, on the desktop and in CI, regardless of system locale.
 */

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const SIGNED_INTEGER = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 0,
  signDisplay: 'exceptZero',
});

/** Latitude, 5 decimals, with hemisphere: `47.44712° N`. */
export function formatLatitude(value: number): string {
  return `${Math.abs(value).toFixed(5)}° ${value < 0 ? 'S' : 'N'}`;
}

/** Longitude, 5 decimals, with hemisphere: `122.30931° W`. */
export function formatLongitude(value: number): string {
  return `${Math.abs(value).toFixed(5)}° ${value < 0 ? 'W' : 'E'}`;
}

/** Altitude as whole feet: `12,500 ft`. */
export function formatAltitude(feet: number): string {
  return `${INTEGER.format(Math.round(feet))} ft`;
}

/** Indicated airspeed as whole knots: `243 kt`. */
export function formatSpeed(knots: number): string {
  return `${INTEGER.format(Math.round(knots))} kt`;
}

/** Vertical speed, always signed: `+1,800 fpm`, `-450 fpm`, `0 fpm`. */
export function formatVerticalSpeed(fpm: number): string {
  return `${SIGNED_INTEGER.format(Math.round(fpm))} fpm`;
}

/** Heading normalised to 0–359 and zero-padded, aviation style: `047°`. */
export function formatHeading(degrees: number): string {
  const normalised = ((Math.round(degrees) % 360) + 360) % 360;
  return `${String(normalised).padStart(3, '0')}°`;
}

/** Pitch and roll, one decimal, always signed: `-2.5°`. */
export function formatAttitude(degrees: number): string {
  const rounded = Math.abs(degrees) < 0.05 ? 0 : degrees;
  const sign = rounded > 0 ? '+' : '';
  return `${sign}${rounded.toFixed(1)}°`;
}

export function formatOnGround(onGround: boolean): string {
  return onGround ? 'On ground' : 'Airborne';
}
