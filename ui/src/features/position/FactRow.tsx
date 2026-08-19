/**
 * Shared `label | mono value` row, used by the four mode tabs and the runway strip.
 *
 * Not by the right rail: `ApplyRail` renders its own rows, because those carry a provenance
 * tag and a three-way colour this row has no business knowing about.
 */
export function FactRow({
  label,
  value,
  caution = false,
}: {
  readonly label: string;
  readonly value: string;
  readonly caution?: boolean;
}) {
  return (
    <div className="pos-factrow">
      <span className="pos-factrow__label">{label}</span>
      <span
        className={
          caution
            ? 'pos-factrow__value pos-mono pos-factrow__value--caution'
            : 'pos-factrow__value pos-mono'
        }
      >
        {value}
      </span>
    </div>
  );
}
