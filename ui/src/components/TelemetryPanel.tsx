import {
  formatAltitude,
  formatAttitude,
  formatHeading,
  formatLatitude,
  formatLongitude,
  formatOnGround,
  formatSpeed,
  formatVerticalSpeed,
} from '../features/telemetry/format';
import { useAppSelector } from '../store';

interface Readout {
  label: string;
  value: string;
}

/** Live aircraft state, fed by the `/ws/state` WebSocket at ~4 Hz. */
export function TelemetryPanel() {
  const latest = useAppSelector((state) => state.telemetry.latest);

  if (latest === null) {
    return (
      <section className="panel" aria-labelledby="telemetry-heading">
        <h2 id="telemetry-heading">Telemetry</h2>
        <p className="panel__empty">Waiting for the first frame…</p>
      </section>
    );
  }

  const readouts: Readout[] = [
    { label: 'Latitude', value: formatLatitude(latest.latitude) },
    { label: 'Longitude', value: formatLongitude(latest.longitude) },
    { label: 'Altitude', value: formatAltitude(latest.altitude_ft) },
    { label: 'Heading', value: formatHeading(latest.heading_deg) },
    { label: 'IAS', value: formatSpeed(latest.ias_kt) },
    { label: 'Vertical speed', value: formatVerticalSpeed(latest.vertical_speed_fpm) },
    { label: 'Pitch', value: formatAttitude(latest.pitch_deg) },
    { label: 'Roll', value: formatAttitude(latest.roll_deg) },
    { label: 'Status', value: formatOnGround(latest.on_ground) },
  ];

  return (
    <section className="panel" aria-labelledby="telemetry-heading">
      <h2 id="telemetry-heading">Telemetry</h2>
      <dl className="readouts">
        {readouts.map((readout) => (
          <div className="readout" key={readout.label}>
            <dt className="readout__label">{readout.label}</dt>
            <dd className="readout__value">{readout.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
