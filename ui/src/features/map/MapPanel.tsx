/**
 * The Instructor Map: OSM tiles, the mock airport overlay, the live aircraft, and the
 * three-zone chrome — layer toggles on the left, canvas in the middle, tool buttons on
 * the right.
 *
 * All map behaviour lives in the hooks next door; this file is layout and dispatch.
 * The chrome renders whether or not the map is ready, which is also what the jsdom
 * tests exercise (the WebGL side stays dormant behind the maplibre stub).
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { MapStagingBar } from './MapStagingBar';
import {
  followToggled,
  layerToggled,
  modeSelected,
  type MapLayerKey,
} from './mapSlice';
import { distanceNm, formatMeasure, initialBearingDeg } from './measure';
import { useAircraftMarker } from './useAircraftMarker';
import { useMapInteractions } from './useMapInteractions';
import { useMapLibre } from './useMapLibre';
import { useMapOverlays } from './useMapOverlays';
import './map.css';

const LAYER_TOGGLES: ReadonlyArray<{ key: MapLayerKey; label: string }> = [
  { key: 'runways', label: 'Runways' },
  { key: 'ils', label: 'ILS' },
  { key: 'navaids', label: 'Navaids' },
  { key: 'trail', label: 'Trail' },
];

function ZoomInIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" fill="none" />
    </svg>
  );
}

function ZoomOutIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path d="M5 12h14" stroke="currentColor" strokeWidth="2" fill="none" />
    </svg>
  );
}

function FollowIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <circle cx="12" cy="12" r="6" stroke="currentColor" strokeWidth="2" fill="none" />
      <path
        d="M12 1v4M12 19v4M1 12h4M19 12h4"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" />
    </svg>
  );
}

function MeasureIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        d="M4 20 20 4M7 17l2 2M11 13l2 2M15 9l2 2"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
    </svg>
  );
}

function RepositionIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path
        d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11Z"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
      <circle cx="12" cy="10" r="2" fill="currentColor" />
    </svg>
  );
}

export function MapPanel() {
  const dispatch = useAppDispatch();
  const layers = useAppSelector((state) => state.map.layers);
  const follow = useAppSelector((state) => state.map.follow);
  const mode = useAppSelector((state) => state.map.mode);
  const measureA = useAppSelector((state) => state.map.measureA);
  const measureB = useAppSelector((state) => state.map.measureB);
  const staged = useAppSelector((state) => state.map.staged);

  const { containerRef, map } = useMapLibre();
  useMapOverlays(map);
  useAircraftMarker(map);
  useMapInteractions(map);

  let measureReadout: string | null = null;
  if (mode === 'measure') {
    if (measureA !== null && measureB !== null) {
      measureReadout = formatMeasure(
        distanceNm(measureA, measureB),
        initialBearingDeg(measureA, measureB),
      );
    } else if (measureA !== null) {
      measureReadout = 'Tap the second point';
    } else {
      measureReadout = 'Tap two points to measure';
    }
  }

  return (
    <section className="panel map-panel" aria-labelledby="map-heading">
      <h2 id="map-heading">Map</h2>
      <div className="map-panel__body">
        <div className="map-panel__layers" role="group" aria-label="Map layers">
          {LAYER_TOGGLES.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className="map-layer-toggle"
              aria-pressed={layers[key]}
              onClick={() => {
                dispatch(layerToggled(key));
              }}
            >
              <span className="map-layer-toggle__dot" aria-hidden="true" />
              {label}
            </button>
          ))}
          <p className="map-panel__note">Overlay: demo fixture</p>
        </div>

        <div className="map-panel__viewport" data-mode={mode}>
          <div ref={containerRef} className="map-panel__canvas" />
          {measureReadout !== null && (
            <p className="map-panel__chip">{measureReadout}</p>
          )}
          {mode === 'reposition' && staged === null && (
            <p className="map-panel__chip">Tap the map to stage a position</p>
          )}
        </div>

        <div className="map-panel__tools" role="group" aria-label="Map tools">
          <button
            type="button"
            className="map-tool"
            aria-label="Zoom in"
            onClick={() => {
              map?.zoomIn();
            }}
          >
            <ZoomInIcon />
          </button>
          <button
            type="button"
            className="map-tool"
            aria-label="Zoom out"
            onClick={() => {
              map?.zoomOut();
            }}
          >
            <ZoomOutIcon />
          </button>
          <button
            type="button"
            className="map-tool map-tool--follow"
            aria-label="Follow aircraft"
            aria-pressed={follow}
            onClick={() => {
              dispatch(followToggled());
            }}
          >
            <FollowIcon />
          </button>
          <button
            type="button"
            className="map-tool map-tool--mode"
            aria-label="Measure distance"
            aria-pressed={mode === 'measure'}
            onClick={() => {
              dispatch(modeSelected('measure'));
            }}
          >
            <MeasureIcon />
          </button>
          <button
            type="button"
            className="map-tool map-tool--mode"
            aria-label="Reposition aircraft"
            aria-pressed={mode === 'reposition'}
            onClick={() => {
              dispatch(modeSelected('reposition'));
            }}
          >
            <RepositionIcon />
          </button>
        </div>
      </div>

      {staged !== null && <MapStagingBar staged={staged} />}
    </section>
  );
}
