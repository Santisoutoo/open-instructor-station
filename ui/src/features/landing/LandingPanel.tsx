/**
 * The Landing Analysis panel: pick one of the recorded demo landings, read the
 * trace small-multiples and the deviation picture, get the ten graded numbers, and
 * take the debrief home as JSON or CSV. PDF is stated as not-yet, never hidden.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { DeviationChart } from './DeviationChart';
import { downloadText, landingToCsv, landingToJson } from './export';
import { useGetLandingsQuery } from './landingApi';
import { LandingReportCard } from './LandingReportCard';
import { landingSelected } from './landingSlice';
import { TraceChart } from './TraceChart';
import './landing.css';

export function LandingPanel() {
  const dispatch = useAppDispatch();
  const selectedId = useAppSelector((state) => state.landing.selectedId);
  const { data: landings, isLoading } = useGetLandingsQuery();

  const landing =
    landings === undefined
      ? undefined
      : (landings.find(({ id }) => id === selectedId) ?? landings[0]);

  return (
    <section className="panel landing-panel" aria-labelledby="landing-heading">
      <h2 id="landing-heading">Landing analysis</h2>

      {isLoading && <p className="landing-panel__loading">Loading recorded landings…</p>}

      {landings !== undefined && landing !== undefined && (
        <>
          <div className="landing-picker" role="group" aria-label="Recorded landings">
            {landings.map(({ id, label, description }) => (
              <button
                key={id}
                type="button"
                className="landing-picker__card"
                aria-pressed={id === landing.id}
                onClick={() => {
                  dispatch(landingSelected(id));
                }}
              >
                <span className="landing-picker__label">{label}</span>
                <span className="landing-picker__desc">{description}</span>
              </button>
            ))}
          </div>

          <p className="landing-meta">
            {landing.runway} ·{' '}
            <time dateTime={landing.recorded_at}>
              {landing.recorded_at.replace('T', ' ').replace('Z', ' UTC')}
            </time>{' '}
            · demo recording
          </p>

          <div className="landing-charts">
            <TraceChart
              title="IAS"
              unit="kt"
              samples={landing.samples}
              y={(s) => s.ias_kt}
              touchdownIndex={landing.touchdownIndex}
            />
            <TraceChart
              title="Altitude"
              unit="ft AGL"
              samples={landing.samples}
              y={(s) => s.altitude_agl_ft}
              touchdownIndex={landing.touchdownIndex}
            />
            <TraceChart
              title="Vertical speed"
              unit="fpm"
              samples={landing.samples}
              y={(s) => s.vs_fpm}
              touchdownIndex={landing.touchdownIndex}
            />
            <TraceChart
              title="Pitch"
              unit="deg"
              samples={landing.samples}
              y={(s) => s.pitch_deg}
              y2={(s) => s.roll_deg}
              y2Label="roll"
              touchdownIndex={landing.touchdownIndex}
            />
          </div>

          <DeviationChart
            samples={landing.samples}
            touchdownIndex={landing.touchdownIndex}
          />

          <LandingReportCard report={landing.report} />

          <div className="landing-export" role="group" aria-label="Export debrief">
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                downloadText(
                  `landing-${landing.id}.json`,
                  landingToJson(landing),
                  'application/json',
                );
              }}
            >
              Export JSON
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                downloadText(`landing-${landing.id}.csv`, landingToCsv(landing), 'text/csv');
              }}
            >
              Export CSV
            </button>
            <button type="button" className="ghost-button" disabled>
              Export PDF
            </button>
            <span className="landing-export__note">
              PDF report arrives with the backend integration.
            </span>
          </div>
        </>
      )}
    </section>
  );
}
