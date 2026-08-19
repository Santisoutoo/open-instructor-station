import { applyRows } from './applyRows';
import { checks } from './checks';
import { NAVDATA_FOOTER, SAMPLE_METAR } from './sampleData';
import { useAppSelector } from '../../store';

export function ApplyRail() {
  const design = useAppSelector((state) => state.positionDesign);
  const rows = applyRows(design);
  const checkList = checks(design);

  return (
    <aside className="pos-rail" aria-label="Will be applied">
      <div className="pos-rail__head">
        <h2 className="pos-rail__title">Will be applied</h2>
        <span className="pos-tag">sample data</span>
      </div>

      <ul className="pos-rail__rows">
        {rows.map((row) => (
          <li key={row.label} className="pos-rail__row">
            <span className="pos-rail__row-label">{row.label}</span>
            <span
              className={
                row.colour === 'caution'
                  ? 'pos-mono pos-rail__row-value pos-rail__row-value--caution'
                  : 'pos-mono pos-rail__row-value'
              }
            >
              {row.value}
            </span>
            <span
              className={
                row.colour === 'caution'
                  ? 'pos-rail__row-tag pos-rail__row-tag--caution'
                  : 'pos-rail__row-tag'
              }
            >
              {row.tag}
            </span>
          </li>
        ))}
      </ul>

      <div className="pos-rail__checks">
        <h3 className="pos-rail__checks-title">Checks</h3>
        <ul className="pos-rail__checks-list">
          {checkList.map((check, index) => (
            <li key={`${check.text}-${String(index)}`} className="pos-rail__check">
              <span className={`pos-dot pos-dot--${check.dot}`} aria-hidden="true" />
              <div className="pos-rail__check-body">
                <p className="pos-rail__check-text">{check.text}</p>
                <p className="pos-rail__check-note">{check.note}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="pos-rail__footer">
        <p className="pos-mono pos-rail__metar">{SAMPLE_METAR}</p>
        <p className="pos-rail__footer-note">{NAVDATA_FOOTER}</p>
      </div>
    </aside>
  );
}
