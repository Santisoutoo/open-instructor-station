/**
 * The ten debrief numbers, each coloured by its grade. Colour is never the only
 * signal — the value itself is the information and the grade is also exposed to
 * assistive tech through the data attribute's styling plus the visible dot.
 */

import { REPORT_METRICS } from './format';
import { gradeReport } from './grade';
import type { LandingReport } from './types.mock';

export function LandingReportCard({ report }: { report: LandingReport }) {
  const grades = gradeReport(report);
  return (
    <dl className="landing-report">
      {REPORT_METRICS.map(({ key, label, format }) => (
        <div key={key} className="landing-report__item" data-grade={grades[key]}>
          <dt className="landing-report__label">{label}</dt>
          <dd className="landing-report__value">
            <span className="landing-report__dot" aria-hidden="true" />
            {format(report[key])}
          </dd>
        </div>
      ))}
    </dl>
  );
}
