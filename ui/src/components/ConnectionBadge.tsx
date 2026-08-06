import { useGetHealthQuery } from '../api/instructorApi';
import { useAppSelector } from '../store';
import type { ConnectionStatus } from '../store/connectionSlice';

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  idle: 'Offline',
  connecting: 'Connecting',
  connected: 'Connected',
  error: 'Disconnected',
};

/**
 * Live link indicator: green connected / amber connecting / red error, annotated with the
 * adapter name reported by `GET /api/health` so the instructor can tell at a glance whether
 * they are driving the real simulator or the fake adapter.
 */
export function ConnectionBadge() {
  const status = useAppSelector((state) => state.connection.status);
  const lastError = useAppSelector((state) => state.connection.lastError);
  const lastUpdateAt = useAppSelector((state) => state.connection.lastUpdateAt);
  const { data: health } = useGetHealthQuery(undefined, { pollingInterval: 10_000 });

  const adapter = health?.adapter ?? 'unknown';
  const detail =
    status === 'connected'
      ? `adapter: ${adapter}`
      : (lastError ?? 'waiting for the instructor server');

  return (
    <div
      className={`badge badge--${status}`}
      role="status"
      aria-live="polite"
      title={
        lastUpdateAt === null
          ? detail
          : `${detail} — last frame ${new Date(lastUpdateAt).toLocaleTimeString('en-GB')}`
      }
    >
      <span className="badge__dot" aria-hidden="true" />
      <span className="badge__label">{STATUS_LABEL[status]}</span>
      <span className="badge__detail">{detail}</span>
    </div>
  );
}
