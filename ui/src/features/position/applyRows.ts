/**
 * Derives the right rail's "Will be applied" rows from the design slice and the sample
 * data. Pure — no store access, no JSX.
 */

import {
  AIRWORK_LEVEL_FEET,
  RUNWAYS,
  type IlsInfo,
} from './sampleData';
import { formatAltitudeFt, formatHeadingM, formatIlsFrequency, formatSpeedKt } from './format';
import { CIRCUIT_MARKERS, markerHeading } from './markers';
import type { PositionDesignState } from './positionDesignSlice';

export interface ApplyRow {
  readonly label: string;
  readonly value: string;
  readonly colour: 'default' | 'caution';
  readonly tag: string;
}

/** The name shown for "Start position": the stand id, or the active tab's resolved name. */
export function resolveStartPositionName(state: PositionDesignState): string {
  if (state.selectedStand !== null) {
    return state.selectedStand;
  }
  switch (state.activeTab) {
    case 'approach':
      return CIRCUIT_MARKERS[state.selectedMarker].label;
    case 'sidstar':
      return state.procedureIdent;
    case 'airwork':
      return 'Overhead LFMN';
    case 'custom':
      return state.custom.origin === 'runway-relative'
        ? 'Relative to threshold'
        : 'Coordinates';
  }
}

/** The runway course to fall back on when a mode needs one and none is explicit. */
function fallbackCourseDeg(state: PositionDesignState): number {
  const runway = state.selectedRunway !== null ? RUNWAYS[state.selectedRunway] : null;
  return runway !== null && runway.kind === 'runway' ? runway.courseDeg : 0;
}

/** The altitude (ft) the current mode resolves to, ignoring any override. */
export function resolveAltitudeFt(state: PositionDesignState): number {
  if (state.selectedStand !== null) {
    const runway = state.selectedRunway !== null ? RUNWAYS[state.selectedRunway] : RUNWAYS['04R'];
    return runway.elevationFt;
  }
  switch (state.activeTab) {
    case 'approach':
      return CIRCUIT_MARKERS[state.selectedMarker].altFt;
    case 'sidstar':
      return RUNWAYS['04R'].elevationFt;
    case 'airwork':
      return AIRWORK_LEVEL_FEET[state.airworkLevel];
    case 'custom':
      return state.custom.altitudeFt;
  }
}

/** The heading (°M) the current mode resolves to. */
export function resolveHeadingDeg(state: PositionDesignState): number {
  if (state.selectedStand !== null) {
    return 0;
  }
  switch (state.activeTab) {
    case 'approach':
      return markerHeading(state.selectedMarker, fallbackCourseDeg(state));
    case 'sidstar':
      return fallbackCourseDeg(state);
    case 'airwork':
      return fallbackCourseDeg(state);
    case 'custom':
      return state.custom.headingDeg;
  }
}

function runwayIls(state: PositionDesignState): IlsInfo | null {
  if (state.selectedRunway === null) {
    return null;
  }
  const runway = RUNWAYS[state.selectedRunway];
  return runway.kind === 'runway' ? runway.ils : null;
}

/** The 7 right-rail rows, in the fixed order the design doc specifies. */
export function applyRows(state: PositionDesignState): readonly ApplyRow[] {
  const altitudeFt = state.config.altitudeOverride
    ? state.config.altitudeOverrideFt
    : resolveAltitudeFt(state);
  const ils = runwayIls(state);
  const courseText =
    state.selectedRunway !== null
      ? String(fallbackCourseDeg(state)).padStart(3, '0')
      : '000';

  let navRadiosValue: string;
  let navRadiosTag: string;
  let navRadiosColour: ApplyRow['colour'];
  if (ils === null) {
    navRadiosValue = 'not available';
    navRadiosTag = 'unavailable';
    navRadiosColour = 'caution';
  } else if (!state.send.ilsFrequency) {
    navRadiosValue = 'not sent';
    navRadiosTag = 'from navdata';
    navRadiosColour = 'default';
  } else {
    navRadiosValue = `ILS ${formatIlsFrequency(ils.frequencyKhz)} · CRS ${courseText}`;
    navRadiosTag = 'from navdata';
    navRadiosColour = 'default';
  }

  return [
    {
      label: 'Start position',
      value: resolveStartPositionName(state),
      colour: 'default',
      tag: 'navdata',
    },
    {
      label: 'Altitude',
      value: formatAltitudeFt(altitudeFt),
      colour: state.config.altitudeOverride ? 'caution' : 'default',
      tag: state.config.altitudeOverride ? 'overridden' : 'computed',
    },
    {
      label: 'Heading',
      value: formatHeadingM(resolveHeadingDeg(state)),
      colour: 'default',
      tag: 'computed',
    },
    {
      label: 'IAS',
      value: formatSpeedKt(state.config.iasKt),
      colour: 'default',
      tag: 'editable',
    },
    {
      label: 'Landing gear',
      value: state.config.gearDown ? 'down' : 'up',
      colour: state.config.gearDown ? 'default' : 'caution',
      tag: 'editable',
    },
    {
      label: 'Flaps',
      value: state.config.flapsOn ? `${String(state.config.flapsPercent)} %` : 'unchanged',
      colour: 'default',
      tag: 'editable',
    },
    {
      label: 'Nav radios',
      value: navRadiosValue,
      colour: navRadiosColour,
      tag: navRadiosTag,
    },
  ];
}
