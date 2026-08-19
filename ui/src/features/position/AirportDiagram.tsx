/**
 * The 340×262 airport diagram in the Start-at popover: two runway strips, a taxiway line,
 * three terminal blocks, and one absolutely-positioned clickable square per stand.
 */

import { STANDS } from './sampleData';

const WIDTH = 340;
const HEIGHT = 262;

export function AirportDiagram({
  selectedStand,
  onSelect,
}: {
  readonly selectedStand: string | null;
  readonly onSelect: (id: string) => void;
}) {
  return (
    <div className="pos-diagram" style={{ width: WIDTH, height: HEIGHT }}>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        width={WIDTH}
        height={HEIGHT}
        className="pos-diagram__svg"
        role="img"
        aria-label="Airport diagram"
      >
        <rect x={24} y={86} width={150} height={36} className="pos-diagram__terminal" />
        <text x={99} y={107} textAnchor="middle" className="pos-diagram__terminal-label">
          Terminal 1
        </text>
        <rect x={24} y={158} width={130} height={36} className="pos-diagram__terminal" />
        <text x={89} y={179} textAnchor="middle" className="pos-diagram__terminal-label">
          Terminal 2
        </text>
        <rect
          x={178}
          y={130}
          width={44}
          height={40}
          className="pos-diagram__terminal pos-diagram__terminal--ga"
        />
        <text x={200} y={186} textAnchor="middle" className="pos-diagram__terminal-label">
          General aviation
        </text>

        <line x1={30} y1={230} x2={250} y2={230} className="pos-diagram__taxiway" />

        <rect x={260} y={16} width={16} height={226} className="pos-diagram__runway" />
        <rect x={286} y={16} width={16} height={226} className="pos-diagram__runway" />
        <text x={268} y={254} textAnchor="middle" className="pos-diagram__runway-label">
          04L
        </text>
        <text x={294} y={254} textAnchor="middle" className="pos-diagram__runway-label">
          04R
        </text>
      </svg>

      {STANDS.map((stand) => (
        <button
          key={stand.id}
          type="button"
          className={
            stand.id === selectedStand
              ? 'pos-diagram__stand pos-diagram__stand--selected'
              : 'pos-diagram__stand'
          }
          style={{ left: stand.x, top: stand.y }}
          aria-pressed={stand.id === selectedStand}
          aria-label={`Stand ${stand.id}`}
          onClick={() => {
            onSelect(stand.id);
          }}
        >
          <span className="pos-diagram__stand-dot" aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
