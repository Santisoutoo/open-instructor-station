/**
 * Approach training: the circuit diagram, and what the selected marker actually resolves to.
 *
 * The altitude and heading in the column are the **preview's** — the server worked them out
 * from the runway's own threshold, elevation and bearing on a 3° path. Nothing on this side
 * recomputes them; the footnote says where they come from rather than a second arithmetic
 * doing it again and disagreeing by a hundred feet.
 *
 * The final-distance selector is the one approved addition to the mockup. The diagram's two
 * final dots are a picture of "on the centreline, close in and further out"; the server
 * serves seven finals from 20 NM to short, and Phase 1's exit criterion is a 10 NM ILS
 * final. The dots stay; the selector is what places.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { CircuitDiagram } from './CircuitDiagram';
import { FactRow } from './FactRow';
import { FINAL_LABELS, FINAL_ORDER } from './finals';
import { formatAltitudeFt, formatDistanceNm, formatHeadingTrue } from './format';
import {
  isDownwindMarker,
  isFinalMarker,
  markerDistanceNm,
  markerLabel,
} from './markers';
import {
  finalPlacementSelected,
  markerDistanceChanged,
  markerSelected,
  type EditableDistanceMarkerId,
  type MarkerId,
} from './positionDesignSlice';
import { useSelectedRunway, useStagedPlacement, useWeather } from './usePositionData';
import { approachWindText } from './wind';

export function ApproachTrainingTab() {
  const dispatch = useAppDispatch();
  const selectedMarker = useAppSelector((state) => state.positionDesign.selectedMarker);
  const finalPlacement = useAppSelector((state) => state.positionDesign.finalPlacement);
  const markerDistances = useAppSelector((state) => state.positionDesign.markerDistances);

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
      <CircuitDiagram
        courseDeg={courseDeg}
        runwayIdent={runway?.ident ?? '—'}
        windDeg={wind?.directionDeg ?? null}
        windKt={wind?.speedKt ?? null}
        selectedMarker={selectedMarker}
        onSelectMarker={(id: MarkerId) => {
          dispatch(markerSelected(id));
          // The two final dots are shortcuts to two of the server's finals; the selector
          // beside them refines. Clicking a dot without moving the selector would leave the
          // screen drawing 8 NM and placing at 3.
          if (id === 'final-3nm') {
            dispatch(finalPlacementSelected('final_3nm'));
          } else if (id === 'final-8nm') {
            dispatch(finalPlacementSelected('final_8nm'));
          }
        }}
      />
      <div className="pos-approachtab__selected">
        <h3 className="pos-approachtab__name">
          {markerLabel(selectedMarker, finalPlacement)}
        </h3>

        {isFinalMarker(selectedMarker) && (
          <div
            className="pos-approachtab__finals"
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

        {isFinalMarker(selectedMarker) || selectedMarker === 'takeoff' ? (
          <FactRow
            label={isDownwindMarker(selectedMarker) ? 'Abeam offset' : 'Distance'}
            value={formatDistanceNm(
              markerDistanceNm(selectedMarker, finalPlacement, markerDistances),
            )}
          />
        ) : (
          <label className="pos-field">
            <span className="pos-field__label">
              {isDownwindMarker(selectedMarker) ? 'Abeam offset (NM)' : 'Distance (NM)'}
            </span>
            <input
              type="number"
              min="0.1"
              className="pos-field__input pos-mono"
              value={markerDistanceNm(selectedMarker, finalPlacement, markerDistances)}
              onChange={(event) => {
                dispatch(
                  markerDistanceChanged({
                    id: selectedMarker as EditableDistanceMarkerId,
                    value: event.target.value === '' ? null : Number(event.target.value),
                  }),
                );
              }}
            />
          </label>
        )}
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
  );
}
