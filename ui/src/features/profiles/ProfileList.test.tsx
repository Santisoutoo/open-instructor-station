/**
 * `ProfileList` against a stubbed API: Apply issues exactly one `POST .../apply`, Delete
 * calls `window.confirm` before issuing the `DELETE` (and issues nothing when declined),
 * Export renders a plain `<a href>` to the exact export URL — never a `fetch`.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ProfileApplyResult, ProfileSummary } from '../../api/models';
import { setupStore } from '../../store';
import { ProfileList } from './ProfileList';
import { callsTo, stubApi } from './testApi';

const PROFILE: ProfileSummary = {
  profile_id: 'a'.repeat(32),
  name: 'Circuit practice',
  description: 'A test profile.',
  author: 'Instructor',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  airport_icao: 'LEMD',
};

const APPLY_RESULT: ProfileApplyResult = {
  profile_id: PROFILE.profile_id,
  position: { attempted: true, applied: true, result: null, reason: null },
  weather: { attempted: false, applied: true, result: null, reason: null },
  failures: [],
  degraded: false,
  notes: [],
};

function renderList(profiles: ProfileSummary[] = [PROFILE]) {
  const store = setupStore();
  render(
    <Provider store={store}>
      <ProfileList profiles={profiles} />
    </Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ProfileList', () => {
  it('issues exactly one POST .../apply when Apply is pressed', async () => {
    const { calls } = stubApi({
      [`profiles/${PROFILE.profile_id}/apply`]: { body: APPLY_RESULT },
    });
    renderList();

    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => {
      expect(callsTo(calls, '/apply')).toHaveLength(1);
    });
    const call = callsTo(calls, '/apply')[0];
    expect(call).toBeDefined();
    expect({ method: call?.method, body: call?.body }).toEqual({
      method: 'POST',
      body: undefined,
    });
    expect(call?.url).toContain(`profiles/${PROFILE.profile_id}/apply`);
  });

  it('renders the apply result banner after a successful apply', async () => {
    stubApi({ [`profiles/${PROFILE.profile_id}/apply`]: { body: APPLY_RESULT } });
    renderList();

    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(await screen.findByText(/Position: applied/)).toBeInTheDocument();
  });

  it('calls window.confirm before deleting, and issues nothing when declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { calls } = stubApi({});
    renderList();

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(
      callsTo(calls, `profiles/${PROFILE.profile_id}`).filter((call) => call.method === 'DELETE'),
    ).toHaveLength(0);
  });

  it('issues a DELETE once the confirmation is accepted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { calls } = stubApi({ [`profiles/${PROFILE.profile_id}`]: { body: null } });
    renderList();

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(
        callsTo(calls, `profiles/${PROFILE.profile_id}`).some((call) => call.method === 'DELETE'),
      ).toBe(true);
    });
  });

  it('renders Export as a native download link, never a fetch', () => {
    const { calls } = stubApi({});
    renderList();

    const link = screen.getByRole('link', { name: 'Export' });
    expect(link).toHaveAttribute('href', `/api/profiles/${PROFILE.profile_id}/export`);
    expect(link).toHaveAttribute('download');
    expect(calls).toHaveLength(0);
  });

  it('renders a message when there are no saved profiles', () => {
    stubApi({});
    renderList([]);
    expect(screen.getByText('No saved profiles yet.')).toBeInTheDocument();
  });
});
