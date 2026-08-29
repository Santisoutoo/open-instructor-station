/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * The airport overlay (runway polygons, ILS feathers, navaid points) will come from
 * the server's navdata endpoints once the map backend exists — read from the user's
 * own simulator install, never redistributed. Until then the panel renders the
 * hand-written fixture in `mock.ts`, and these types describe only that fixture.
 */

import type { FeatureCollection, LineString, Point, Polygon } from 'geojson';

export interface RunwayProperties {
  /** Runway ident of the lower-numbered end, e.g. `"32L"`. */
  ident: string;
}

export interface IlsProperties {
  /** The runway end the feather serves, e.g. `"32L"`. */
  ident: string;
}

export type NavaidKind = 'vor' | 'ndb' | 'dme';

export interface NavaidProperties {
  ident: string;
  kind: NavaidKind;
}

/** Everything the map draws for the one demo airport, already in GeoJSON. */
export interface AirportOverlay {
  /** Display name of the fixture field. */
  name: string;
  runways: FeatureCollection<Polygon, RunwayProperties>;
  ils: FeatureCollection<LineString, IlsProperties>;
  navaids: FeatureCollection<Point, NavaidProperties>;
}
