/**
 * `actuateCockpitControl`'s `onQueryStarted` is the interesting part of this module
 * (its own docstring): it patches every currently cached `getCockpitState` variant from
 * the response's own confirmed read-back, and invalidates the catalog/state tags only
 * when the response's `revision` disagrees with the cached catalog's. Both are timing
 * -sensitive (the patch runs as a continuation after the mutation's own promise settles),
 * so assertions poll with `waitFor` rather than assuming a fixed number of microtask
 * ticks.
 */

import { waitFor } from '@testing-library/dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore } from '../../store';
import { cockpitCatalogManifestFixture, cockpitStateSnapshotFixture } from './fixtures';
import { cockpitApi } from './cockpitApi';
import { stubApi } from './testApi';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('cockpitApi', () => {
  it('patches every cached getCockpitState variant with the confirmed read-back', async () => {
    const catalog = cockpitCatalogManifestFixture();
    const snapshot = cockpitStateSnapshotFixture();
    stubApi({
      'GET cockpit/state?panel=mcp': { body: snapshot },
      'GET cockpit/state': { body: snapshot }, // the unscoped (search) variant
      'POST cockpit/actuate': {
        body: {
          requested: { control_id: 'fd_capt', value: true },
          state: { control_id: 'fd_capt', value: true },
          actions_taken: 1,
          catalog_id: catalog.aircraft?.catalog_id,
          revision: catalog.revision,
        },
      },
    });
    const store = setupStore();

    // Two variants live at once, exactly as the panel-scoped view and a cross-panel
    // search would both keep subscribed.
    await store.dispatch(cockpitApi.endpoints.getCockpitState.initiate({ panel: 'mcp' }));
    await store.dispatch(cockpitApi.endpoints.getCockpitState.initiate({}));

    await store.dispatch(
      cockpitApi.endpoints.actuateCockpitControl.initiate({
        control_id: 'fd_capt',
        value: true,
      }),
    );

    await waitFor(() => {
      const scoped = cockpitApi.endpoints.getCockpitState.select({ panel: 'mcp' })(
        store.getState(),
      ).data;
      const unscoped = cockpitApi.endpoints.getCockpitState.select({})(store.getState()).data;
      expect(scoped?.states.find((s) => s.control_id === 'fd_capt')?.value).toBe(true);
      expect(unscoped?.states.find((s) => s.control_id === 'fd_capt')?.value).toBe(true);
    });
  });

  it('adds a new row when the actuated control was not in the cached snapshot yet', async () => {
    const catalog = cockpitCatalogManifestFixture();
    stubApi({
      'GET cockpit/state': { body: { catalog_id: 'fake-trainer', revision: 1, states: [] } },
      'POST cockpit/actuate': {
        body: {
          requested: { control_id: 'landing_lights', value: true },
          state: { control_id: 'landing_lights', value: true },
          actions_taken: 1,
          catalog_id: catalog.aircraft?.catalog_id,
          revision: catalog.revision,
        },
      },
    });
    const store = setupStore();

    await store.dispatch(cockpitApi.endpoints.getCockpitState.initiate({}));
    await store.dispatch(
      cockpitApi.endpoints.actuateCockpitControl.initiate({
        control_id: 'landing_lights',
        value: true,
      }),
    );

    await waitFor(() => {
      const cached = cockpitApi.endpoints.getCockpitState.select({})(store.getState()).data;
      expect(cached?.states.find((s) => s.control_id === 'landing_lights')?.value).toBe(true);
    });
  });

  it('invalidates the catalog and state tags when the response revision disagrees', async () => {
    const catalog = cockpitCatalogManifestFixture(); // revision: 1
    const { calls } = stubApi({
      'GET cockpit/catalog': [{ body: catalog }, { body: { ...catalog, revision: 2 } }],
      'POST cockpit/actuate': {
        body: {
          requested: { control_id: 'fd_capt', value: true },
          state: { control_id: 'fd_capt', value: true },
          actions_taken: 1,
          catalog_id: catalog.aircraft?.catalog_id,
          revision: 2, // the aircraft changed underneath the request
        },
      },
    });
    const store = setupStore();

    // Keeps an active subscription so an invalidated tag triggers a real refetch.
    store.dispatch(cockpitApi.endpoints.getCockpitCatalog.initiate());
    await waitFor(() => {
      expect(calls.filter((call) => call.url.includes('cockpit/catalog')).length).toBe(1);
    });

    await store.dispatch(
      cockpitApi.endpoints.actuateCockpitControl.initiate({
        control_id: 'fd_capt',
        value: true,
      }),
    );

    await waitFor(() => {
      expect(calls.filter((call) => call.url.includes('cockpit/catalog')).length).toBe(2);
    });
  });

  it('does not invalidate anything when the response revision matches', async () => {
    const catalog = cockpitCatalogManifestFixture(); // revision: 1
    const { calls } = stubApi({
      'GET cockpit/catalog': { body: catalog },
      'POST cockpit/actuate': {
        body: {
          requested: { control_id: 'fd_capt', value: true },
          state: { control_id: 'fd_capt', value: true },
          actions_taken: 1,
          catalog_id: catalog.aircraft?.catalog_id,
          revision: catalog.revision,
        },
      },
    });
    const store = setupStore();

    store.dispatch(cockpitApi.endpoints.getCockpitCatalog.initiate());
    await waitFor(() => {
      expect(calls.filter((call) => call.url.includes('cockpit/catalog')).length).toBe(1);
    });

    await store.dispatch(
      cockpitApi.endpoints.actuateCockpitControl.initiate({
        control_id: 'fd_capt',
        value: true,
      }),
    );

    // Give any (wrongly firing) refetch a moment to happen before asserting it did not.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls.filter((call) => call.url.includes('cockpit/catalog')).length).toBe(1);
  });

  it('refreshCockpitCatalog always invalidates both tags — the revision always bumps (D1)', async () => {
    const catalog = cockpitCatalogManifestFixture();
    const { calls } = stubApi({
      'GET cockpit/catalog': { body: catalog },
      'POST cockpit/catalog/refresh': { body: { ...catalog, revision: 2 } },
    });
    const store = setupStore();

    store.dispatch(cockpitApi.endpoints.getCockpitCatalog.initiate());
    await waitFor(() => {
      expect(calls.filter((call) => call.url.includes('cockpit/catalog')).length).toBe(1);
    });

    await store.dispatch(cockpitApi.endpoints.refreshCockpitCatalog.initiate());

    await waitFor(() => {
      expect(
        calls.filter(
          (call) => call.method === 'GET' && call.url.includes('cockpit/catalog'),
        ).length,
      ).toBe(2);
    });
  });
});
