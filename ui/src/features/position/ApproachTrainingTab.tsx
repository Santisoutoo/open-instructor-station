/**
 * Approach training: the circuit diagram, and what the selected marker actually resolves to.
 *
 * The altitude and heading in the column are the **preview's** — the server worked them out
 * from the runway's own threshold, elevation and bearing on a 3° path. Nothing on this side
 * recomputes them; the footnote says where they come from rather than a second arithmetic
 * doing it again and disagreeing by a hundred feet.
 *
 * The final-distance selector was the first approved addition to the mockup, and issue #216
 * extended the idea to every other circuit marker: downwind, base and vectors each get their
 * own distance selector too (abeam offset for downwind, distance out for base/vectors), so an
 * instructor is never stuck with the diagram's illustrative distances. Only `takeoff` has
 * nothing to select — a threshold placement has no distance.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { CircuitDiagram } from './CircuitDiagram';
import { CIRCUIT_LEG_OPTIONS_NM } from './circuitDistances';
import { FactRow } from './FactRow';
import { FINAL_LABELS, FINAL_ORDER } from './finals';
import { formatAltitudeFt, formatDistanceNm, formatHeadingTrue } from './format';
import {
  isDownwindMarker,
  isFinalMarker,
  legKindOf,
  markerDistanceNm,
  markerLabel,
} from './markers';
import {
  circuitDistanceSelected,
  finalPlacementSelected,
  markerSelected,
  type MarkerId,
} from './positionDesignSlice';
import { useSelectedRunway, useStagedPlacement, useWeather } from './usePositionData';
import { approachWindText } from './wind';

export function ApproachTrainingTab() {
  const dispatch = useAppDispatch();
  const selectedMarker = useAppSelector((state) => state.positionDesign.selectedMarker);
  const finalPlacement = useAppSelector((state) => state.positionDesign.finalPlacement);
  const circuitDistanceNm = useAppSelector(
    (state) => state.positionDesign.circuitDistanceNm,
  );
  const legKind = legKindOf(selectedMarker);

  const runway = useSelectedRunway();
  const { wind } = useWeather();
  const { preview } = useStagedPlacement();

  const courseDeg = runway?.true_bearing_deg ?? 0;
  const altitudeFt = preview?.placement.position.altitude_ft ?? null;
  const headingDeg = preview?.placement.heading_deg ?? null;

  return (
    <div
      id="pos-tabpanel-approach"
      role="tabpanel"
      aria-labelledby="pos-tab-approach"
      className="pos-approachtab"
    >
      <div className="pos-approachtab__grid">
        <div className="pos-approachtab__diagram">
          <CircuitDiagram
            courseDeg={courseDeg}
            runwayIdent={runway?.ident ?? '—'}
            windDeg={wind?.directionDeg ?? null}
            windKt={wind?.speedKt ?? null}
            selectedMarker={selectedMarker}
            onSelectMarker={(id: MarkerId) => {
              dispatch(markerSelected(id));
              // The 3 NM dot is a shortcut to one of the server's finals; the selector beside
              // it refines. Clicking the dot without moving the selector would leave the
              // screen placing at whatever final was last selected instead of 3 NM.
              if (id === 'final-3nm') {
                dispatch(finalPlacementSelected('final_3nm'));
              }
            }}
          />
        </div>
        <div className="pos-approachtab__selected">
          <h3 className="pos-approachtab__name">
            {markerLabel(selectedMarker, finalPlacement)}
          </h3>

          {isFinalMarker(selectedMarker) && (
            <div
              className="pos-approachtab__distances"
              role="radiogroup"
              aria-label="Final distance"
            >
              {FINAL_ORDER.map((name) => (
                <button
                  key={name}
                  type="button"
                  role="radio"
                  aria-checked={name === finalPlacement}
                  className={
                    name === finalPlacement
                      ? 'pos-chip pos-chip--selected pos-mono'
                      : 'pos-chip pos-mono'
                  }
                  onClick={() => {
                    dispatch(finalPlacementSelected(name));
                  }}
                >
                  {FINAL_LABELS[name]}
                </button>
              ))}
            </div>
          )}

          {legKind !== null && (
            <div
              className="pos-approachtab__distances"
              role="radiogroup"
              aria-label={isDownwindMarker(selectedMarker) ? 'Abeam offset' : 'Distance'}
            >
              {CIRCUIT_LEG_OPTIONS_NM[legKind].map((nm) => (
                <button
                  key={nm}
                  type="button"
                  role="radio"
                  aria-checked={nm === circuitDistanceNm[legKind]}
                  className={
                    nm === circuitDistanceNm[legKind]
                      ? 'pos-chip pos-chip--selected pos-mono'
                      : 'pos-chip pos-mono'
                  }
                  onClick={() => {
                    dispatch(circuitDistanceSelected({ kind: legKind, distanceNm: nm }));
                  }}
                >
                  {nm} NM
                </button>
              ))}
            </div>
          )}

          <FactRow
            label={isDownwindMarker(selectedMarker) ? 'Abeam offset' : 'Distance'}
            value={formatDistanceNm(
              markerDistanceNm(selectedMarker, finalPlacement, circuitDistanceNm),
            )}
          />
          <FactRow
            label="Altitude"
            value={
              altitudeFt === null ? 'not resolved' : `${formatAltitudeFt(altitudeFt)} MSL`
            }
          />
          <FactRow
            label="Heading"
            value={headingDeg === null ? 'not resolved' : formatHeadingTrue(headingDeg)}
          />
          <FactRow
            label="Wind"
            value={
              wind === null
                ? 'not available'
                : approachWindText(wind.directionDeg, wind.speedKt, courseDeg)
            }
          />
          <FactRow label="Runway" value={runway?.ident ?? '—'} />
          <p className="pos-approachtab__footnote">
            Ticks every 2 NM from the threshold. The altitude and heading are the
            server&apos;s, resolved from the runway&apos;s published threshold, elevation
            and bearing.
          </p>
        </div>
      </div>
    </div>
  );
}
