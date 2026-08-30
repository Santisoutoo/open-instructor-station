import { describe, expect, it } from 'vitest';
import type { ApproachType } from '../../api/models';
import {
  APPROACH_TYPE_LABEL,
  APPROACH_TYPE_ORDER,
  approachTypeMatches,
  approachTypeOf,
  approachTypesIn,
  commonApproachTypes,
  familyHasApproachType,
} from './approachTypes';

/** Compile-time exhaustiveness: a type the server adds must be ordered and labelled here. */
const EVERY_TYPE: Record<ApproachType, true> = {
  ils: true,
  loc: true,
  rnav: true,
  gps: true,
  vor: true,
  vor_dme: true,
  ndb: true,
  ndb_dme: true,
  lda: true,
  sdf: true,
  gls: true,
  mls: true,
  igs: true,
  unknown: true,
};

const ils = { kind: 'approach', ident: 'I04R', approach_type: 'ils' } as const;
const rnav = { kind: 'approach', ident: 'R04R', approach_type: 'rnav' } as const;
const unclassified = { kind: 'approach', ident: 'X04R', approach_type: null } as const;
const sid = { kind: 'sid', ident: 'BADO8A', approach_type: null } as const;
/** What the provider really publishes for a named transition: route type `A` → unknown. */
const ilsTransition = {
  kind: 'approach',
  ident: 'I04R',
  transition: 'MUS',
  approach_type: 'unknown',
} as const;

describe('the vocabulary', () => {
  it('orders and labels every type the server can publish, once', () => {
    const all = Object.keys(EVERY_TYPE) as ApproachType[];
    expect([...APPROACH_TYPE_ORDER].sort()).toEqual([...all].sort());
    expect(new Set(APPROACH_TYPE_ORDER).size).toBe(APPROACH_TYPE_ORDER.length);
    for (const type of all) {
      expect(APPROACH_TYPE_LABEL[type]).not.toBe('');
    }
  });

  it('only the two approach families carry a type', () => {
    expect(familyHasApproachType('apptr')).toBe(true);
    expect(familyHasApproachType('final')).toBe(true);
    expect(familyHasApproachType('sid')).toBe(false);
    expect(familyHasApproachType('star')).toBe(false);
  });
});

describe('approachTypeOf', () => {
  it('folds an unclassified approach onto "unknown" so it still lands under a chip', () => {
    expect(approachTypeOf(unclassified)).toBe('unknown');
  });

  it('is null for anything that is not an approach', () => {
    expect(approachTypeOf(sid)).toBeNull();
  });

  it('a transition inherits its common route’s type — its own says only ‘transition’', () => {
    const commonTypes = commonApproachTypes([ils, rnav, ilsTransition, sid]);
    expect(approachTypeOf(ilsTransition, commonTypes)).toBe('ils');
    expect(approachTypeOf(ilsTransition)).toBe('unknown');
  });

  it('a summary’s own real type always wins over the lookup', () => {
    const commonTypes = new Map([['R04R', 'ils'] as const]);
    expect(approachTypeOf(rnav, commonTypes)).toBe('rnav');
  });
});

describe('commonApproachTypes', () => {
  it('maps only common routes with a real type', () => {
    const commonTypes = commonApproachTypes([ils, unclassified, ilsTransition, sid]);
    expect(commonTypes.get('I04R')).toBe('ils');
    expect(commonTypes.has('X04R')).toBe(false);
    expect(commonTypes.has('BADO8A')).toBe(false);
  });
});

describe('approachTypeMatches', () => {
  it('passes everything under "all"', () => {
    expect(approachTypeMatches('final', 'all', ils)).toBe(true);
    expect(approachTypeMatches('final', 'all', unclassified)).toBe(true);
  });

  it('narrows to the wanted type, treating null as "unknown"', () => {
    expect(approachTypeMatches('final', 'ils', ils)).toBe(true);
    expect(approachTypeMatches('final', 'ils', rnav)).toBe(false);
    expect(approachTypeMatches('apptr', 'unknown', unclassified)).toBe(true);
    expect(approachTypeMatches('apptr', 'ils', unclassified)).toBe(false);
  });

  it('finds an ILS transition under the ILS chip through the inherited type', () => {
    const commonTypes = commonApproachTypes([ils, ilsTransition]);
    expect(approachTypeMatches('apptr', 'ils', ilsTransition, commonTypes)).toBe(true);
  });

  it('ignores the filter entirely on SIDs and STARs', () => {
    expect(approachTypeMatches('sid', 'ils', sid)).toBe(true);
    expect(approachTypeMatches('star', 'vor', sid)).toBe(true);
  });
});

describe('approachTypesIn', () => {
  it('lists the distinct types present, counted, in display order', () => {
    expect(approachTypesIn([rnav, unclassified, ils, ils, sid])).toEqual([
      { type: 'ils', count: 2 },
      { type: 'rnav', count: 1 },
      { type: 'unknown', count: 1 },
    ]);
  });

  it('is empty when nothing is an approach', () => {
    expect(approachTypesIn([sid])).toEqual([]);
  });
});
