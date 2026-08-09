/**
 * The circuit grid and the finals rail.
 *
 * Laid out spatially: the runway sits in the middle column, the left-hand circuit legs to
 * its left and the right-hand ones to its right, in the order they are flown. An
 * instructor points at where the aeroplane should be rather than reading an identifier off
 * a list — which is the one thing the incumbent product gets genuinely right, and the
 * reason this is a grid and not a dropdown.
 *
 * Where it improves on the incumbent: the finals are the full set the feature spec asks
 * for (20 down to 3 NM plus short) rather than two fixed tiles, and nothing here commits.
 * Tapping stages.
 */

import type { PlacementRequest, RunwayPlacementName } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { FINAL_TILES, PATTERN_TILES } from './placements';
import { placementStaged } from './positionSlice';

export function PatternGrid({
  icao,
  runwayIdent,
}: {
  icao: string;
  runwayIdent: string;
}) {
  const dispatch = useAppDispatch();
  const staged = useAppSelector((state) => state.position.staged);

  const stagedName =
    staged !== null && staged.type === 'runway' ? staged.placement : null;

  function stage(placement: RunwayPlacementName) {
    const request: PlacementRequest = {
      type: 'runway',
      airport_icao: icao,
      runway_ident: runwayIdent,
      placement,
    };
    dispatch(placementStaged(request));
  }

  return (
    <div className="pattern">
      <div className="pattern__grid">
        {PATTERN_TILES.map((tile) => (
          <button
            key={tile.name}
            type="button"
            className={`tile${stagedName === tile.name ? ' tile--staged' : ''}`}
            style={{ gridColumn: tile.cell.column, gridRow: tile.cell.row }}
            aria-pressed={stagedName === tile.name}
            onClick={() => {
              stage(tile.name);
            }}
          >
            <span className="tile__label">{tile.label}</span>
            {tile.detail !== null && <span className="tile__detail">{tile.detail}</span>}
          </button>
        ))}

        {/* The runway, drawn as the anchor the tiles are arranged around. */}
        <div className="pattern__runway" style={{ gridColumn: 2, gridRow: '1 / 5' }}>
          <span className="pattern__runway-ident mono">{runwayIdent}</span>
          <span className="pattern__runway-hint">Approach from below</span>
        </div>
      </div>

      <div className="finals" role="group" aria-label="Final approach distances">
        <span className="finals__title">Final</span>
        {FINAL_TILES.map((tile) => (
          <button
            key={tile.name}
            type="button"
            className={`chip${stagedName === tile.name ? ' chip--staged' : ''}`}
            aria-pressed={stagedName === tile.name}
            onClick={() => {
              stage(tile.name);
            }}
          >
            {tile.label}
          </button>
        ))}
      </div>
    </div>
  );
}
