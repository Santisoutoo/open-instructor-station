/**
 * Gross weight vs MTOW, fuel total, and a small SVG CG-vs-envelope graphic.
 *
 * **Pure.** Props in, numbers and SVG out — the arithmetic already happened in
 * `core.fuel_payload.mass_and_balance` and arrived as `MassAndBalanceResult`; this
 * file only draws it. `limits` comes straight from `AirframeMassLimits.cg_envelope` —
 * no server-side schematic model needed, the envelope polygon *is* the wire data.
 *
 * `limits === null` means `limits_source === "unknown"`: there is nothing to draw, so
 * the graphic is skipped entirely rather than shown empty or guessed (§8.3.4, D7).
 */

import type { AirframeMassLimits, MassAndBalanceResult } from '../../api/models';

const GRAPHIC_WIDTH = 220;
const GRAPHIC_HEIGHT = 150;
const PADDING = 14;

interface MassAndBalanceReadoutProps {
  massAndBalance: MassAndBalanceResult;
  limits: AirframeMassLimits | null;
}

function CgGraphic({
  limits,
  massAndBalance,
}: {
  limits: AirframeMassLimits;
  massAndBalance: MassAndBalanceResult;
}) {
  const points = limits.cg_envelope.points;
  const weights = points.map((point) => point.weight_kg);
  const cgValues = points.flatMap((point) => [point.fwd_limit_in, point.aft_limit_in]);
  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);
  const minCg = Math.min(...cgValues);
  const maxCg = Math.max(...cgValues);

  const innerWidth = GRAPHIC_WIDTH - PADDING * 2;
  const innerHeight = GRAPHIC_HEIGHT - PADDING * 2;
  const weightSpan = maxWeight - minWeight || 1;
  const cgSpan = maxCg - minCg || 1;

  const x = (cgIn: number) => PADDING + ((cgIn - minCg) / cgSpan) * innerWidth;
  const y = (weightKg: number) =>
    PADDING + innerHeight - ((weightKg - minWeight) / weightSpan) * innerHeight;

  const fwdEdge = points.map(
    (point) => `${String(x(point.fwd_limit_in))},${String(y(point.weight_kg))}`,
  );
  const aftEdge = [...points]
    .reverse()
    .map((point) => `${String(x(point.aft_limit_in))},${String(y(point.weight_kg))}`);
  const polygon = [...fwdEdge, ...aftEdge].join(' ');

  const cgArm = massAndBalance.cg_arm_in;
  const dotClass =
    massAndBalance.within_envelope === false
      ? 'mb-graphic__dot mb-graphic__dot--violated'
      : 'mb-graphic__dot';

  return (
    <svg
      className="mb-graphic"
      viewBox={`0 0 ${String(GRAPHIC_WIDTH)} ${String(GRAPHIC_HEIGHT)}`}
      role="img"
      aria-label="Centre of gravity versus the published envelope"
    >
      <polygon className="mb-graphic__envelope" points={polygon} />
      {cgArm != null && (
        <circle
          className={dotClass}
          cx={x(cgArm)}
          cy={y(massAndBalance.gross_weight_kg)}
          r={5}
        />
      )}
    </svg>
  );
}

export function MassAndBalanceReadout({ massAndBalance, limits }: MassAndBalanceReadoutProps) {
  if (limits === null) {
    return (
      <div className="mb-readout mb-readout--unknown">
        <p className="mb-readout__unknown">
          Mass and balance cannot be verified for this airframe — no published or table CG
          envelope. Weights below are read from the simulator as reported.
        </p>
        <dl className="mb-readout__numbers">
          <div className="mb-readout__item">
            <dt>Fuel</dt>
            <dd>{Math.round(massAndBalance.fuel_kg)} kg</dd>
          </div>
          <div className="mb-readout__item">
            <dt>Payload</dt>
            <dd>{Math.round(massAndBalance.payload_kg)} kg</dd>
          </div>
        </dl>
      </div>
    );
  }

  const grossPct = Math.round(
    (massAndBalance.gross_weight_kg / limits.max_takeoff_weight_kg) * 100,
  );

  return (
    <div className="mb-readout">
      <dl className="mb-readout__numbers">
        <div className="mb-readout__item">
          <dt>Gross weight</dt>
          <dd>
            {Math.round(massAndBalance.gross_weight_kg)} / {Math.round(limits.max_takeoff_weight_kg)}{' '}
            kg <span className="mb-readout__pct">({grossPct}%)</span>
          </dd>
        </div>
        <div className="mb-readout__item">
          <dt>Fuel</dt>
          <dd>{Math.round(massAndBalance.fuel_kg)} kg</dd>
        </div>
        <div className="mb-readout__item">
          <dt>CG</dt>
          <dd>
            {massAndBalance.cg_arm_in == null
              ? 'unknown'
              : `${massAndBalance.cg_arm_in.toFixed(2)} in`}
          </dd>
        </div>
      </dl>
      <CgGraphic limits={limits} massAndBalance={massAndBalance} />
      {massAndBalance.within_envelope === false && (
        <p className="mb-readout__violation" role="alert">
          Outside the published CG envelope.
        </p>
      )}
    </div>
  );
}
