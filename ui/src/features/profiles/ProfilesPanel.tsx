/**
 * The Profiles tab: the Save form collapsed at the top, the list below, an Import button.
 *
 * No capability gate at the tab level (D3 — nothing here needs one): the CRUD/import/
 * export endpoints never touch the simulator, and per-component refusal on Apply is
 * rendered entirely from `ProfileApplyResult.reason` after the attempt (design §7.4).
 */

import { useRef, useState } from 'react';
import { ProfileList } from './ProfileList';
import { useGetProfilesQuery, useImportProfileMutation } from './profilesApi';
import { SaveProfileForm } from './SaveProfileForm';
import './profiles.css';

export function ProfilesPanel() {
  const { data: profiles, isLoading, isError } = useGetProfilesQuery();
  const [importProfile, importState] = useImportProfileMutation();
  const [formOpen, setFormOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChosen = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file === undefined) {
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    void importProfile(formData).unwrap().catch(() => {
      // Rendered from importState.isError below; nothing to do here.
    });
  };

  return (
    <section className="panel profiles-panel" aria-labelledby="profiles-heading">
      <h2 id="profiles-heading">Profiles</h2>

      <div className="profiles-panel__toolbar">
        <button
          type="button"
          className="profiles-panel__toggle"
          onClick={() => {
            setFormOpen((open) => !open);
          }}
        >
          {formOpen ? 'Hide save form' : 'Save current setup as a profile'}
        </button>
        <button type="button" onClick={handleImportClick} disabled={importState.isLoading}>
          Import
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json"
          className="profiles-panel__file-input"
          onChange={handleFileChosen}
        />
      </div>

      {importState.isError && <p className="panel__error">The upload could not be imported.</p>}

      {formOpen && <SaveProfileForm />}

      {isLoading && <p className="panel__empty">Loading saved profiles…</p>}
      {isError && <p className="panel__error">The saved profiles could not be loaded.</p>}
      {profiles !== undefined && <ProfileList profiles={profiles} />}
    </section>
  );
}
