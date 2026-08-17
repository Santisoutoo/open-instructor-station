/**
 * Renders one `ProfileApplyResult`: a line per attempted component (green when applied,
 * amber with its reason when not), with the banner's overall tone following `degraded`.
 * Never a modal (design §7.3) — it renders inline, under the row that triggered it.
 */

import type {
  ProfileApplyResult,
  ProfileFailureOutcome,
  ProfilePositionOutcome,
  ProfileWeatherOutcome,
} from '../../api/models';

interface ApplyResultBannerProps {
  result: ProfileApplyResult;
}

function toneClass(applied: boolean): string {
  return applied ? 'profiles-banner__line--ok' : 'profiles-banner__line--warn';
}

function PositionLine({ outcome }: { outcome: ProfilePositionOutcome }) {
  if (!outcome.attempted) {
    return null;
  }
  return (
    <li className={toneClass(outcome.applied)}>
      Position: {outcome.applied ? 'applied' : (outcome.reason ?? 'not applied')}
    </li>
  );
}

function WeatherLine({ outcome }: { outcome: ProfileWeatherOutcome }) {
  if (!outcome.attempted) {
    return null;
  }
  return (
    <li className={toneClass(outcome.applied)}>
      Weather: {outcome.applied ? 'applied' : (outcome.reason ?? 'not applied')}
    </li>
  );
}

function FailureLine({ outcome }: { outcome: ProfileFailureOutcome }) {
  const label = outcome.ref.failure_id;
  const detail = outcome.applied
    ? outcome.armed
      ? 'armed'
      : 'injected'
    : (outcome.reason ?? 'not applied');
  return (
    <li className={toneClass(outcome.applied)}>
      {label}: {detail}
    </li>
  );
}

export function ApplyResultBanner({ result }: ApplyResultBannerProps) {
  return (
    <div
      className={
        result.degraded ? 'profiles-banner profiles-banner--degraded' : 'profiles-banner profiles-banner--ok'
      }
      role="status"
    >
      <ul className="profiles-banner__lines">
        <PositionLine outcome={result.position} />
        <WeatherLine outcome={result.weather} />
        {result.failures.map((outcome, index) => (
          <FailureLine key={`${outcome.ref.failure_id}-${index}`} outcome={outcome} />
        ))}
      </ul>
    </div>
  );
}
