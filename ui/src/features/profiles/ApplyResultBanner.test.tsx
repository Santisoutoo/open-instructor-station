/**
 * `ApplyResultBanner` — a pure render of one `ProfileApplyResult`: each component's reason
 * when `applied` is false, green (the `--ok` tone) when `degraded` is false.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ProfileApplyResult } from '../../api/models';
import { ApplyResultBanner } from './ApplyResultBanner';

const HAPPY: ProfileApplyResult = {
  profile_id: 'a'.repeat(32),
  position: { attempted: true, applied: true, result: null, reason: null },
  weather: { attempted: true, applied: true, result: null, reason: null },
  failures: [{ ref: { failure_id: 'airframe.smoke', engine_index: null }, applied: true, armed: false, armed_id: null, reason: null }],
  degraded: false,
  notes: [],
};

const DEGRADED: ProfileApplyResult = {
  profile_id: 'b'.repeat(32),
  position: {
    attempted: true,
    applied: false,
    result: null,
    reason: "Runway 09 is not published at ZZZQ.",
  },
  weather: { attempted: true, applied: true, result: null, reason: null },
  failures: [
    {
      ref: { failure_id: 'airframe.smoke', engine_index: null },
      applied: false,
      armed: false,
      armed_id: null,
      reason: "Unavailable on this adapter — does not declare can_inject_failures.",
    },
  ],
  degraded: true,
  notes: [],
};

describe('ApplyResultBanner', () => {
  it('renders every attempted component as applied, with the ok tone, when not degraded', () => {
    render(<ApplyResultBanner result={HAPPY} />);

    expect(screen.getByText(/Position: applied/)).toHaveClass('profiles-banner__line--ok');
    expect(screen.getByText(/Weather: applied/)).toHaveClass('profiles-banner__line--ok');
    expect(screen.getByText(/airframe\.smoke: injected/)).toHaveClass('profiles-banner__line--ok');
    expect(screen.getByRole('status')).toHaveClass('profiles-banner--ok');
  });

  it('renders each failing component reason, with the warn tone, when degraded', () => {
    render(<ApplyResultBanner result={DEGRADED} />);

    expect(screen.getByText(/Position: Runway 09 is not published at ZZZQ\./)).toHaveClass(
      'profiles-banner__line--warn',
    );
    expect(
      screen.getByText(/airframe\.smoke: Unavailable on this adapter/),
    ).toHaveClass('profiles-banner__line--warn');
    expect(screen.getByRole('status')).toHaveClass('profiles-banner--degraded');
  });

  it('omits a line for a component the profile never attempted', () => {
    render(
      <ApplyResultBanner
        result={{
          ...HAPPY,
          weather: { attempted: false, applied: true, result: null, reason: null },
        }}
      />,
    );

    expect(screen.queryByText(/Weather:/)).not.toBeInTheDocument();
  });
});
