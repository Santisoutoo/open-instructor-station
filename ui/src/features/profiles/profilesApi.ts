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
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  ProfileApplyResult,
  ProfileSummary,
  TrainingProfile,
  TrainingProfileCreate,
} from '../../api/models';

export const profilesApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /** Every saved profile, summarised, newest `updated_at` first. */
    getProfiles: builder.query<ProfileSummary[], void>({
      query: () => 'profiles',
      providesTags: ['Profiles'],
    }),
    /** One profile, in full. Fetched when a row expands. */
    getProfile: builder.query<TrainingProfile, string>({
      query: (profileId) => `profiles/${profileId}`,
      providesTags: (_result, _error, profileId) => [{ type: 'Profiles', id: profileId }],
    }),
    /** Save a new profile. The server assigns `profile_id` and timestamps. */
    createProfile: builder.mutation<TrainingProfile, TrainingProfileCreate>({
      query: (draft) => ({ url: 'profiles', method: 'POST', body: draft }),
      invalidatesTags: ['Profiles'],
    }),
    /** Replace name/description/author/scenario of an existing profile. Never creates. */
    replaceProfile: builder.mutation<
      TrainingProfile,
      { profileId: string; draft: TrainingProfileCreate }
    >({
      query: ({ profileId, draft }) => ({
        url: `profiles/${profileId}`,
        method: 'PUT',
        body: draft,
      }),
      invalidatesTags: (_result, _error, { profileId }) => [
        'Profiles',
        { type: 'Profiles', id: profileId },
      ],
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
  useGetProfileQuery,
  useCreateProfileMutation,
  useReplaceProfileMutation,
  useDeleteProfileMutation,
  useApplyProfileMutation,
  useImportProfileMutation,
} = profilesApi;
