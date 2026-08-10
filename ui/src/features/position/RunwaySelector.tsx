/**
 * One button per runway **end**.
 *
 * 18L and 36R are two buttons, not one, because a placement is always relative to one end:
 * "10 NM final" means nothing until it is known which way the aeroplane is pointing. The
 * server returns them as separate `Runway` objects for the same reason.
 */

import { useGetIlsQuery, useGetRunwaysQuery } from '../../api/instructorApi';
import type { Runway } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { formatIlsFrequency, formatRunwayLength } from './placements';
import { runwaySelected } from './positionSlice';

/** The ILS badge. Its own component because a 404 here is an ordinary outcome. */
function IlsBadge({ icao, runwayIdent }: { icao: string; runwayIdent: string }) {
  const { data: ils } = useGetIlsQuery({ icao, runwayIdent });
  if (ils === undefined) {
    return null;
  }
  return (
    <span className="runway__ils">
      ILS <span className="mono">{formatIlsFrequency(ils.frequency_khz)}</span>
      {ils.glideslope_deg != null && ` · ${ils.glideslope_deg.toFixed(1)}°`}
    </span>
  );
}

function RunwayButton({ runway, selected }: { runway: Runway; selected: boolean }) {
  const dispatch = useAppDispatch();
  return (
    <button
      type="button"
      className={`runway${selected ? ' runway--selected' : ''}`}
      aria-pressed={selected}
      onClick={() => {
        dispatch(runwaySelected(runway.ident));
      }}
    >
      <span className="runway__ident mono">{runway.ident}</span>
      <span className="runway__meta">
        {formatRunwayLength(runway.length_m)}
        {runway.surface != null && ` · ${runway.surface}`}
      </span>
      <IlsBadge icao={runway.airport_icao} runwayIdent={runway.ident} />
    </button>
  );
}

export function RunwaySelector({ icao }: { icao: string }) {
  const selectedIdent = useAppSelector((state) => state.position.selectedRunwayIdent);
  const { data: runways, isFetching, isError } = useGetRunwaysQuery(icao);

  if (isError) {
    return <p className="panel__error">The runways of {icao} could not be read.</p>;
  }
  if (runways === undefined) {
    return <p className="panel__empty">{isFetching ? 'Reading runways…' : ''}</p>;
  }
  if (runways.length === 0) {
    return (
      <p className="panel__empty">
        {icao} publishes no runways in this navigation data, so runway-relative placements
        are unavailable. A coordinate placement still works.
      </p>
    );
  }

  return (
    <div className="runways" role="group" aria-label="Runway end">
      {runways.map((runway) => (
        <RunwayButton
          key={runway.ident}
          runway={runway}
          selected={runway.ident === selectedIdent}
        />
      ))}
    </div>
  );
}
