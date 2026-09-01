/**
 * SID, STAR and approach procedures, and the leg the aircraft is placed on.
 *
 * **Unpositionable legs are shown, not hidden.** A `CA` leg ends at an altitude rather than
 * at a fix, so it has no defensible coordinate — but an instructor reading a SID needs to
 * see the climb leg to make sense of the ones around it. Those rows render disabled with
 * the server's own `unpositionable_reason` beside them. Nothing here knows ARINC 424:
 * `is_positionable` and the reason are both computed by the navdata provider.
 *
 * The diagram and the leg list sit side by side (`.pos-sidstartab__split`) rather than
 * stacked: together they were taller than the panel, so picking a leg scrolled the picture
 * out of view — the one thing the picture exists to prevent. The split collapses back to a
 * single column on its own when a column would be too narrow, which is a *container* width
 * question and not a viewport one: `ApplyRail` takes its own slice of the same row.
 */

import { Suspense, lazy, useRef } from 'react';
import {
  useGetProcedureLayoutQuery,
  useGetProcedureQuery,
  useGetProceduresQuery,
} from '../../api/instructorApi';
import type { Procedure, ProcedureLeg } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import {
  APPROACH_TYPE_LABEL,
  approachTypeMatches,
  approachTypeOf,
  approachTypesIn,
  commonApproachTypes,
  familyHasApproachType,
} from './approachTypes';
import { FactRow } from './FactRow';
import { Popover } from './Popover';
import { ProcedureDiagram } from './ProcedureDiagram';
import { ProcedureViewToggle } from './ProcedureViewToggle';
import {
  PROCEDURE_FAMILIES,
  approachFilterSelected,
  diagramModeSelected,
  procedureFamilySelected,
  procedureLegSelected,
  procedureMenuToggled,
  procedureSelected,
  type ProcedureFamily,
} from './positionDesignSlice';
import {
  procedureFamilyMatches,
  procedureKindOf,
  useAirport,
  useLoadedIcao,
  useSelectedRunway,
} from './usePositionData';

/**
 * Lazy-loaded so three.js/`@react-three/fiber`/`@react-three/drei` never enter the main
 * bundle. Declared here, not in `ui/src/components/tabs.ts` — that registry lazy-loads the
 * eight top-level app tabs, and the Position panel is already one of them; this is a
 * narrower boundary nested one level deeper, only around the 3D branch of this one tab.
 */
const ProcedureDiagram3D = lazy(() =>
  import('./ProcedureDiagram3D').then((module) => ({
    default: module.ProcedureDiagram3D,
  })),
);

const FAMILY_LABEL: Record<ProcedureFamily, string> = {
  sid: 'Departure · SID',
  star: 'Arrival · STAR',
  apptr: 'Approach transition · APPTR',
  final: 'Final approach · FINAL',
};

function LegRow({
  leg,
  selected,
  onSelect,
}: {
  readonly leg: ProcedureLeg;
  readonly selected: boolean;
  readonly onSelect: (sequence: number) => void;
}) {
  const fix = leg.fix?.ident ?? leg.fix_ref?.ident ?? '—';
  if (!leg.is_positionable) {
    return (
      <li className="pos-legs__row pos-legs__row--unpositionable">
        <span className="pos-mono">{leg.sequence}</span>
        <span className="pos-mono">{leg.path_terminator}</span>
        <span className="pos-mono">{fix}</span>
        <span className="pos-legs__reason">{leg.unpositionable_reason}</span>
      </li>
    );
  }
  return (
    <li className="pos-legs__row">
      <button
        type="button"
        className={
          selected ? 'pos-legs__pick pos-legs__pick--selected' : 'pos-legs__pick'
        }
        aria-pressed={selected}
        onClick={() => {
          onSelect(leg.sequence);
        }}
      >
        <span className="pos-mono">{leg.sequence}</span>
        <span className="pos-mono">{leg.path_terminator}</span>
        <span className="pos-mono">{fix}</span>
        <span className="pos-legs__altitude">{leg.altitude?.display ?? '—'}</span>
      </button>
    </li>
  );
}

/** The legs of the open procedure, and the facts read off the leg that is selected. */
function ProcedureBody({
  procedure,
  sequence,
  onSelectLeg,
  commonTypes,
}: {
  readonly procedure: Procedure;
  readonly sequence: number | null;
  readonly onSelectLeg: (sequence: number) => void;
  readonly commonTypes: ReadonlyMap<string, NonNullable<Procedure['approach_type']>>;
}) {
  const chosen = procedure.legs.find((leg) => leg.sequence === sequence);
  const firstPositionable = procedure.legs.find((leg) => leg.is_positionable);
  const shown = chosen ?? firstPositionable;

  return (
    <>
      <ul className="pos-legs">
        {procedure.legs.map((leg) => (
          <LegRow
            key={leg.sequence}
            leg={leg}
            selected={leg.sequence === sequence}
            onSelect={onSelectLeg}
          />
        ))}
      </ul>
      <div className="pos-sidstartab__facts">
        <FactRow label="Transition" value={procedure.transition ?? 'common route'} />
        {procedure.kind === 'approach' && (
          <FactRow
            label="Approach type"
            value={
              APPROACH_TYPE_LABEL[approachTypeOf(procedure, commonTypes) ?? 'unknown']
            }
          />
        )}
        <FactRow label="First waypoint" value={shown?.fix?.ident ?? '—'} />
        <FactRow
          label="Altitude restriction"
          value={shown?.altitude?.display ?? 'not in navdata'}
        />
      </div>
    </>
  );
}

export function SidStarTab() {
  const dispatch = useAppDispatch();
  const icao = useLoadedIcao();
  const family = useAppSelector((state) => state.positionDesign.procedureFamily);
  const approachFilter = useAppSelector((state) => state.positionDesign.approachFilter);
  const selection = useAppSelector((state) => state.positionDesign.procedure);
  const menuOpen = useAppSelector((state) => state.positionDesign.procedureMenuOpen);
  const diagramMode = useAppSelector((state) => state.positionDesign.diagramMode);
  const runway = useSelectedRunway();
  // The ARP georeferences the 3D view's OSM ground texture (#178). `useAirport()` shares
  // RTK Query's cache with every other caller, so this is a read, not a new request.
  const { airport } = useAirport();
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Shared by both diagram branches — the 2D and 3D views must orient identically.
  const courseDeg = runway?.true_bearing_deg ?? 0;

  const kind = procedureKindOf(family);
  const { data: procedures, isError } = useGetProceduresQuery(
    { icao, kind },
    { skip: icao === '' },
  );
  // The type chips come from the family's own procedures: an airport with only RNAV
  // approaches must not offer an empty ILS chip. Transitions inherit their common
  // route's type, so the lookup is built from every approach, not just the family's.
  const commonTypes = commonApproachTypes(procedures ?? []);
  const ofFamily = (procedures ?? []).filter((procedure) =>
    procedureFamilyMatches(family, procedure.transition),
  );
  const approachTypes = familyHasApproachType(family)
    ? approachTypesIn(ofFamily, commonTypes)
    : [];
  const matching = ofFamily.filter((procedure) =>
    approachTypeMatches(family, approachFilter, procedure, commonTypes),
  );

  const { data: procedure } = useGetProcedureQuery(
    {
      icao,
      kind,
      ident: selection?.ident ?? '',
      transition: selection?.transition ?? null,
    },
    { skip: selection === null },
  );
  const { data: layout } = useGetProcedureLayoutQuery(
    {
      icao,
      kind,
      ident: selection?.ident ?? '',
      transition: selection?.transition ?? null,
      runwayIdent: runway?.ident ?? null,
    },
    { skip: selection === null },
  );

  return (
    <div
      id="pos-tabpanel-sidstar"
      role="tabpanel"
      aria-labelledby="pos-tab-sidstar"
      className="pos-sidstartab"
    >
      <div className="pos-sidstartab__kind" role="radiogroup" aria-label="Procedure type">
        {PROCEDURE_FAMILIES.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={option === family}
            className={option === family ? 'pos-chip pos-chip--selected' : 'pos-chip'}
            onClick={() => {
              dispatch(procedureFamilySelected(option));
            }}
          >
            {FAMILY_LABEL[option]}
          </button>
        ))}
      </div>

      {approachTypes.length > 1 && (
        <div
          className="pos-sidstartab__type"
          role="radiogroup"
          aria-label="Approach type"
        >
          <span className="pos-sidstartab__type-label">Type</span>
          <button
            type="button"
            role="radio"
            aria-checked={approachFilter === 'all'}
            className={
              approachFilter === 'all' ? 'pos-chip pos-chip--selected' : 'pos-chip'
            }
            onClick={() => {
              dispatch(approachFilterSelected('all'));
            }}
          >
            All
            <span className="pos-sidstartab__type-count">{String(ofFamily.length)}</span>
          </button>
          {approachTypes.map(({ type, count }) => (
            <button
              key={type}
              type="button"
              role="radio"
              aria-checked={approachFilter === type}
              className={
                approachFilter === type ? 'pos-chip pos-chip--selected' : 'pos-chip'
              }
              onClick={() => {
                dispatch(approachFilterSelected(type));
              }}
            >
              {APPROACH_TYPE_LABEL[type]}
              <span className="pos-sidstartab__type-count">{String(count)}</span>
            </button>
          ))}
        </div>
      )}

      <div className="pos-sidstartab__ident">
        <button
          ref={triggerRef}
          type="button"
          className="pos-sidstartab__ident-trigger pos-mono"
          aria-haspopup="listbox"
          aria-expanded={menuOpen}
          aria-controls="pos-procedure-ident-menu"
          onClick={() => {
            dispatch(procedureMenuToggled());
          }}
        >
          {selection?.ident ?? 'Choose a procedure'}
        </button>
        <span className="pos-sidstartab__ident-count">
          {String(matching.length)} in navdata
        </span>
        <Popover
          id="pos-procedure-ident-menu"
          open={menuOpen}
          onClose={() => {
            dispatch(procedureMenuToggled());
          }}
          triggerRef={triggerRef}
          className="pos-popover pos-sidstartab__ident-menu"
        >
          <ul
            className="pos-sidstartab__ident-list"
            role="listbox"
            aria-label="Procedure ident"
          >
            {matching.map((entry) => {
              const transition = entry.transition ?? null;
              const type = approachTypeOf(entry, commonTypes);
              return (
                <li key={`${entry.ident}-${transition ?? ''}`}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={
                      entry.ident === selection?.ident &&
                      transition === (selection.transition ?? null)
                    }
                    className="pos-sidstartab__ident-option pos-mono"
                    onClick={() => {
                      dispatch(procedureSelected({ ident: entry.ident, transition }));
                    }}
                  >
                    <span>
                      {entry.ident}
                      {type !== null && (
                        <span className="pos-sidstartab__ident-type">
                          {APPROACH_TYPE_LABEL[type]}
                        </span>
                      )}
                    </span>
                    <span className="pos-sidstartab__ident-via">
                      {transition ?? 'common route'} ·{' '}
                      {String(entry.positionable_leg_count)}/{String(entry.leg_count)}{' '}
                      placeable
                    </span>
                  </button>
                </li>
              );
            })}
            {matching.length === 0 && (
              <li className="pos-sidstartab__ident-empty">
                {isError
                  ? 'The procedures of this airport could not be read.'
                  : approachFilter === 'all'
                    ? 'No procedure of this type in the navigation data.'
                    : `No ${APPROACH_TYPE_LABEL[approachFilter]} approach in the navigation data.`}
              </li>
            )}
          </ul>
        </Popover>
      </div>

      <div className="pos-sidstartab__breadcrumb pos-mono">
        <span>
          {icao === '' ? '—' : icao}/{runway?.ident ?? '—'}
        </span>
        <span aria-hidden="true">→</span>
        <span>{selection?.ident ?? '—'}</span>
        <span aria-hidden="true">→</span>
        <span>
          {procedure?.legs.find((leg) => leg.is_positionable)?.fix?.ident ?? '—'}
        </span>
      </div>

      {procedure === undefined ? (
        <p className="pos-sidstartab__empty">
          Pick a procedure, then the leg to start on. Only legs that carry a resolved fix
          can be placed on.
        </p>
      ) : (
        <div
          className={
            layout !== undefined
              ? 'pos-sidstartab__split'
              : 'pos-sidstartab__split pos-sidstartab__split--legs-only'
          }
        >
          {layout !== undefined && (
            <div className="pos-sidstartab__diagram">
              <ProcedureViewToggle
                mode={diagramMode}
                onSelect={(mode) => {
                  dispatch(diagramModeSelected(mode));
                }}
              />
              <div className="pos-sidstartab__picture">
                {diagramMode === '2d' ? (
                  <ProcedureDiagram
                    layout={layout}
                    courseDeg={courseDeg}
                    selectedSequence={selection?.sequence ?? null}
                    onSelectLeg={(sequence) => {
                      dispatch(procedureLegSelected(sequence));
                    }}
                  />
                ) : (
                  <Suspense
                    fallback={
                      <p className="pos-sidstartab__diagram-loading">Loading 3D view…</p>
                    }
                  >
                    <ProcedureDiagram3D
                      layout={layout}
                      courseDeg={courseDeg}
                      selectedSequence={selection?.sequence ?? null}
                      onSelectLeg={(sequence) => {
                        dispatch(procedureLegSelected(sequence));
                      }}
                      runway={runway ?? undefined}
                      airportPosition={airport?.position}
                    />
                  </Suspense>
                )}
              </div>
            </div>
          )}
          <div className="pos-sidstartab__legs">
            <ProcedureBody
              procedure={procedure}
              commonTypes={commonTypes}
              sequence={selection?.sequence ?? null}
              onSelectLeg={(sequence) => {
                dispatch(procedureLegSelected(sequence));
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
