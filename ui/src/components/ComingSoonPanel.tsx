/**
 * Stand-in body for a module whose panel has not landed yet. Only the shell renders
 * it, and only while this branch is being built out — a registered tab with no `load`
 * in `tabs.ts` gets this instead of a blank screen.
 */
export function ComingSoonPanel({ label }: { label: string }) {
  return (
    <section className="panel" aria-label={label}>
      <h2>{label}</h2>
      <p className="panel__empty">
        This module is being built — its panel lands on this branch shortly.
      </p>
    </section>
  );
}
