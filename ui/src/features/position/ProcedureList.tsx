/**
 * SID, STAR and approach procedures, and their legs.
 *
 * **Unpositionable legs are shown, not hidden.** A `CA` leg ends at an altitude rather
 * than at a fix, so it has no defensible coordinate — but an instructor reading a SID
 * needs to see the climb leg to make sense of the ones around it. Those rows render
 * disabled with the server's own `unpositionable_reason` beside them.
 *
 * The UI never decides which legs those are: `is_positionable` and the reason are computed
 * by the navdata provider, so nothing here has to know ARINC 424.
 */

import { useGetProcedureQuery, useGetProceduresQuery } from '../../api/instructorApi';
import type { ProcedureKind, ProcedureLeg } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { placementStaged, procedureOpened } from './positionSlice';

const KINDS: readonly { kind: ProcedureKind; label: string }[] = [
  { kind: 'sid', label: 'SID' },
  { kind: 'star', label: 'STAR' },
  { kind: 'approach', label: 'Approach' },
];

function LegRow({
  leg,
  onStage,
}: {
  leg: ProcedureLeg;
  onStage: (sequence: number) => void;
}) {
  const positionable = leg.is_positionable;
  return (
    <tr className={positionable ? undefined : 'leg--unpositionable'}>
      <td className="mono">{leg.sequence}</td>
      <td className="mono">{leg.path_terminator}</td>
      <td className="mono">{leg.fix?.ident ?? '—'}</td>
      <td>{leg.altitude?.display ?? '—'}</td>
      <td>{leg.speed?.display ?? '—'}</td>
      <td>
        {positionable ? (
          <button
            type="button"
            className="leg__stage"
            onClick={() => {
              onStage(leg.sequence);
            }}
          >
            Stage
          </button>
        ) : (
          <span className="leg__reason">{leg.unpositionable_reason}</span>
        )}
      </td>
    </tr>
  );
}

function ProcedureLegs({
  icao,
  kind,
  ident,
  transition,
}: {
  icao: string;
  kind: ProcedureKind;
  ident: string;
  transition: string | null;
}) {
  const dispatch = useAppDispatch();
  const { data: procedure, isError } = useGetProcedureQuery({
    icao,
    kind,
    ident,
    transition,
  });

  if (isError) {
    return <p className="panel__error">{ident} could not be read.</p>;
  }
  if (procedure === undefined) {
    return <p className="panel__empty">Reading {ident}…</p>;
  }

  return (
    <div className="legs">
      <table className="legs__table">
        <thead>
          <tr>
            <th scope="col">Seq</th>
            <th scope="col">Type</th>
            <th scope="col">Fix</th>
            <th scope="col">Altitude</th>
            <th scope="col">Speed</th>
            <th scope="col">Place</th>
          </tr>
        </thead>
        <tbody>
          {procedure.legs.map((leg) => (
            <LegRow
              key={leg.sequence}
              leg={leg}
              onStage={(sequence) => {
                dispatch(
                  placementStaged({
                    type: 'procedure_leg',
                    airport_icao: icao,
                    kind,
                    ident,
                    transition,
                    sequence,
                  }),
                );
              }}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ProcedureList({ icao }: { icao: string }) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.position.openProcedure);
  const { data: procedures, isError } = useGetProceduresQuery({ icao });

  if (isError) {
    return <p className="panel__error">The procedures of {icao} could not be read.</p>;
  }
  if (procedures === undefined) {
    return <p className="panel__empty">Reading procedures…</p>;
  }
  if (procedures.length === 0) {
    return (
      <p className="panel__empty">
        {icao} has no published procedures in this navigation data.
      </p>
    );
  }

  return (
    <div className="procedures">
      {KINDS.map(({ kind, label }) => {
        const ofKind = procedures.filter((procedure) => procedure.kind === kind);
        if (ofKind.length === 0) {
          return null;
        }
        return (
          <section key={kind} className="procedures__group">
            <h3 className="procedures__title">{label}</h3>
            <ul className="procedures__list">
              {ofKind.map((procedure) => {
                const isOpen =
                  open?.ident === procedure.ident &&
                  open.kind === kind &&
                  open.transition === (procedure.transition ?? null);
                return (
                  <li key={`${procedure.ident}-${procedure.transition ?? ''}`}>
                    <button
                      type="button"
                      className={`procedure${isOpen ? ' procedure--open' : ''}`}
                      aria-expanded={isOpen}
                      onClick={() => {
                        dispatch(
                          procedureOpened(
                            isOpen
                              ? null
                              : {
                                  kind,
                                  ident: procedure.ident,
                                  transition: procedure.transition ?? null,
                                },
                          ),
                        );
                      }}
                    >
                      <span className="mono">{procedure.ident}</span>
                      {procedure.transition != null && (
                        <span className="procedure__transition mono">
                          {procedure.transition}
                        </span>
                      )}
                      <span className="procedure__meta">
                        {procedure.positionable_leg_count}/{procedure.leg_count} placeable
                      </span>
                    </button>
                    {isOpen && (
                      <ProcedureLegs
                        icao={icao}
                        kind={kind}
                        ident={procedure.ident}
                        transition={procedure.transition ?? null}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
