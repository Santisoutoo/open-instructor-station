/** Shared `label | mono value | optional tag` row, used by the 4 mode tabs and the rail. */
export function FactRow({
  label,
  value,
  caution = false,
  accent = false,
  tag,
}: {
  readonly label: string;
  readonly value: string;
  readonly caution?: boolean;
  readonly accent?: boolean;
  readonly tag?: string;
}) {
  const valueClassName = [
    'pos-factrow__value',
    'pos-mono',
    caution ? 'pos-factrow__value--caution' : '',
    accent ? 'pos-factrow__value--accent' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className="pos-factrow">
      <span className="pos-factrow__label">{label}</span>
      <span className={valueClassName}>{value}</span>
      {tag !== undefined && <span className="pos-factrow__tag">{tag}</span>}
    </div>
  );
}
