/**
 * One row per saved profile: name, description, author, airport teaser, updated date.
 * Per row — Apply (fires `/apply`, D8: no staging bar, the profile *is* the staged
 * thing), Export (a native `<a href download>`, never a `fetch`), Delete (behind
 * `window.confirm()`, D12 — the only confirmation dialog in this manager).
 *
 * Tablet-first: rows are 44px+ touch targets, Apply is the largest button on each row —
 * the single most common action in this panel (design §7.3).
 */

import { useState } from 'react';
import type { ProfileApplyResult, ProfileSummary } from '../../api/models';
import { ApplyResultBanner } from './ApplyResultBanner';
import { useApplyProfileMutation, useDeleteProfileMutation } from './profilesApi';

function formatUpdated(iso: string): string {
  return new Date(iso).toLocaleString();
}

interface ProfileRowProps {
  profile: ProfileSummary;
}

function ProfileRow({ profile }: ProfileRowProps) {
  const [applyProfile, applyState] = useApplyProfileMutation();
  const [deleteProfile, deleteState] = useDeleteProfileMutation();
  const [lastResult, setLastResult] = useState<ProfileApplyResult | null>(null);

  const handleApply = () => {
    void applyProfile(profile.profile_id)
      .unwrap()
      .then((result) => {
        setLastResult(result);
      })
      .catch(() => {
        // Rendered from applyState.isError below; nothing to do here.
      });
  };

  const handleDelete = () => {
    if (!window.confirm(`Delete the profile "${profile.name}"?`)) {
      return;
    }
    void deleteProfile(profile.profile_id);
  };

  return (
    <li className="profile-row">
      <div className="profile-row__summary">
        <span className="profile-row__name">{profile.name}</span>
        {profile.airport_icao !== null && profile.airport_icao !== undefined && (
          <span className="profile-row__airport">{profile.airport_icao}</span>
        )}
        {profile.description !== '' && (
          <span className="profile-row__description">{profile.description}</span>
        )}
        <span className="profile-row__meta">
          {profile.author !== null ? `${profile.author} — ` : ''}
          updated {formatUpdated(profile.updated_at)}
        </span>
      </div>

      <div className="profile-row__actions">
        <button
          type="button"
          className="profile-row__apply"
          disabled={applyState.isLoading}
          onClick={handleApply}
        >
          Apply
        </button>
        <a
          className="profile-row__export"
          href={`/api/profiles/${profile.profile_id}/export`}
          download={`${profile.name}.json`}
        >
          Export
        </a>
        <button
          type="button"
          className="profile-row__delete"
          disabled={deleteState.isLoading}
          onClick={handleDelete}
        >
          Delete
        </button>
      </div>

      {applyState.isError && <p className="panel__error">The profile could not be applied.</p>}
      {lastResult !== null && <ApplyResultBanner result={lastResult} />}
    </li>
  );
}

interface ProfileListProps {
  profiles: ProfileSummary[];
}

export function ProfileList({ profiles }: ProfileListProps) {
  if (profiles.length === 0) {
    return <p className="panel__empty">No saved profiles yet.</p>;
  }
  return (
    <ul className="profile-list">
      {profiles.map((profile) => (
        <ProfileRow key={profile.profile_id} profile={profile} />
      ))}
    </ul>
  );
}
