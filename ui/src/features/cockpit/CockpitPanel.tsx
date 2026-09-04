/**
 * The Cockpit Controls tab — Wave 1 Track C (design §7, issue #221), drawn as a
 * schematic cockpit since issue #253.
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
 *
 * The schematic (issue #253) adds one panel-at-a-time drawing keyed by the catalog id
 * (`layouts/`), a Schematic / List toggle, and the one rotary **draft** shared by the
 * slot under the wheel and the tray's editor: the wheel, the keys and the `±` buttons
 * only ever edit that draft, and a single write leaves on Enter / Set. A search, the
 * List mode, or an aircraft without a layout all fall back to the flat list unchanged.
 */

import { useEffect, useMemo } from 'react';
import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import type { CockpitActuation, CockpitControlSpec } from '../../api/models';
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
  slotFocused,
  viewModeSet,
} from './cockpitSlice';
import { cockpitErrorDetail } from './errors';
import { controlStateMap, unmetHints, visibleControls, visibleParked } from './filter';
import { cockpitGate } from './gate';
import { layoutFor, slotIndex, type LayoutSlot } from './layouts';
import { PanelPicker } from './PanelPicker';
import { SchematicPanel } from './SchematicPanel';
import { SchematicTray, type TrayFocus } from './SchematicTray';
import { ViewModeToggle } from './ViewModeToggle';
import { useRotaryDraft } from './widgets/useRotaryDraft';
import './cockpit.css';

/** How often `/state` is re-read while the tab is mounted, gated open and a catalog is active. */
const STATE_POLL_MS = 2000;

export function CockpitPanel() {
  const dispatch = useAppDispatch();

  const capabilitiesQuery = useGetCapabilitiesQuery();
  const gate = cockpitGate(capabilitiesQuery.data, capabilitiesQuery.isError);

  const { selectedPanelId, viewMode, focusedControlId, search, pending, lastError } =
    useAppSelector((state) => state.cockpit);

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

  const stateQuery = useGetCockpitStateQuery(stateQueryArg, {
    skip: !gate.open || !hasAircraft,
    pollingInterval: gate.open && hasAircraft ? STATE_POLL_MS : 0,
    skipPollingIfUnfocused: true,
  });

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

  // --- schematic -----------------------------------------------------------------
  const layout = layoutFor(catalog?.aircraft?.catalog_id);
  const panelLayout =
    layout !== null && activePanelId !== null
      ? (layout.panels[activePanelId] ?? null)
      : null;
  const schematicReason =
    layout === null
      ? `No schematic for ${catalog?.aircraft?.label ?? 'this aircraft'}`
      : panelLayout === null
        ? 'No schematic for this panel'
        : undefined;
  const schematic = !searching && viewMode === 'schematic' && panelLayout !== null;

  const slots = useMemo(
    () => (panelLayout === null ? new Map<string, LayoutSlot>() : slotIndex(panelLayout)),
    [panelLayout],
  );

  // One draft for the whole tab: the slot under the wheel and the tray's editor share it,
  // so a notch on the diagram shows up in the field and Set writes exactly that.
  const draft = useRotaryDraft();

  // Focus moving away from the draft's control abandons the draft: a panel switch, the
  // List toggle or a lost link must never leave a stale value a slot could still commit.
  // A wheel notch on an unfocused knob focuses and nudges it in the same event, so the
  // two land together and nothing is reset.
  const draftControlId = draft.draft.controlId;
  const resetDraft = draft.reset;
  useEffect(() => {
    if (draftControlId !== null && draftControlId !== focusedControlId) {
      resetDraft(draftControlId);
    }
  }, [draftControlId, focusedControlId, resetDraft]);

  const focused: TrayFocus | null = useMemo(() => {
    if (focusedControlId === null) {
      return null;
    }
    const spec = visible.controls.find(
      (control) => control.control_id === focusedControlId,
    );
    if (spec !== undefined) {
      return { spec, slot: slots.get(focusedControlId) };
    }
    const parked = visible.parked.find((entry) => entry.control_id === focusedControlId);
    return parked === undefined ? null : { parked };
  }, [focusedControlId, visible, slots]);

  const confirmedNumber = (spec: CockpitControlSpec): number | null => {
    const value = states[spec.control_id];
    return typeof value === 'number' ? value : null;
  };

  /** One write. Resolves `true` on a confirmed read-back, `false` on any failure. */
  const write = async (controlId: string, body: ActuationBody): Promise<boolean> => {
    dispatch(actuationStarted(controlId));
    const actuation: CockpitActuation = { control_id: controlId, ...body };
    try {
      await actuate(actuation).unwrap();
      dispatch(actuationSettled({ controlId }));
      return true;
    } catch (error) {
      dispatch(
        actuationSettled({
          controlId,
          error: cockpitErrorDetail(error, 'The control could not be actuated.'),
        }),
      );
      return false;
    }
  };

  const commitDraft = (spec: CockpitControlSpec, slot: LayoutSlot | undefined) => {
    const body = draft.body(spec, slot);
    if (body !== null) {
      // The draft survives a failed write (the instructor retries) and clears on success —
      // scoped to this control, so a draft started elsewhere meanwhile is untouched.
      void write(spec.control_id, body).then((ok) => {
        if (ok) {
          draft.reset(spec.control_id);
        }
      });
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
                <>
                  <PanelPicker
                    panels={sortedPanels}
                    activePanelId={activePanelId}
                    onSelect={(panelId) => {
                      dispatch(panelSelected(panelId));
                    }}
                  />
                  <ViewModeToggle
                    mode={schematic ? 'schematic' : 'list'}
                    onChange={(mode) => {
                      dispatch(viewModeSet(mode));
                    }}
                    {...(schematicReason !== undefined
                      ? { disabledReason: schematicReason }
                      : {})}
                  />
                </>
              )}
              {stateQuery.isError && (
                <p className="panel__error">
                  The control states could not be read — values below may be stale.
                </p>
              )}
              {schematic && panelLayout !== null ? (
                <>
                  <SchematicPanel
                    layout={panelLayout}
                    controls={visible.controls}
                    parked={visible.parked}
                    states={states}
                    pending={pending}
                    focusedId={focusedControlId}
                    draft={draft.draft}
                    onFocus={(controlId) => {
                      dispatch(slotFocused(controlId));
                    }}
                    onCommit={write}
                    onNudge={(spec, slot, sign, count) => {
                      draft.nudge(spec, slot, confirmedNumber(spec), sign, count);
                    }}
                    onDraftText={(spec, text) => {
                      draft.setText(spec, text);
                    }}
                    onCommitDraft={commitDraft}
                    onDiscardDraft={(spec) => {
                      draft.reset(spec.control_id);
                    }}
                  />
                  <SchematicTray
                    focused={focused}
                    value={
                      focused !== null && 'spec' in focused
                        ? states[focused.spec.control_id]
                        : undefined
                    }
                    hints={
                      focused !== null && 'spec' in focused
                        ? unmetHints(focused.spec, states)
                        : []
                    }
                    pending={
                      focused !== null &&
                      'spec' in focused &&
                      pending[focused.spec.control_id] === true
                    }
                    onCommit={(body) =>
                      focused !== null && 'spec' in focused
                        ? write(focused.spec.control_id, body)
                        : undefined
                    }
                    draft={draft}
                  />
                </>
              ) : (
                <ControlList
                  controls={visible.controls}
                  parked={visible.parked}
                  states={states}
                  pending={pending}
                  emptyMessage={emptyMessage}
                  onCommit={write}
                />
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
