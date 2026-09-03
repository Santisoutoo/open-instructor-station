/**
 * The Cockpit Controls tab — Wave 1 Track C (design §7, issue #221).
 *
 * Renders whatever catalog `GET /api/cockpit/catalog` reports: no control is named
 * anywhere in this feature folder. Gated on `can_control_cockpit` (`gate.ts`, fail-closed,
 * the `cameraGate`/`failuresGate` pattern); with the capability present but no aircraft
 * detected, the banner alone explains why and offers "Re-detect aircraft" — hard rule 3,
 * disabled/hidden with a reason, never a throw.
 *
 * Reads and writes take deliberately different routes (design D8/D13): `GET
 * /cockpit/state` is polled every `STATE_POLL_MS` while the tab is open, a capability is
 * present and a catalog is active, scoped to the selected panel — or left unscoped while
 * a search is active, since a match can be on a panel that is not the one showing. `POST
 * /cockpit/actuate` is one write; `cockpitApi.ts` patches the state cache and reconciles
 * the revision straight from the response (its own module docstring) — this component
 * only owns the pending lock and the error banner around that call.
 */

import { useMemo } from 'react';
import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import type { CockpitActuation } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { AircraftBanner } from './AircraftBanner';
import {
  useActuateCockpitControlMutation,
  useGetCockpitCatalogQuery,
  useGetCockpitStateQuery,
  useRefreshCockpitCatalogMutation,
} from './cockpitApi';
import { ControlList } from './ControlList';
import type { ActuationBody } from './ControlRow';
import { ControlSearch } from './ControlSearch';
import {
  actuationSettled,
  actuationStarted,
  errorDismissed,
  panelSelected,
  searchChanged,
} from './cockpitSlice';
import { cockpitErrorDetail } from './errors';
import { controlStateMap, visibleControls, visibleParked } from './filter';
import { cockpitGate } from './gate';
import { PanelPicker } from './PanelPicker';
import './cockpit.css';

/** How often `/state` is re-read while the tab is mounted, gated open and a catalog is active. */
const STATE_POLL_MS = 2000;

export function CockpitPanel() {
  const dispatch = useAppDispatch();

  const capabilitiesQuery = useGetCapabilitiesQuery();
  const gate = cockpitGate(capabilitiesQuery.data, capabilitiesQuery.isError);

  const { selectedPanelId, search, pending, lastError } = useAppSelector(
    (state) => state.cockpit,
  );

  const catalogQuery = useGetCockpitCatalogQuery(undefined, { skip: !gate.open });
  const catalog = catalogQuery.data;
  const hasAircraft = catalog?.aircraft != null;

  const sortedPanels = useMemo(
    () => [...(catalog?.panels ?? [])].sort((a, b) => a.order - b.order),
    [catalog?.panels],
  );
  const activePanelId = selectedPanelId ?? sortedPanels[0]?.panel_id ?? null;
  const searching = search.trim() !== '';
  const stateArg = searching ? undefined : (activePanelId ?? undefined);
  // `exactOptionalPropertyTypes` forbids an explicit `panel: undefined` — the unscoped
  // request must omit the key entirely, not carry it with an `undefined` value.
  const stateQueryArg = stateArg === undefined ? {} : { panel: stateArg };

  const stateQuery = useGetCockpitStateQuery(
    stateQueryArg,
    {
      skip: !gate.open || !hasAircraft,
      pollingInterval: gate.open && hasAircraft ? STATE_POLL_MS : 0,
      skipPollingIfUnfocused: true,
    },
  );

  const [actuate] = useActuateCockpitControlMutation();
  const [refresh, refreshMutation] = useRefreshCockpitCatalogMutation();

  const states = useMemo(() => controlStateMap(stateQuery.data), [stateQuery.data]);
  const visible = useMemo(
    () =>
      catalog === undefined
        ? { controls: [], parked: [] }
        : {
            controls: visibleControls(catalog, activePanelId, search),
            parked: visibleParked(catalog, activePanelId, search),
          },
    [catalog, activePanelId, search],
  );

  const stale =
    stateQuery.data !== undefined &&
    catalog !== undefined &&
    stateQuery.data.revision !== catalog.revision;

  const write = async (controlId: string, body: ActuationBody) => {
    dispatch(actuationStarted(controlId));
    const actuation: CockpitActuation = { control_id: controlId, ...body };
    try {
      await actuate(actuation).unwrap();
      dispatch(actuationSettled({ controlId }));
    } catch (error) {
      dispatch(
        actuationSettled({
          controlId,
          error: cockpitErrorDetail(error, 'The control could not be actuated.'),
        }),
      );
    }
  };

  const emptyMessage =
    search.trim() !== ''
      ? `No controls match “${search.trim()}”.`
      : 'This panel has no controls.';

  return (
    <section className="panel cockpit-panel" aria-labelledby="cockpit-heading">
      <h2 id="cockpit-heading">Cockpit</h2>

      {!gate.open && <p className="panel__empty">{gate.reason}</p>}

      {gate.open && (
        <>
          {catalogQuery.isLoading && (
            <p className="panel__empty">Loading the cockpit catalog…</p>
          )}
          {catalogQuery.isError && (
            <p className="panel__error">
              The cockpit catalog could not be loaded — every control stays hidden.
            </p>
          )}

          {catalog !== undefined && (
            <AircraftBanner
              manifest={catalog}
              stale={stale}
              refreshing={refreshMutation.isLoading}
              onRefresh={() => {
                void refresh();
              }}
            />
          )}

          {lastError !== null && (
            <p className="panel__error" role="alert">
              {lastError}{' '}
              <button
                type="button"
                className="control__dismiss"
                onClick={() => {
                  dispatch(errorDismissed());
                }}
              >
                Dismiss
              </button>
            </p>
          )}

          {hasAircraft && (
            <>
              <ControlSearch
                value={search}
                onChange={(value) => {
                  dispatch(searchChanged(value));
                }}
              />
              {!searching && (
                <PanelPicker
                  panels={sortedPanels}
                  activePanelId={activePanelId}
                  onSelect={(panelId) => {
                    dispatch(panelSelected(panelId));
                  }}
                />
              )}
              {stateQuery.isError && (
                <p className="panel__error">
                  The control states could not be read — values below may be stale.
                </p>
              )}
              <ControlList
                controls={visible.controls}
                parked={visible.parked}
                states={states}
                pending={pending}
                emptyMessage={emptyMessage}
                onCommit={(controlId, body) => {
                  void write(controlId, body);
                }}
              />
            </>
          )}
        </>
      )}
    </section>
  );
}
