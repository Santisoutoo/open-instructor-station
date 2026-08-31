/**
 * The airport diagram in the Start-at popover: OpenStreetMap tiles under the airport's own
 * navdata — every runway strip between the two thresholds navdata publishes for it, and one
 * clickable square per parking stand at the stand's own coordinate — zoomable and pannable
 * the way the Instructor Map is (wheel, drag, the +/− control).
 *
 * The tiles are *context*, not data: the aprons and terminals they show come from OSM, the
 * stands the instructor can pick come from `apt.dat`, and only the latter are clickable.
 * Nothing computed here ever crosses the wire: clicking a square sends the stand's **name**,
 * and the server resolves the position.
 *
 * **Stands and runway labels are DOM, not MapLibre markers or symbol layers.** The style has
 * no glyph server (the app runs on a LAN — see `useMapLibre`), so a symbol layer could not
 * print "04R" at all; and a React `<button>` keeps the 44px tap target, the `aria-pressed`
 * state and the jsdom tests the SVG diagram had. The overlay is re-laid out through
 * `map.project` on every `move`. Until the map has loaded — and in jsdom, where it never
 * does — the same elements sit where `standProjection.ts` puts them, so the picker is usable
 * with no tiles at all.
 *
 * The runway strips are one GeoJSON line layer, because a strip is a *line on the ground*
 * and must stay glued to the tiles at every zoom; a DOM line would have to be re-measured.
 */

import type { FeatureCollection, LineString } from 'geojson';
import { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';
import { useEffect, useRef, useState } from 'react';
import type { ParkingStand, Runway } from '../../api/models';
import { useMapLibre } from '../map/useMapLibre';
import {
  DIAGRAM_HEIGHT,
  DIAGRAM_MARGIN,
  DIAGRAM_WIDTH,
  diagramBounds,
  extentOf,
  projectLatLon,
  runwayStrips,
  type DiagramPoint,
  type LatLon,
} from './standProjection';

const RUNWAY_SOURCE = 'pos-diagram-runways';

/** Closest the initial fit goes: one stand is not a whole airport, so do not zoom into it. */
const FIT_MAX_ZOOM = 16;

/** Re-render whenever the camera moves, so the DOM overlay follows the tiles. */
function useCameraTick(map: MapLibreMap | null): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (map === null) {
      return;
    }
    const bump = () => {
      setTick((value) => value + 1);
    };
    map.on('move', bump);
    map.on('resize', bump);
    return () => {
      map.off('move', bump);
      map.off('resize', bump);
    };
  }, [map]);
  return tick;
}

function runwayGeoJson(runways: readonly Runway[]): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: runwayStrips(runways).map((strip) => ({
      type: 'Feature',
      properties: { key: strip.key },
      geometry: {
        type: 'LineString',
        coordinates: [
          [strip.from.threshold.longitude, strip.from.threshold.latitude],
          [strip.to.threshold.longitude, strip.to.threshold.latitude],
        ],
      },
    })),
  };
}

export function AirportDiagram({
  stands,
  runways,
  selectedStand,
  onSelect,
}: {
  readonly stands: readonly ParkingStand[];
  readonly runways: readonly Runway[];
  readonly selectedStand: string | null;
  readonly onSelect: (name: string) => void;
}) {
  const points: readonly LatLon[] = [
    ...stands.map((stand) => stand.position),
    ...runways.map((runway) => runway.threshold),
  ];
  const extent = extentOf(points);

  const { containerRef, map } = useMapLibre({
    bounds: extent ?? undefined,
    fitPadding: DIAGRAM_MARGIN,
    fitMaxZoom: FIT_MAX_ZOOM,
    navigation: true,
    compactAttribution: true,
  });
  useCameraTick(map);

  // The stands arrive from their own query, often after the map was created around the
  // runways alone. Fit once more when the extent first becomes known — and only then, so a
  // camera the instructor has already moved is never yanked back.
  const fittedRef = useRef<string | null>(null);
  const extentKey = extent === null ? null : JSON.stringify(extent);
  useEffect(() => {
    if (map === null || extent === null || fittedRef.current === extentKey) {
      return;
    }
    if (fittedRef.current === null) {
      map.fitBounds(extent, {
        padding: DIAGRAM_MARGIN,
        maxZoom: FIT_MAX_ZOOM,
        duration: 0,
      });
    }
    fittedRef.current = extentKey;
  }, [map, extent, extentKey]);

  useEffect(() => {
    if (map === null) {
      return;
    }
    const data = runwayGeoJson(runways);
    const source = map.getSource(RUNWAY_SOURCE) as GeoJSONSource | undefined;
    if (source !== undefined) {
      source.setData(data);
      return;
    }
    map.addSource(RUNWAY_SOURCE, { type: 'geojson', data });
    map.addLayer({
      id: RUNWAY_SOURCE,
      type: 'line',
      source: RUNWAY_SOURCE,
      layout: { 'line-cap': 'round' },
      paint: { 'line-color': '#7a8290', 'line-width': 6, 'line-opacity': 0.75 },
    });
  }, [map, runways]);

  // Where a coordinate sits in the box: through the live camera once there is one, through
  // the fitted static projection before that.
  const fallbackBounds = diagramBounds(points);
  function place(point: LatLon): DiagramPoint {
    if (map === null) {
      return projectLatLon(point, fallbackBounds);
    }
    const projected = map.project([point.longitude, point.latitude]);
    return { x: projected.x, y: projected.y };
  }

  return (
    <div className="pos-diagram" style={{ width: DIAGRAM_WIDTH, height: DIAGRAM_HEIGHT }}>
      <div
        ref={containerRef}
        className="pos-diagram__map"
        role="img"
        aria-label="Airport map"
      />

      <div className="pos-diagram__overlay">
        {runways.map((runway) => {
          const point = place(runway.threshold);
          return (
            <span
              key={runway.ident}
              className="pos-diagram__runway-label pos-mono"
              style={{ left: point.x, top: point.y }}
              aria-hidden="true"
            >
              {runway.ident}
            </span>
          );
        })}

        {/*
          Keyed by name AND index: real apt.dat parking names repeat — LFMN alone has
          dozens of stands all called "Apron K parking" — and duplicate React keys leave
          stale buttons behind that no longer follow the camera.
        */}
        {stands.map((stand, index) => {
          const point = place(stand.position);
          return (
            <button
              key={`${stand.name}#${String(index)}`}
              type="button"
              className={
                stand.name === selectedStand
                  ? 'pos-diagram__stand pos-diagram__stand--selected'
                  : 'pos-diagram__stand'
              }
              style={{ left: point.x, top: point.y }}
              aria-pressed={stand.name === selectedStand}
              aria-label={`Stand ${stand.name}`}
              onClick={() => {
                onSelect(stand.name);
              }}
            >
              <span className="pos-diagram__stand-dot" aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </div>
  );
}
