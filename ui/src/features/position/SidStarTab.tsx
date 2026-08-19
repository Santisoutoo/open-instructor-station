import { useRef } from 'react';
import { FactRow } from './FactRow';
import { Popover } from './Popover';
import {
  PROCEDURE_KINDS,
  procedureIdentSelected,
  procedureKindSelected,
  procedureMenuToggled,
  type ProcedureKind,
} from './positionDesignSlice';
import { PROCEDURE_IDENTS, splitProcedureIdent } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';

const KIND_LABEL: Record<ProcedureKind, string> = {
  sid: 'Departure · SID',
  star: 'Arrival · STAR',
  apptr: 'Approach transition · APPTR',
  final: 'Final approach · FINAL',
};

export function SidStarTab() {
  const dispatch = useAppDispatch();
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const procedureKind = useAppSelector((state) => state.positionDesign.procedureKind);
  const procedureIdent = useAppSelector((state) => state.positionDesign.procedureIdent);
  const menuOpen = useAppSelector((state) => state.positionDesign.procedureMenuOpen);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const breadcrumb = splitProcedureIdent(procedureIdent);

  return (
    <div
      id="pos-tabpanel-sidstar"
      role="tabpanel"
      aria-labelledby="pos-tab-sidstar"
      className="pos-sidstartab"
    >
      <div className="pos-sidstartab__kind" role="radiogroup" aria-label="Procedure type">
        {PROCEDURE_KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            role="radio"
            aria-checked={kind === procedureKind}
            className={kind === procedureKind ? 'pos-chip pos-chip--selected' : 'pos-chip'}
            onClick={() => {
              dispatch(procedureKindSelected(kind));
            }}
          >
            {KIND_LABEL[kind]}
          </button>
        ))}
      </div>

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
          {procedureIdent}
        </button>
        <span className="pos-sidstartab__ident-count">
          {String(PROCEDURE_IDENTS.length)} in navdata
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
          <ul className="pos-sidstartab__ident-list" role="listbox" aria-label="Procedure ident">
            {PROCEDURE_IDENTS.map((entry) => (
              <li key={entry.ident}>
                <button
                  type="button"
                  role="option"
                  aria-selected={entry.ident === procedureIdent}
                  className="pos-sidstartab__ident-option pos-mono"
                  onClick={() => {
                    dispatch(procedureIdentSelected(entry.ident));
                  }}
                >
                  {entry.ident}
                  <span className="pos-sidstartab__ident-via">via {entry.via}</span>
                </button>
              </li>
            ))}
          </ul>
        </Popover>
      </div>

      <div className="pos-sidstartab__breadcrumb pos-mono">
        <span>LFMN/{selectedRunway ?? '—'}</span>
        <span aria-hidden="true">→</span>
        <span>{breadcrumb.short}</span>
        <span aria-hidden="true">→</span>
        <span>{breadcrumb.waypoint}</span>
      </div>

      <div className="pos-sidstartab__facts">
        <FactRow label="Transition" value={breadcrumb.transition} />
        <FactRow label="First waypoint" value={breadcrumb.waypoint} />
        <FactRow label="Altitude restriction" value="not in navdata" />
      </div>
    </div>
  );
}
