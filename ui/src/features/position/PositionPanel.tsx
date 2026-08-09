/**
 * The Position Manager panel: airport, runway, placement, staging bar.
 *
 * The whole body is gated on the navdata status exactly as the rest of the app is gated on
 * adapter capabilities — there is no point offering an airport search over an index that
 * does not exist. The commit is gated separately, so a panel attached to an adapter that
 * cannot reposition is still fully explorable; only the button is dead, and it says why.
 */

import {
  useBuildNavdataIndexMutation,
  useGetNavdataStatusQuery,
} from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { AirportSearch } from './AirportSearch';
import { CoordinateForm } from './CoordinateForm';
import { ParkingList } from './ParkingList';
import { PatternGrid } from './PatternGrid';
import { ProcedureList } from './ProcedureList';
import { RunwaySelector } from './RunwaySelector';
import { StagingBar } from './StagingBar';
import { airacLabel, navdataGate } from './gate';
import { type PositionTab, tabSelected } from './positionSlice';
import './position.css';

/** How often to re-read the status while an index build is running. */
const BUILD_POLL_MS = 1000;

const TABS: readonly { id: PositionTab; label: string }[] = [
  { id: 'pattern', label: 'Pattern & final' },
  { id: 'procedures', label: 'Procedures' },
  { id: 'parking', label: 'Gates & stands' },
  { id: 'coordinate', label: 'Coordinate & fix' },
];

function NavdataCard({
  reason,
  canBuild,
  fraction,
}: {
  reason: string;
  canBuild: boolean;
  fraction: number | null;
}) {
  const [buildIndex, buildState] = useBuildNavdataIndexMutation();
  return (
    <div className="navdata-card">
      <p className="navdata-card__reason">{reason}</p>
      {fraction !== null && (
        <div
          className="navdata-card__bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fraction * 100)}
        >
          <span style={{ width: `${String(Math.round(fraction * 100))}%` }} />
        </div>
      )}
      {canBuild && (
        <button
          type="button"
          className="navdata-card__build"
          disabled={buildState.isLoading}
          onClick={() => {
            void buildIndex();
          }}
        >
          {buildState.isLoading ? 'Starting…' : 'Build index'}
        </button>
      )}
    </div>
  );
}

export function PositionPanel() {
  const dispatch = useAppDispatch();
  const selectedIcao = useAppSelector((state) => state.position.selectedIcao);
  const selectedRunway = useAppSelector((state) => state.position.selectedRunwayIdent);
  const activeTab = useAppSelector((state) => state.position.activeTab);

  const { data: status, isError } = useGetNavdataStatusQuery(undefined, {
    pollingInterval: BUILD_POLL_MS,
    skipPollingIfUnfocused: true,
  });
  const gate = navdataGate(status, isError);
  const airac = airacLabel(status);

  return (
    <section className="panel panel--position" aria-labelledby="position-heading">
      <div className="panel__head">
        <h2 id="position-heading">Position</h2>
        {airac !== null && <span className="panel__badge mono">{airac}</span>}
      </div>

      {gate.kind === 'loading' && <p className="panel__empty">{gate.reason}</p>}
      {gate.kind === 'blocked' && (
        <NavdataCard reason={gate.reason} canBuild={gate.canBuild} fraction={null} />
      )}
      {gate.kind === 'building' && (
        <NavdataCard reason={gate.reason} canBuild={false} fraction={gate.fraction} />
      )}

      {gate.kind === 'ready' && (
        <>
          <AirportSearch />

          {selectedIcao === null ? (
            <p className="panel__empty">
              Search for an airport to begin. Every airport in the simulator&apos;s
              navigation data is available.
            </p>
          ) : (
            <>
              <RunwaySelector icao={selectedIcao} />

              <div className="tabs" role="tablist" aria-label="Placement type">
                {TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    className={`tab${activeTab === tab.id ? ' tab--active' : ''}`}
                    aria-selected={activeTab === tab.id}
                    onClick={() => {
                      dispatch(tabSelected(tab.id));
                    }}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="tabs__body">
                {activeTab === 'pattern' &&
                  (selectedRunway === null ? (
                    <p className="panel__empty">
                      Pick a runway end above. A final or a circuit leg is always relative
                      to one end.
                    </p>
                  ) : (
                    <PatternGrid icao={selectedIcao} runwayIdent={selectedRunway} />
                  ))}
                {activeTab === 'procedures' && <ProcedureList icao={selectedIcao} />}
                {activeTab === 'parking' && <ParkingList icao={selectedIcao} />}
                {activeTab === 'coordinate' && <CoordinateForm />}
              </div>
            </>
          )}

          <StagingBar />
        </>
      )}
    </section>
  );
}
