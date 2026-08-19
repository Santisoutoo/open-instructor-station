/**
 * Frozen sample data for the Position screen v3 replica — LFMN (Nice / Côte d'Azur).
 *
 * Everything here is static and visibly tagged "sample data" in the right rail: this phase
 * is not wired to the real navdata/weather APIs (see the design doc's "Scope" section). No
 * React, no store access — a plain data module.
 */

import type { AirworkLevel, ParkingFilter, RunwayId } from './positionDesignSlice';

export const AIRPORT_ICAO = 'LFMN';
export const AIRPORT_NAME = "Nice / Côte d'Azur";
/** Decimal-degree centre used for the Airwork tab's "Overhead LFMN" fact and the CTR check. */
export const AIRPORT_LATITUDE = 43.6584;
export const AIRPORT_LONGITUDE = 7.2159;
/** The pre-formatted `43°39′N 007°12′E` shown on the Airwork tab's Position fact. */
export const AIRPORT_POSITION_LABEL = "43°39′N 007°12′E";

export interface IlsInfo {
  /** Kilohertz, so `formatIlsFrequency` (which expects kHz) needs no conversion. */
  readonly frequencyKhz: number;
}

export interface RunwayFacts {
  readonly kind: 'runway';
  readonly courseDeg: number;
  readonly lengthFt: number;
  readonly surface: string;
  readonly elevationFt: number;
  readonly ils: IlsInfo | null;
}

export interface HelipadFacts {
  readonly kind: 'helipad';
  readonly elevationFt: number;
  readonly type: string;
}

export type RunwayEntry = RunwayFacts | HelipadFacts;

/**
 * `Record<RunwayId, …>` rather than an array or a loose `Record<string, …>`, so
 * `noUncheckedIndexedAccess` does not force `| undefined` on every lookup by the finite
 * `RunwayId` union (per the design doc's type-strictness notes).
 */
export const RUNWAYS: Record<RunwayId, RunwayEntry> = {
  '04R': {
    kind: 'runway',
    courseDeg: 40,
    lengthFt: 9710,
    surface: 'Asphalt',
    elevationFt: 12,
    ils: { frequencyKhz: 110700 },
  },
  '22L': {
    kind: 'runway',
    courseDeg: 220,
    lengthFt: 9710,
    surface: 'Asphalt',
    elevationFt: 12,
    ils: null,
  },
  '04L': {
    kind: 'runway',
    courseDeg: 40,
    lengthFt: 9710,
    surface: 'Asphalt',
    elevationFt: 12,
    ils: { frequencyKhz: 110700 },
  },
  '22R': {
    kind: 'runway',
    courseDeg: 220,
    lengthFt: 9710,
    surface: 'Asphalt',
    elevationFt: 12,
    ils: null,
  },
  HELI: { kind: 'helipad', elevationFt: 12, type: 'Helipad' },
};

/**
 * The reciprocal end of each physical strip (04R/22L, 04L/22R). `Partial` on purpose: the
 * helipad has no reciprocal, and a check that needs one must be able to see that it doesn't.
 */
export const RECIPROCAL_RUNWAY: Partial<Record<RunwayId, RunwayId>> = {
  '04R': '22L',
  '22L': '04R',
  '04L': '22R',
  '22R': '04L',
};

export const SAMPLE_WIND = { directionDeg: 240, speedKt: 12 } as const;
export const SAMPLE_QNH_HPA = 1013;

export type StandType = 'Gate heavy' | 'Gate medium' | 'Miscellaneous' | 'Tie-down';

export interface Stand {
  readonly id: string;
  readonly type: StandType;
  readonly x: number;
  readonly y: number;
}

/** The 16 stands, in the 340×262 airport diagram's coordinate space. */
export const STANDS: readonly Stand[] = [
  { id: 'A1', type: 'Gate heavy', x: 44, y: 104 },
  { id: 'A2', type: 'Gate heavy', x: 68, y: 104 },
  { id: 'A3', type: 'Gate heavy', x: 92, y: 104 },
  { id: 'A4', type: 'Gate medium', x: 116, y: 104 },
  { id: 'A5', type: 'Gate medium', x: 140, y: 104 },
  { id: 'A6', type: 'Gate medium', x: 164, y: 104 },
  { id: 'B1', type: 'Gate medium', x: 44, y: 176 },
  { id: 'B2', type: 'Gate medium', x: 68, y: 176 },
  { id: 'B3', type: 'Gate medium', x: 92, y: 176 },
  { id: 'B4', type: 'Gate medium', x: 116, y: 176 },
  { id: 'B5', type: 'Gate medium', x: 140, y: 176 },
  { id: 'T1', type: 'Tie-down', x: 44, y: 230 },
  { id: 'T2', type: 'Tie-down', x: 64, y: 230 },
  { id: 'T3', type: 'Tie-down', x: 84, y: 230 },
  { id: 'T4', type: 'Tie-down', x: 104, y: 230 },
  { id: 'M1', type: 'Miscellaneous', x: 196, y: 150 },
];

/** Whether a stand's type passes the sidebar's parking-type filter. */
export function standMatchesFilter(filter: ParkingFilter, type: StandType): boolean {
  switch (filter) {
    case 'all':
      return true;
    case 'gate-heavy':
      return type === 'Gate heavy';
    case 'gate-medium':
      return type === 'Gate medium';
    case 'misc':
      return type === 'Miscellaneous';
    case 'tie-down':
      return type === 'Tie-down';
  }
}

export interface ProcedureIdent {
  readonly ident: string;
  readonly via: string;
}

/** The 8 sample procedure idents shown in the SID & STAR ident dropdown. */
export const PROCEDURE_IDENTS: readonly ProcedureIdent[] = [
  { ident: 'BADO8A.04B.BADOD', via: 'BADOD' },
  { ident: 'BADO8C.04B.BADOD', via: 'BADOD' },
  { ident: 'BASI8A.04B.BASIP', via: 'BASIP' },
  { ident: 'BODR8A.04B.BODRU', via: 'BODRU' },
  { ident: 'EPOL8A.04B.EPOLO', via: 'EPOLO' },
  { ident: 'EPOL8B.04B.EPOLO', via: 'EPOLO' },
  { ident: 'IRMA8A.04B.IRMAR', via: 'IRMAR' },
  { ident: 'IRMA8C.04B.IRMAR', via: 'IRMAR' },
];

/** Splits `BADO8A.04B.BADOD` into its three breadcrumb parts. */
export function splitProcedureIdent(ident: string): {
  short: string;
  transition: string;
  waypoint: string;
} {
  const parts = ident.split('.');
  return {
    short: parts[0] ?? ident,
    transition: parts[1] ?? '',
    waypoint: parts[2] ?? '',
  };
}

/** `Record<AirworkLevel, …>` so every level in the closed set is covered. */
export const AIRWORK_LEVEL_FEET: Record<AirworkLevel, number> = {
  FL300: 30000,
  FL200: 20000,
  FL100: 10000,
  FL050: 5000,
};

/** The circuit-level tick bar's pixel width, one per level. */
export const AIRWORK_TICK_WIDTH_PX: Record<AirworkLevel, number> = {
  FL300: 58,
  FL200: 44,
  FL100: 30,
  FL050: 18,
};

export const SAMPLE_METAR = 'LFMN 171730Z 24012KT 9999 FEW035 26/18 Q1013 NOSIG';
export const NAVDATA_FOOTER = 'Navdata X-Plane 12 · AIRAC 2508 · METAR 6 min old';
