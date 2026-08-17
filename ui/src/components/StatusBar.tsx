import { formatScenarioId } from '../features/scenarios/format';
import { scenariosApi } from '../features/scenarios/scenariosApi';
import { useScenarioRunStatus } from '../features/scenarios/useScenarioRun';
import {
  formatAltitude,
  formatHeading,
  formatSpeed,
  formatVerticalSpeed,
} from '../features/telemetry/format';
import { useAppDispatch, useAppSelector } from '../store';
import { demoFeedToggled } from '../store/uiSlice';

/**
 * The persistent strip along the bottom: the four numbers an instructor glances at
 * between actions, the demo-feed switch, and the sim link state. Always visible,
 * whatever module is open — the tab bar changes the workspace, never the situation.
 */
export function StatusBar() {
  const dispatch = useAppDispatch();
  const latest = useAppSelector((state) => state.telemetry.latest);
  const demoFeed = useAppSelector((state) => state.ui.demoFeed);
  const connectionStatus = useAppSelector((state) => state.connection.status);

  // `useScenarioRunStatus` is an active subscription, not a passive cache read — the
  // footer is always mounted while the Scenarios panel is not (it unmounts on tab
  // switch), so this component must be able to notice a run finishing or failing on its
  // own. The manifest read stays passive: this footer never needs to trigger that fetch
  // itself, only borrow whichever scenario name the Scenarios panel (or a run already in
  // progress) has already caused to be cached.
  const cachedManifest = scenariosApi.endpoints.getScenarios.useQueryState();
  const scenarioRun = useScenarioRunStatus();
  const scenarioName =
    scenarioRun !== null
      ? (cachedManifest.data?.scenarios.find((scenario) => scenario.id === scenarioRun.scenario_id)
          ?.name ?? formatScenarioId(scenarioRun.scenario_id))
      : null;

  const connected = connectionStatus === 'connected';
  const demoActive = demoFeed && !connected;

  const linkModifier = connected
    ? 'statusbar__link--connected'
    : connectionStatus === 'error'
      ? 'statusbar__link--error'
      : '';
  const linkLabel = connected
    ? 'Sim link up'
    : connectionStatus === 'connecting'
      ? 'Sim link connecting…'
      : connectionStatus === 'error'
        ? 'Sim link down'
        : 'Sim link idle';

  return (
    <footer className="statusbar">
      {latest === null ? (
        <span className="statusbar__empty">No aircraft data</span>
      ) : (
        <dl className="statusbar__strip">
          <div className="statusbar__item">
            <dt className="statusbar__label">Alt</dt>
            <dd className="statusbar__value">{formatAltitude(latest.altitude_ft)}</dd>
          </div>
          <div className="statusbar__item">
            <dt className="statusbar__label">IAS</dt>
            <dd className="statusbar__value">{formatSpeed(latest.ias_kt)}</dd>
          </div>
          <div className="statusbar__item">
            <dt className="statusbar__label">Hdg</dt>
            <dd className="statusbar__value">{formatHeading(latest.heading_deg)}</dd>
          </div>
          <div className="statusbar__item">
            <dt className="statusbar__label">V/S</dt>
            <dd className="statusbar__value">
              {formatVerticalSpeed(latest.vertical_speed_fpm)}
            </dd>
          </div>
        </dl>
      )}

      <div className="statusbar__right">
        {scenarioRun !== null && scenarioRun.status === 'running' && (
          <span className="statusbar__scenario-chip">
            <span className="statusbar__scenario-dot" aria-hidden="true" />
            {scenarioName}
          </span>
        )}
        {demoActive && <span className="statusbar__demo-chip">Demo data</span>}
        <button
          type="button"
          className="ghost-button"
          aria-pressed={demoFeed}
          onClick={() => dispatch(demoFeedToggled())}
        >
          Demo feed
        </button>
        <span className={`statusbar__link ${linkModifier}`.trim()}>
          <span className="statusbar__link-dot" aria-hidden="true" />
          {linkLabel}
        </span>
      </div>
    </footer>
  );
}
