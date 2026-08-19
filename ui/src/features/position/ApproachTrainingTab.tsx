import { CircuitDiagram } from './CircuitDiagram';
import { FactRow } from './FactRow';
import { formatAltitudeFt, formatDistanceNm, formatHeadingM } from './format';
import { CIRCUIT_MARKERS, markerHeading } from './markers';
import { markerSelected, type MarkerId } from './positionDesignSlice';
import { RUNWAYS, SAMPLE_WIND } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';
import { approachWindText } from './wind';

export function ApproachTrainingTab() {
  const dispatch = useAppDispatch();
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedMarker = useAppSelector((state) => state.positionDesign.selectedMarker);

  const runway = selectedRunway !== null ? RUNWAYS[selectedRunway] : null;
  const courseDeg = runway !== null && runway.kind === 'runway' ? runway.courseDeg : 0;
  const marker = CIRCUIT_MARKERS[selectedMarker];
  const heading = markerHeading(selectedMarker, courseDeg);

  function selectMarker(id: MarkerId) {
    dispatch(markerSelected(id));
  }

  return (
    <div
      id="pos-tabpanel-approach"
      role="tabpanel"
      aria-labelledby="pos-tab-approach"
      className="pos-approachtab"
    >
      <CircuitDiagram
        courseDeg={courseDeg}
        runwayIdent={selectedRunway ?? '—'}
        windDeg={SAMPLE_WIND.directionDeg}
        windKt={SAMPLE_WIND.speedKt}
        selectedMarker={selectedMarker}
        onSelectMarker={selectMarker}
      />
      <div className="pos-approachtab__selected">
        <h3 className="pos-approachtab__name">{marker.label}</h3>
        <FactRow label="Distance" value={formatDistanceNm(marker.distNm)} />
        <FactRow label="Altitude" value={`${formatAltitudeFt(marker.altFt)} ${marker.altRef}`} />
        <FactRow label="Heading" value={formatHeadingM(heading)} />
        <FactRow
          label="Wind"
          value={approachWindText(SAMPLE_WIND.directionDeg, SAMPLE_WIND.speedKt, courseDeg)}
        />
        <FactRow label="Runway" value={selectedRunway ?? '—'} />
        <p className="pos-approachtab__footnote">
          Ticks every 2 NM from the threshold. Altitudes from a 3° path, 300 ft/NM, pattern
          1,500 ft AAL.
        </p>
      </div>
    </div>
  );
}
