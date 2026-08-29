/**
 * From what the instructor picked on screen to the `PlacementRequest` the server resolves.
 *
 * **The diagram's `(u, v)` marker coordinates never leave the diagram.** They are a
 * schematic picture at a fixed 40 px/NM, drawn so an instructor can point at where the
 * aeroplane should be; the along-track position on the real earth is the server's, computed
 * by `core.geodesy` from the runway's own threshold and bearing. What crosses the wire is a
 * *name* — `left_downwind`, `final_10nm` — plus the circuit's dimensions.
 *
 * ## The marker table
 *
 * | marker | request |
 * |---|---|
 * | `takeoff` | `runway_threshold` |
 * | `final-3nm`, `final-8nm` | `runway`, the tab's selected `final_*` / `short_final` |
 * | `downwind-left` / `-right` | `runway`, `left_downwind` / `right_downwind`, width 4 NM |
 * | `base-left` / `-right` | `runway`, `left_base` / `right_base`, width 4 NM, leg 6 NM |
 * | `vectors-left` / `-right` | `runway`, `left_base` / `right_base`, width 2 NM, leg 6 NM |
 *
 * **The vectors rows are not an approximation, and are not to be "fixed".**
 * `core.geodesy.traffic_pattern_point` puts a base leg at `along = -leg_distance_nm`,
 * `across = side × pattern_width_nm`, facing `axis + 90°` in a left-hand circuit. Feed it
 * 6 NM and 2 NM and it returns exactly the mockup's vectors position: 6 NM out on the
 * approach side, 2 NM off the centreline, on an intercept heading. The only thing a
 * dedicated "vectors" placement would add server-side is a different label.
 *
 * Speed, gear and flaps are deliberately absent from every request here. They are the
 * preview's business (`Placement.to_setup()` resolves them from the placement's profile and
 * the aircraft's approach category), and the instructor's edits ride on `ApplyPlacementRequest.setup`
 * instead — which is what keeps the preview cache key stable while they tune a number.
 */

import type { GeoPosition, PlacementRequest, ProcedureKind } from '../../api/models';
import type { FinalPlacementName } from './finals';
import { isDownwindMarker } from './markers';
import type { DesignTabId, MarkerId } from './positionDesignSlice';

/** The circuit geometry a marker asks the server for. */
export interface CircuitPlacement {
  readonly placement: 'left_downwind' | 'right_downwind' | 'left_base' | 'right_base';
  readonly patternWidthNm: number;
  readonly legDistanceNm: number | null;
}

/**
 * The six circuit markers. `takeoff` and the two finals are handled separately: one is a
 * ground placement, the others are driven by the final-distance selector.
 */
export const CIRCUIT_PLACEMENTS: Record<
  Exclude<MarkerId, 'takeoff' | 'final-3nm' | 'final-8nm'>,
  CircuitPlacement
> = {
  'downwind-left': {
    placement: 'left_downwind',
    patternWidthNm: 4,
    legDistanceNm: null,
  },
  'downwind-right': {
    placement: 'right_downwind',
    patternWidthNm: 4,
    legDistanceNm: null,
  },
  'base-left': { placement: 'left_base', patternWidthNm: 4, legDistanceNm: 6 },
  'base-right': { placement: 'right_base', patternWidthNm: 4, legDistanceNm: 6 },
  // 6 NM out, 2 NM off the centreline, intercept heading — see the module docstring.
  'vectors-left': { placement: 'left_base', patternWidthNm: 2, legDistanceNm: 6 },
  'vectors-right': { placement: 'right_base', patternWidthNm: 2, legDistanceNm: 6 },
};

/** Everything the screen knows that a request can be built from. */
export interface PlacementInputs {
  readonly icao: string;
  readonly runwayIdent: string | null;
  readonly standName: string | null;
  readonly activeTab: DesignTabId;
  readonly marker: MarkerId;
  readonly finalPlacement: FinalPlacementName;
  /**
   * The instructor's edit to the selected marker's own NM distance — abeam offset for a
   * downwind marker, leg distance for base/vectors — or `null` for `CIRCUIT_PLACEMENTS`'
   * own default. Ignored for `takeoff` and the two finals, which are not editable this way.
   */
  readonly markerDistanceOverrideNm: number | null;
  readonly procedure: {
    readonly kind: ProcedureKind;
    readonly ident: string;
    readonly transition: string | null;
    readonly sequence: number | null;
  } | null;
  /** Where "Overhead {ICAO}" is, and how high — the Airwork tab. */
  readonly airwork: {
    readonly position: GeoPosition;
    readonly headingDeg: number;
  } | null;
  readonly custom: {
    readonly position: GeoPosition;
    readonly headingDeg: number | null;
  } | null;
}

/**
 * The placement the current screen state means, or `null` when it does not yet mean one.
 *
 * `null` is an ordinary outcome, not an error: no airport loaded, no runway picked, no
 * procedure leg chosen. The rail says what is missing; nothing is staged and the commit
 * button is dead.
 *
 * **A selected stand wins over everything.** Picking a stand is picking a ground position,
 * and the circuit marker or procedure leg still highlighted behind it is not where the
 * aeroplane is going — the rail's checks say so in words too.
 *
 * **The Custom location tab needs no airport.** A latitude and a longitude are a whole
 * `CoordinatePlacementRequest`, and the Map's "Send to Position tab" hand-off arrives as
 * exactly that — often nowhere near a field. Every other placement is named relative to an
 * airport and cannot resolve without one.
 */
export function buildPlacementRequest(inputs: PlacementInputs): PlacementRequest | null {
  if (inputs.standName !== null) {
    return inputs.icao === ''
      ? null
      : {
          type: 'parking',
          airport_icao: inputs.icao,
          stand_name: inputs.standName,
        };
  }

  if (inputs.activeTab === 'custom') {
    if (inputs.custom === null) {
      return null;
    }
    return {
      type: 'coordinate',
      position: inputs.custom.position,
      heading_deg: inputs.custom.headingDeg,
    };
  }

  if (inputs.icao === '') {
    return null;
  }

  switch (inputs.activeTab) {
    case 'approach':
      return runwayRequest(inputs);
    case 'sidstar': {
      const procedure = inputs.procedure;
      if (procedure === null || procedure.sequence === null) {
        return null;
      }
      return {
        type: 'procedure_leg',
        airport_icao: inputs.icao,
        kind: procedure.kind,
        ident: procedure.ident,
        transition: procedure.transition,
        sequence: procedure.sequence,
      };
    }
    case 'airwork': {
      if (inputs.airwork === null) {
        return null;
      }
      return {
        type: 'coordinate',
        position: inputs.airwork.position,
        heading_deg: inputs.airwork.headingDeg,
      };
    }
  }
}

/** The Approach tab: a runway-relative placement, which needs a runway end. */
function runwayRequest(inputs: PlacementInputs): PlacementRequest | null {
  const runwayIdent = inputs.runwayIdent;
  if (runwayIdent === null) {
    return null;
  }
  if (inputs.marker === 'takeoff') {
    return {
      type: 'runway_threshold',
      airport_icao: inputs.icao,
      runway_ident: runwayIdent,
    };
  }
  if (inputs.marker === 'final-3nm' || inputs.marker === 'final-8nm') {
    return {
      type: 'runway',
      airport_icao: inputs.icao,
      runway_ident: runwayIdent,
      placement: inputs.finalPlacement,
    };
  }
  const circuit = CIRCUIT_PLACEMENTS[inputs.marker];
  const override = inputs.markerDistanceOverrideNm;
  // Downwind's editable number is the abeam offset (`pattern_width_nm`); base/vectors'
  // is the leg distance (`leg_distance_nm`) — `pattern_width_nm` stays the fixed circuit
  // width for those two. See the module docstring's marker table.
  const patternWidthNm =
    isDownwindMarker(inputs.marker) && override !== null ? override : circuit.patternWidthNm;
  const legDistanceNm =
    !isDownwindMarker(inputs.marker) && override !== null ? override : circuit.legDistanceNm;
  return {
    type: 'runway',
    airport_icao: inputs.icao,
    runway_ident: runwayIdent,
    placement: circuit.placement,
    pattern_width_nm: patternWidthNm,
    ...(legDistanceNm === null ? {} : { leg_distance_nm: legDistanceNm }),
  };
}
