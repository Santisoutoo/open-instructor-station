/**
 * The Position screen's root: header, runway strip, tab strip + active tab body, right rail,
 * bottom bar, inside the `.pos` scope class. The `data-theme` attribute the CSS reads
 * (`[data-theme='light'] .pos { … }`) is already maintained on `<html>` by `uiSync`.
 *
 * **The body is gated on the navigation data, and the gate fails closed.** There is no point
 * offering an airport search over an index that does not exist, so while it is missing or
 * building the screen says so and offers to build it — the same contract the panel had
 * before the redesign, reinstated here rather than reinvented. The header stays visible
 * through the gate on purpose: this screen is full-bleed, so its screen menu is the only way
 * off it.
 *
 * **An airport is not the only way in.** The Map's "Send to Position tab" hands over a bare
 * coordinate (`docs/designs/instructor-map.md` D5), which is a whole placement on its own and
 * frequently nowhere near a field. When one has been adopted with no airport loaded, the
 * screen shows the Custom location tab, the rail and the commit bar — the runway strip and
 * the other three tabs have nothing behind them and are not drawn. Sending a coordinate to a
 * screen that answers "type an ICAO code" is the same as losing it.
 */

import {
  instructorApi,
  useBuildNavdataIndexMutation,
  useGetNavdataStatusQuery,
} from '../../api/instructorApi';
import { useAppSelector } from '../../store';
import { AirworkTab } from './AirworkTab';
import { ApplyRail } from './ApplyRail';
import { ApproachTrainingTab } from './ApproachTrainingTab';
import { BottomBar } from './BottomBar';
import { CustomLocationTab } from './CustomLocationTab';
import { PositionHeaderBar } from './PositionHeaderBar';
import { PositionTabs } from './PositionTabs';
import { RunwayStrip } from './RunwayStrip';
import { SidStarTab } from './SidStarTab';
import { navdataGate } from './gate';
import './position.css';

/** How often to re-read the status while an index build is running. */
const BUILD_POLL_MS = 1000;

/** Read the cached navdata status without subscribing to it or issuing a request. */
const useGetNavdataStatusState = instructorApi.endpoints.getNavdataStatus.useQueryState;

function NavdataCard({
  reason,
  canBuild,
  fraction,
}: {
  readonly reason: string;
  readonly canBuild: boolean;
  readonly fraction: number | null;
}) {
  const [buildIndex, buildState] = useBuildNavdataIndexMutation();
  return (
    <div className="pos-navdata">
      <p className="pos-navdata__reason">{reason}</p>
      {fraction !== null && (
        <div
          className="pos-navdata__bar"
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
          className="pos-navdata__build"
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
  const activeTab = useAppSelector((state) => state.positionDesign.activeTab);
  const loadedIcao = useAppSelector((state) => state.positionDesign.loadedIcao);
  const hasCoordinate = useAppSelector(
    (state) =>
      state.positionDesign.custom.latitude !== null &&
      state.positionDesign.custom.longitude !== null,
  );

  // Polled **only while a build is running**, which is what `BUILD_POLL_MS` says it is for.
  // A ready index does not change under the screen, and a station left open on one for a
  // lesson would otherwise ask the same question once a second, over the LAN, of the process
  // that is also flying the aeroplane. The interval has to be decided before the query that
  // answers it, hence reading the cache first: `useQueryState` is the same cache entry,
  // without a second subscription or a second request.
  const cached = useGetNavdataStatusState();
  const { data: status, isError } = useGetNavdataStatusQuery(undefined, {
    pollingInterval: cached.data?.state === 'building' ? BUILD_POLL_MS : 0,
    skipPollingIfUnfocused: true,
  });
  const gate = navdataGate(status, isError);

  return (
    <div className="pos">
      <PositionHeaderBar />

      {gate.kind === 'loading' && <p className="pos-empty">{gate.reason}</p>}
      {gate.kind === 'blocked' && (
        <NavdataCard reason={gate.reason} canBuild={gate.canBuild} fraction={null} />
      )}
      {gate.kind === 'building' && (
        <NavdataCard reason={gate.reason} canBuild={false} fraction={gate.fraction} />
      )}

      {gate.kind === 'ready' && loadedIcao !== '' && (
        <>
          <RunwayStrip />
          <PositionTabs />
          <div className="pos-body">
            <div className="pos-main">
              {activeTab === 'approach' && <ApproachTrainingTab />}
              {activeTab === 'sidstar' && <SidStarTab />}
              {activeTab === 'airwork' && <AirworkTab />}
              {activeTab === 'custom' && <CustomLocationTab />}
            </div>
            <ApplyRail />
          </div>
          <BottomBar />
        </>
      )}

      {gate.kind === 'ready' && loadedIcao === '' && hasCoordinate && (
        <>
          <p className="pos-empty">
            A coordinate handed over from another screen. Load an airport to place on a
            runway, a procedure or a stand.
          </p>
          <div className="pos-body">
            <div className="pos-main">
              <CustomLocationTab />
            </div>
            <ApplyRail />
          </div>
          <BottomBar />
        </>
      )}

      {gate.kind === 'ready' && loadedIcao === '' && !hasCoordinate && (
        <p className="pos-empty">
          Type an ICAO code and press Load. Every airport in the simulator&apos;s
          navigation data is available.
        </p>
      )}
    </div>
  );
}
