/**
 * The approach-type sub-filter of the SID & STAR tab.
 *
 * The server already classifies every approach (`ProcedureSummary.approach_type`, decoded
 * from the ARINC 424 route type by the navdata provider); nothing here reads an ident's
 * leading letter. The filter is client-side on purpose: the chip row is **derived from the
 * data** — only the types this airport actually publishes are offered — which needs the
 * unfiltered list anyway, so a server-side `approach_type` query parameter would buy nothing.
 *
 * `approach_type` is nullable on the wire (a SID has none; a record the provider could not
 * classify carries `"unknown"`). On an approach a missing value is folded onto `"unknown"`
 * so it still lands under a chip rather than vanishing from every filter.
 */

import type { ApproachType, ProcedureSummary } from '../../api/models';
import type { ApproachFilter, ProcedureFamily } from './positionDesignSlice';

/** Display order — the ones an instructor asks for first come first. */
export const APPROACH_TYPE_ORDER = [
  'ils',
  'loc',
  'rnav',
  'gps',
  'vor',
  'vor_dme',
  'ndb',
  'ndb_dme',
  'lda',
  'sdf',
  'gls',
  'mls',
  'igs',
  'unknown',
] as const satisfies readonly ApproachType[];

/** `Record` so adding a type to the server's vocabulary fails the typecheck here. */
export const APPROACH_TYPE_LABEL: Record<ApproachType, string> = {
  ils: 'ILS',
  loc: 'LOC',
  rnav: 'RNAV/RNP',
  gps: 'GPS',
  vor: 'VOR',
  vor_dme: 'VOR/DME',
  ndb: 'NDB',
  ndb_dme: 'NDB/DME',
  lda: 'LDA',
  sdf: 'SDF',
  gls: 'GLS',
  mls: 'MLS',
  igs: 'IGS',
  unknown: 'Other',
};

/** Whether the chip row applies at all: only the two approach families carry a type. */
export function familyHasApproachType(family: ProcedureFamily): boolean {
  return family === 'apptr' || family === 'final';
}

/** What `approachTypeOf` needs from a summary. */
export interface TypedSummary {
  readonly kind: ProcedureSummary['kind'];
  readonly ident: string;
  readonly transition?: string | null;
  readonly approach_type?: ApproachType | null;
}

/**
 * The type of each approach's **common route**, by ident.
 *
 * ARINC 424 gives a named approach transition its own route type (`A`), so the provider
 * honestly reports its type as `"unknown"` — but the transition to `I32L` is still part of
 * an ILS, and an instructor filtering on ILS expects to find it. The common route carries
 * the real type; transitions inherit it through this map.
 */
export function commonApproachTypes(
  summaries: readonly TypedSummary[],
): ReadonlyMap<string, ApproachType> {
  const types = new Map<string, ApproachType>();
  for (const summary of summaries) {
    const type = summary.approach_type ?? null;
    if (
      summary.kind === 'approach' &&
      (summary.transition == null || summary.transition === '') &&
      type !== null &&
      type !== 'unknown'
    ) {
      types.set(summary.ident, type);
    }
  }
  return types;
}

/**
 * An approach's type as the filter sees it — `null` on anything that is not an approach.
 * A missing or `"unknown"` type falls back to the same ident's common route, then to
 * `"unknown"` so the procedure still lands under a chip rather than vanishing.
 */
export function approachTypeOf(
  summary: TypedSummary,
  commonTypes?: ReadonlyMap<string, ApproachType>,
): ApproachType | null {
  if (summary.kind !== 'approach') {
    return null;
  }
  const own = summary.approach_type ?? null;
  if (own !== null && own !== 'unknown') {
    return own;
  }
  return commonTypes?.get(summary.ident) ?? 'unknown';
}

/** Whether a procedure passes the type filter. SIDs and STARs always do. */
export function approachTypeMatches(
  family: ProcedureFamily,
  wanted: ApproachFilter,
  summary: TypedSummary,
  commonTypes?: ReadonlyMap<string, ApproachType>,
): boolean {
  if (!familyHasApproachType(family) || wanted === 'all') {
    return true;
  }
  return approachTypeOf(summary, commonTypes) === wanted;
}

/** The distinct types among these procedures, in display order, with how many of each. */
export function approachTypesIn(
  summaries: readonly TypedSummary[],
  commonTypes?: ReadonlyMap<string, ApproachType>,
): readonly { readonly type: ApproachType; readonly count: number }[] {
  const counts = new Map<ApproachType, number>();
  for (const summary of summaries) {
    const type = approachTypeOf(summary, commonTypes);
    if (type !== null) {
      counts.set(type, (counts.get(type) ?? 0) + 1);
    }
  }
  return APPROACH_TYPE_ORDER.filter((type) => counts.has(type)).map((type) => ({
    type,
    count: counts.get(type) ?? 0,
  }));
}
