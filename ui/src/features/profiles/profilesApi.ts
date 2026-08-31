/**
 * Training Profiles endpoints injected into the shared API slice —
 * `server/profile_routes.py`.
 *
 * `Profiles` is declared on the shared `instructorApi` (the `FuelPayload` tag's own
 * precedent, not the Weather/Failures polling shape): the list genuinely needs
 * tag-based invalidation across create/delete/import, which a manual cache write
 * cannot express as cleanly as a tag can. `applyProfile` additionally invalidates
 * `AircraftState` — the shared tag every other manager's own apply mutation
 * invalidates — because applying a profile can move the aircraft and write weather
 * and failures the way any of those managers' own applies do.
 *
 * `exportProfile` is deliberately **not** an endpoint here (D6 of
 * `docs/designs/training-profiles.md`'s panel outline, §7.1): `ProfileList.tsx` renders
 * a plain `<a href="/api/profiles/{id}/export" download>` so the browser handles the
 * download natively, with zero client-side blob juggling.
 *
 * `GET /api/profiles/{id}` and `PUT /api/profiles/{id}` exist on the server (D13:
 * REST completeness for scripting and a later UI, not scope creep) but have no
 * client binding here — no row-expand or edit UI in this Phase 2 panel calls
 * either. Add `getProfile`/`replaceProfile` back alongside whichever UI first
 * needs them, rather than shipping an unexercised hook ahead of that need.
 */

import { instructorApi } from '../../api/instructorApi';
import type { ProfileApplyResult, ProfileSummary, TrainingProfile, TrainingProfileCreate } from '../../api/models';

export const profilesApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /** Every saved profile, summarised, newest `updated_at` first. */
    getProfiles: builder.query<ProfileSummary[], void>({
      query: () => 'profiles',
      providesTags: ['Profiles'],
    }),
    /** Save a new profile. The server assigns `profile_id` and timestamps. */
    createProfile: builder.mutation<TrainingProfile, TrainingProfileCreate>({
      query: (draft) => ({ url: 'profiles', method: 'POST', body: draft }),
      invalidatesTags: ['Profiles'],
    }),
    /** Remove a profile. */
    deleteProfile: builder.mutation<void, string>({
      query: (profileId) => ({ url: `profiles/${profileId}`, method: 'DELETE' }),
      invalidatesTags: ['Profiles'],
    }),
    /**
     * Run the embedded scenario, each component attempted independently. Almost
     * always 200 — partial application is reported in the body, never as an error.
     */
    applyProfile: builder.mutation<ProfileApplyResult, string>({
      query: (profileId) => ({ url: `profiles/${profileId}/apply`, method: 'POST' }),
      invalidatesTags: ['AircraftState'],
    }),
    /** Upload a `.json` file exported from this or another instance. Always a fresh id. */
    importProfile: builder.mutation<TrainingProfile, FormData>({
      query: (formData) => ({ url: 'profiles/import', method: 'POST', body: formData }),
      invalidatesTags: ['Profiles'],
    }),
  }),
});

export const {
  useGetProfilesQuery,
  useCreateProfileMutation,
  useDeleteProfileMutation,
  useApplyProfileMutation,
  useImportProfileMutation,
} = profilesApi;
