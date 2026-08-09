/**
 * The two placements that need no runway: a bare coordinate and a named fix.
 *
 * **The speed field is not optional here and the form says why.** A free coordinate is the
 * one placement whose speed defaults to zero, because a latitude and longitude is as
 * likely a parking spot as a cruise level and guessing would be inventing. An instructor
 * putting the aircraft airborne must state a speed or it arrives below stall — the server
 * says so in its notes, and the form says so before they get there.
 */

import { useState } from 'react';
import { useAppDispatch } from '../../store';
import { placementStaged } from './positionSlice';

export function CoordinateForm() {
  const dispatch = useAppDispatch();
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [altitude, setAltitude] = useState('');
  const [heading, setHeading] = useState('');
  const [speed, setSpeed] = useState('');
  const [fixIdent, setFixIdent] = useState('');
  const [fixAltitude, setFixAltitude] = useState('');

  const coordinateReady = latitude.trim() !== '' && longitude.trim() !== '';
  const fixReady = fixIdent.trim() !== '' && fixAltitude.trim() !== '';

  return (
    <div className="coordinate">
      <form
        className="coordinate__form"
        onSubmit={(event) => {
          event.preventDefault();
          dispatch(
            placementStaged({
              type: 'coordinate',
              position: {
                latitude: Number(latitude),
                longitude: Number(longitude),
                altitude_ft: altitude === '' ? 0 : Number(altitude),
              },
              heading_deg: heading === '' ? 0 : Number(heading),
              ias_kt: speed === '' ? 0 : Number(speed),
            }),
          );
        }}
      >
        <h3 className="coordinate__title">Coordinate</h3>
        <div className="coordinate__row">
          <label className="coordinate__field">
            <span>Latitude</span>
            <input
              type="number"
              step="any"
              value={latitude}
              onChange={(event) => {
                setLatitude(event.target.value);
              }}
            />
          </label>
          <label className="coordinate__field">
            <span>Longitude</span>
            <input
              type="number"
              step="any"
              value={longitude}
              onChange={(event) => {
                setLongitude(event.target.value);
              }}
            />
          </label>
        </div>
        <div className="coordinate__row">
          <label className="coordinate__field">
            <span>Altitude ft</span>
            <input
              type="number"
              value={altitude}
              onChange={(event) => {
                setAltitude(event.target.value);
              }}
            />
          </label>
          <label className="coordinate__field">
            <span>Heading °</span>
            <input
              type="number"
              value={heading}
              onChange={(event) => {
                setHeading(event.target.value);
              }}
            />
          </label>
          <label className="coordinate__field">
            <span>Speed kt</span>
            <input
              type="number"
              value={speed}
              onChange={(event) => {
                setSpeed(event.target.value);
              }}
            />
          </label>
        </div>
        <p className="coordinate__warning">
          Leave the speed at 0 only for a point on the ground. An airborne placement at 0
          kt arrives below stall speed.
        </p>
        <button type="submit" className="coordinate__submit" disabled={!coordinateReady}>
          Stage coordinate
        </button>
      </form>

      <form
        className="coordinate__form"
        onSubmit={(event) => {
          event.preventDefault();
          dispatch(
            placementStaged({
              type: 'waypoint',
              ident: fixIdent.trim().toUpperCase(),
              altitude_ft: Number(fixAltitude),
            }),
          );
        }}
      >
        <h3 className="coordinate__title">Waypoint</h3>
        <div className="coordinate__row">
          <label className="coordinate__field">
            <span>Fix ident</span>
            <input
              type="text"
              className="mono"
              placeholder="GOXOL"
              value={fixIdent}
              onChange={(event) => {
                setFixIdent(event.target.value);
              }}
            />
          </label>
          <label className="coordinate__field">
            <span>Altitude ft</span>
            <input
              type="number"
              value={fixAltitude}
              onChange={(event) => {
                setFixAltitude(event.target.value);
              }}
            />
          </label>
        </div>
        <button type="submit" className="coordinate__submit" disabled={!fixReady}>
          Stage waypoint
        </button>
      </form>
    </div>
  );
}
