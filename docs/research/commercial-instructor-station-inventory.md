# Competitive inventory — a commercial instructor station

A feature-by-feature record of the closest commercial equivalent to Open Instructor Station: a
proprietary Windows instructor station for X-Plane and the MSFS family. It is referred to here
as **the reference product**; the vendor and product name are deliberately left out.

It exists so we can compare scope against [`../feature-spec.md`](../feature-spec.md)
deliberately: what they solved, what they left out, and where our 15 managers have gaps.

| | |
|---|---|
| Build surveyed | A 2026 release, evaluation licence |
| Configuration | Desktop install, X-Plane 12 profile, no simulator connected |
| Date | 2026-08-09 |
| Sources | The running application, every module walked, plus the vendor's public online manual |

**Scope of this document.** It records *what the product does*, observed from its own UI and its
public documentation. No code, layout, artwork, string or asset is reproduced here, and none may
be copied into this repository — the same rule that governs Little Navmap in `CLAUDE.md` applies
here with more force, since the reference product is proprietary. Screenshots taken during the
survey were kept out of the repo on purpose.

---

## 0. Shape of the product

A single Windows desktop application, **external to the simulator** — the same core premise as
ours. It connects to X-Plane over the **legacy UDP protocol on port 49000** (auto-detected or
manually configured IP and port) and to the MSFS/P3D/FSX family over **SimConnect**, local or
remote.

Navigation is a flat grid of **module buttons along the bottom edge**, two rows, always visible.
No tab bar, no nesting: one click reaches any module from any other. Each module then has its
own vertical rail of sub-sections on the left. Everything is sized for touch, and the vendor
ships Android and iOS clients plus a network client for extra PCs.

The bottom bar carries 14 modules plus four global buttons:

| Button | Behaviour |
|---|---|
| **Freeze** | Freezes aircraft position in the simulator while leaving pitch, bank and airspeed controllable. Turns red while active. |
| **Pause** | Pauses the simulator outright. Turns red while active. |
| **Info** | Licence, changelog, hardware key, support contact form. |
| **Exit** | Closes the application. |

All main buttons have `CTRL+SHIFT+<letter>` shortcuts (P position, M map, Z freeze, U pause,
E exit …). Which modules appear, and in what order, is configurable. A 15th module,
**Access Control**, is a paid add-on and was not present in the surveyed install.

Three cross-cutting mechanics worth noting, because they recur in every module:

1. **Presets everywhere.** Position, weather and fuel/load each have their own unlimited,
   user-named preset store with a right-click rename/delete menu. There is no single "scenario"
   object — the presets are per-module and independent.
2. **Aircraft profiles.** Most numeric defaults (approach distances, pattern geometry, pushback
   speed, gauge options) can be stored *per aircraft* rather than globally, switched on with one
   setting.
3. **Tri-state layer toggles.** Map layers are not on/off but off → symbols → symbols + labels.

---

## 1. Position

The module that most directly overlaps our Position Manager. Left column: airport selection;
centre: a large picker; bottom: the options that are applied with the move.

- **Airport selection**
  - ICAO entry field.
  - **Random** airport button.
  - **Search for Airport** dialog.
  - Airport information read-out: name, country, city.
  - **Show Airport on Map** and **Show Airport METAR** buttons.
- **Runway / helipad selection**
  - Every runway end as a large button across the top (keyboard shortcut to cycle).
  - Runway information line: surface type, length, elevation, heading, **ILS frequency**.
  - Helipads listed alongside runways.
  - Optional confirmation dialog before a move (a setting).
- **Approach Training** — a 3×3 grid of placements around the selected runway:
  - `Downwind Left` / `Take Off` / `Downwind Right`
  - `Vectors Left` / `3 NM Final` / `Vectors Right`
  - `Base Left` / `8 NM Final` / `Base Right`
  - Each tile states its own geometry, e.g. *Downwind 4 NM, back 1 NM*; *Vectors 2 NM, final 6 NM*;
    *Base 4 NM, final 6 NM*. All distances, the vertical/horizontal offset, the vectors intercept
    angle and the downwind altitude are configurable in Settings, per aircraft profile.
  - Glideslope follows the runway's published ILS angle, or 3° when there is none.
  - Only **two** named final distances are offered as tiles (3 NM and 8 NM); anything else goes
    through Custom Location.
- **SID / STAR waypoints**
  - Procedure type selector (SID or STAR), procedure ident selector, waypoint selector.
  - **Move Aircraft to Waypoint**, with heading automatically set toward the next waypoint.
  - No approach (APPCH) procedures and no holding placement in this module — holdings are a
    *display* feature of the Map (§2).
- **Airwork** — four buttons at pre-defined flight levels, altitudes set in Settings.
- **Custom Location**
  - Altitude (MSL) and heading fields.
  - *From runway landing point*: distance offset plus direction.
  - *At coordinate*: latitude/longitude, pre-filled from the current airport.
- **Gate or Parking** — type filter (all, gate, tie-down …), position selector, move button.
- **Options applied with every placement**
  - **IAS** (kt) and **pitch** (°).
  - **Set gear** (with up/down), **set flaps** (%).
  - **Override altitude** (ft MSL).
  - **Set HDG** and **Set CRS** checkboxes — auto-tunes heading and OBS course, and the ILS
    frequency for the runway.
  - Saved per aircraft profile.
- **Flight Situation Presets**
  - **Add** captures the current situation: position, altitude, speed, heading, pitch, bank.
  - Paged 6-at-a-time with Back/Next; right-click to rename or delete.
  - **Reset Current Flight Situation**.
  - Optionally saves the active flight plan with the preset.
  - A recent build additionally saves and restores the *internal* aircraft situation of one
    payware airliner family alongside the preset (commercial licence).
- **Airport/runway restriction filter** (Settings): minimum runway length, surface type, whether
  helipads appear at all.
- **Scenery reload handling** (Settings): a recent build changed ground repositions in X-Plane to
  force a scenery reload only when the new position is **more than 50 NM** away.

---

## 2. Map

A full moving map, and the module with the largest surface area. Layers are tri-state: off,
symbols, symbols + text.

- **Aircraft layers**: user aircraft (adds flight level, IAS, true heading when fully on);
  AI aircraft (type, altitude, speed, heading; limited to ~70–100 NM around the user);
  **VATSIM**, **IVAO** and **PilotEdge** live networks, each with pilots and ATC and a
  last-update timestamp on hover.
- **Object layers**: airports, runways, ILS beams, runway extended axis (dotted), markers
  (OM/MM/IM/BC), taxiways/aprons/parking with names, VOR/DME, NDB, airspaces.
- **Navigation layers**: high (jet) airways, low (victor) airways, waypoints — each with idents.
- **Other layers**: weather stations, user POIs.
- **Backgrounds**: plain, street map, satellite, height/elevation map — from a commercial tile
  provider or **OpenStreetMap**, selectable.
- **Actions**: Find Object dialog; **Flight Plan Mode** (edit the plan on the map); Auto Zoom
  driven by altitude AGL; zoom in/out; centre aircraft; **trace aircraft** (trail line);
  **Reposition Aircraft** by clicking the map; weather info overlay (wind arrow, direction,
  speed, visibility, OAT, QNH); **measure** tool (distance, true bearing, time en-route);
  compass rose around the aircraft; **print map**.
- **Interactions**: drag to pan, wheel/pinch to zoom, `CTRL`+drag to zoom to a region,
  right-click (or long touch) for the context menu.
- **Right-click menu**: show map information for the facility; **create user POI**;
  **show holding** — standard/non-standard turn, inbound course, ground speed, entry sector
  display, time- or distance-based legs, optional radial offset from the fix; **show SIDs/STARs**
  for a chosen runway and procedure.
- **Footer**: cursor position, FPS, map scale, height-map legend.
- **Settings**: refresh rate; grid and **minimum sector altitude (MSA)** display; customisable
  aircraft label text with placeholders (separately for user, AI and online aircraft); auto
  re-centring; bearing type; ground-traffic filtering; POI import/export as CSV; holding entry
  sector size.

---

## 3. Flight Plan

- **Current flight plan**: departure/arrival airports and runways, next waypoint with distance
  and **ETE** (switchable to **ETA**, computer or simulator time, local or UTC), total remaining
  distance and time, and the full point list with airway, true/magnetic heading and leg distance.
  Right-click a point to delete it, move it up/down, centre the map on it, or clear the plan.
  **Print** the plan.
- **Manual flight planning**: load / save / delete named plans; title, flight number, cruising
  altitude, cost index; set departure and arrival airport; **add waypoint**; **calculate airway
  route** automatically; reset plan.
- **Airway usage**: none / high (jet) / low (victor) / both, and a **use SIDs/STARs** toggle.
- **Import**: the MSFS/P3D/FSX plan formats, the X-Plane plan formats, two payware GPS/airliner
  route formats, a route-finder web service, an online flight-planning service, plain waypoint text, the
  scheduled flights of a payware dispatch tool, and the company-route stores of three payware
  Airbus add-ons — thirteen sources in all.
- **Export**: the same formats, plus one more payware airliner route format, direct load into the
  simulator, and direct export to a third-party MCDU.
- **Synchronise** with the simulator's own flight plan and with four third-party FMS/MCDU
  implementations.

---

## 4. Conditions (weather, time, simulation rate)

Sub-sections: Current Weather, Weather Themes, Real-Time Weather, ILS Visibility, Custom Weather,
Weather Presets, Season and Time.

- **Current weather**: read back as a METAR string, plus a translated table or continuous-text
  rendering, with a filter for official METAR data only. Load it into Custom Weather, or save it
  as a preset.
- **Weather Themes**: one-click pre-configured themes.
- **Real-time weather**: push live weather into the simulator; source selectable (**NOAA,
  VATSIM, IVAO, PilotEdge**). *Continuous* mode updates automatically on a time interval or a
  distance flown, with a **minimum altitude threshold so an update never disturbs a final
  approach**, and shows when the next update is due. X-Plane gets a simpler enable + manual
  refresh.
- **ILS visibility**: one-click **CAT I, CAT I LTS, CAT II, CAT IIIa, CAT IIIb, CAT IIIc**, each
  carrying a decision height and an RVR (editable in Settings), applied against a reference
  airport/runway — last approach, flight-plan departure, flight-plan arrival, or a custom one.
  This is the sharpest training-oriented weather feature in the product: it sets weather *by the
  exercise you want*, not by meteorology.
- **Custom weather — simplified mode** (all simulators): a high layer, a low layer and a surface
  layer, with automatic interpolation between them. Per layer: wind, turbulence, visibility,
  temperature (auto ISA, ISA deviation, or direct), clouds and precipitation. Surface adds local
  QNH.
- **Custom weather — X-Plane native**: visibility, precipitation %, storminess %, temperature,
  dew point, pressure; **thermals** (altitude, coverage %, climb rate); wind layers (direction,
  altitude, speed, turbulence 0–10, gust direction change, gust speed increase); **wave height
  and direction**; cloud layers (type, base, top); **runway conditions — dry / damp / wet, with a
  "patchy" flag**. A recent build added X-Plane 12 upper-layer temperature and ISA deviation.
- **Custom weather — full P3D/FSX mode**: unlimited wind layers (direction or fully variable
  with a from/to range, speed, gusts, surface vs aloft, depth, turbulence None→Severe, wind shear
  Gradual→Instantaneous); cloud layers (base, coverage Few→Overcast and 1/8–8/8, type, top shape
  flat/round/anvil, turbulence, precipitation type and strength, precipitation base, icing rate);
  visibility layers (base, top, value, direction N…NW); temperature layers (max altitude,
  temperature, dew point); barometric pressure. Weather can be loaded from a pasted **METAR
  string**.
- **Third-party weather engine integration**: read and set the engine's weather mode, including a
  **historic date/time** mode, and author **weather effects** — thermal, downdraft, updraft,
  turbulence, windshear — each with an intensity, an altitude band (current aircraft altitude or
  manual, plus a range), and a location that is either the aircraft's, relative to it (bearing +
  distance) or absolute (lat/lon), with a radius. Effects can be created, edited, duplicated,
  deleted and sent.
- **Calculate Wind dialog**: a compass rose where the arrow's length is the speed, showing the
  aircraft heading and runway alignment, with a **crosswind component** computed either against
  the current heading or against a chosen runway.
- **Weather presets**: unlimited, named, right-click rename/delete/edit.
- **Season and Time**: quick season buttons; sync with computer time (with an offset) once or
  continuously; custom date and time dialogs.
- **Simulation rate**: `−` / `+`, showing requested and (X-Plane) actual rate.
- **Sound**: mute/un-mute the simulator, optionally automatically on connect.
- **General info**: simulator frame rate and simulator clock.

---

## 5. Pushback

- Shows the current airport and the exact location at it (gate, parking or runway).
- **Request jetway** (not supported for X-Plane).
- Three push directions — **backward**, **left**, **right** — each a large button:
  - straight push distance;
  - for the turning pushes, a **turn angle** (default 90°) and a **straight distance after the
    turn** (default 10 ft);
  - the **expected heading after the push** is displayed before you commit.
- Stops automatically once the distance (and post-turn distance) is reached; a manual **stop**
  is always available.
- Pushback speed and turn radius are settings; parameters save per aircraft profile.
- Refuses to run when the aircraft is not on the ground, and says so.

---

## 6. Fuel/Load

- **Fuel**: an "All Tanks" total plus every individual tank, five quick-set percentage buttons
  and a manual value field; setting the total distributes across tanks, or adjust one tank alone.
- **Payload**: every payload station listed, adjustable individually by button or by typing a
  value.
- **Weight calculation**, live: empty weight, + payload, = **zero fuel weight**, + fuel,
  = **gross weight**, max weight, and **centre of gravity** — longitudinal always, lateral on
  simulators that expose it (not X-Plane).
- **Freeze current fuel level** — stops consumption; unfreeze restores it.
- Unlimited named **fuel/load presets** with right-click rename/delete.

---

## 7. View/Slew

- **Camera view**: back to virtual (3D) cockpit; back to 2D cockpit; up to three custom camera
  positions (commercial licence, defined by offsets in Settings); an 8-direction translation pad
  plus up/down; rotate left/right/up/down; **zoom in/out at two speeds each**; reset view; cycle
  external views.
- **Slew mode**: enable/disable; stop (staying enabled); reset heading, pitch and bank to zero;
  forward/backward/left/right and turn left/right; up/down; bank left/right; pitch up/down.

---

## 8. Failures

- **Failure catalogue**: engines (individually), electrical system, brakes, **fuel leak** (all
  tanks or per tank, up to nine tanks), **gear stuck** and **flaps stuck** at a chosen position,
  and **panel failures** (one panel or several).
- **Conditions attached to any failure** — this is the interesting part:
  - trigger immediately, or after a delay in minutes;
  - only above a minimum altitude (MSL) and/or below a maximum;
  - only above a minimum IAS and/or below a maximum;
  - for leaks, a **fuel loss rate per minute**;
  - explicit **enable** and **disable** buttons per armed failure.
- **Random failures**: choose which failure types are eligible, the conditions they inherit, a
  fuel-loss range for leaks, an **average number of failures per hour** (decimals allowed, so
  less than one per hour) and a **minimum interval between failures**. Optionally re-armed
  automatically on start-up.
- **Clear All** resets every active failure.
- **Hide failures** from the trainee (commercial licence) and per-failure colour settings.
- Failure source is switchable between the simulator's standard failure system and third-party
  aircraft systems; recent builds added the internal failure systems of several payware
  airliners.

---

## 9. Aircraft

Sub-sections: Aircraft Gauges, Aircraft Status, Engines, Radio & Autopilot, Lights & Switches,
TCAS Traffic, ATC Control, Change Aircraft.

- **Gauges**: a classic **six-pack** or a generic **PFD**; each gauge can be **detached into its
  own always-on-top window**. Options for whether they show IAS/TAS/GS and true vs magnetic
  heading.
- **Status**: IAS, TAS, ground speed, Mach; indicated altitude, MSL, AGL, barometric setting and
  QNH; pitch, bank, **G-force**, vertical speed, heading, trims (with a *reset all three trims*
  button); flaps, gear, spoilers, parking brake; electrical bus load and voltage, battery charge,
  **APU**, ground power; **pressurisation** (status, target cabin altitude, dump); **exit doors**;
  **glider towing** with release, and a winch option on X-Plane.
- **Engines**: per-engine status, individual or collective lever control with 0 / 25 / 75 / 100 %
  quick buttons and a custom percentage, **reverse thrust** per engine or all, quick-start, and
  the engine switches.
- **Radio & autopilot**: frequencies, OBS/CRS, transponder; autopilot master, airspeed hold,
  altitude hold, vertical speed, heading hold.
- **Lights & switches**: the aircraft's light and switch set as buttons.
- **TCAS traffic**: spawn an **intruder** — aircraft type (defaults to yours), bearing relative
  to your heading (preset or typed), distance, TAS, relative altitude and vertical speed;
  generate, and remove all intruders.
- **ATC control**: show/hide the simulator's ATC window and pick menu options remotely.
- **Change aircraft**: pick from the installed list and swap (restrictable by licence settings).
- **Custom buttons**: user-defined buttons in named categories, each bound to a data/command ID
  with units, toggle or momentary, and activate/deactivate values — an escape hatch for anything
  the product does not expose natively.
- **Aircraft warnings** (Settings): alert on pitch or bank beyond a limit, or speed below an
  altitude.

---

## 10. Statistics

Two tabs: **General Statistics** and **Approach Statistics**.

- **General**: four live graphs — airspeed (IAS and TAS), altitude (aircraft altitude against
  **ground elevation**), vertical speed, and attitude (pitch and bank). Click to maximise one,
  right-click to choose what it plots.
- **Recording**: start/stop, transport controls to scrub back and forth through the recording,
  **clear all flight data**, **import from CSV**, **export as CSV**, **print charts**, and
  **export to Google Earth** with optional VOR, NDB and waypoint overlays inside a configurable
  radius. Which parameters are recorded, a high-speed recording mode and a data-point cap are
  settings.
- **Approach**: starts tracking automatically when an approach begins, or on a manually entered
  ICAO. Shows airport, runway and visibility, a **landing quality report**, and two deviation
  graphs — **localizer** (lateral alignment) and **glideslope** (against the runway's published
  angle, or 3° when there is none). Print, and reset.

---

## 11. Network

Not simulator networking — **remote control of the other PCs in a sim pit**.

- **Build Client**: generates a client executable to copy onto each remote machine; it reports
  its IP and port, shows when it last connected, and can start with Windows behind a full-screen
  waiting screen (custom background, logo and text on a commercial licence, and a command-line
  switch to disable it).
- **Add computers** by name, IP and port; enable/disable or delete each; a green or red border
  shows connection health along with last status and last connect time.
- Per computer: **restart, shutdown, hibernate, sleep**, and **Wake-on-LAN** (MAC learned from a
  previous connection or entered manually). The same four actions exist as *all computers*
  buttons.
- **Startup action sequences** per computer, executed in order with a configurable wait between
  them: *start program* (path, arguments, normal/minimised/maximised), *terminate program* (by
  window title substring or exact process name), *focus program* (same matching, plus optional
  synthetic keystrokes), *restart/shutdown/hibernate/sleep*.
- **Status page for web display**: an HTML template with placeholders — call sign, aircraft name
  override, departure/arrival, lat/lon, state (Parking/Taxi/In Flight), remaining distance, ETE,
  ETA, indicated/MSL/AGL altitude, true and magnetic heading, IAS/TAS/GS, vertical speed, OAT,
  and fore/back colours — served by a built-in web server, written to a file, or uploaded to FTP
  on an interval.

---

## 12. Motion

Hardware integration with a single motion-hardware vendor.

- **Motion platform**: active profile and profile switching; platform status (state, position,
  weight) with Initialize / Simulate / Park / Stop; per-motor status, temperature and force; a
  colour legend (disconnected, initialising, operational, fault).
- **Control loading**: active profile and switching; hardware connection status with Initialize /
  Stop / Fault Reset; simulator connection status with Connect / Disconnect; device status split
  by pilot, copilot and general devices.

---

## 13. Settings

Organised in three groups — **Simulator Related**, **Aircraft Related**, **Other**.

- **Simulator**: multiple named simulator configurations, one active. For X-Plane: install
  directory, **Build Database** (the surveyed install had built its database from the X-Plane 12
  directory and displays the build timestamp), UDP connection automatic or manual (IP, port
  49000). For the MSFS family: documents folder, database build, **navigation data update**,
  SimConnect local or remote.
- **Aircraft profiles**: enable per-aircraft settings, create/edit/copy/assign/revert profiles.
- **Position**: final distance and offsets, vectors distances and intercept angle, base
  distances, downwind lateral distance and altitude, the four airwork flight levels, what is
  auto-set on a position change (heading, course, ILS frequency), airport/runway restrictions,
  scenery reload and loading-dialog behaviour, confirmation dialogs, freeze/pause behaviour,
  whether to switch module after a placement.
- **Map**: per-map-type colours, text colours, zoom thresholds and font sizes; parking display;
  tooltips; auto-zoom table; aircraft icon style, distance vectors and afterglow trails;
  compass-rose radius; the altitude at which the display switches to flight levels; refresh rate;
  MSA display; label templates; background provider; online-network user IDs to suppress your own
  duplicate; POI CSV import/export; holding entry sector size.
- **Conditions**: ILS visibility category table, real-time weather source, mute on connect,
  simplified-weather toggle.
- **Failures**: colours, hide-from-trainee, auto re-arm random failures.
- **Statistics**: recorded parameters, high-speed recording, data-point limits, chart colours for
  screen and print, localizer information source.
- **Network**, **Status page**, **Mobile devices**: ports, IPs, update frequency, connection
  timeout, FTP parameters.
- **Units**: altitude, temperature, atmospheric pressure, other pressure, weight, short distance,
  far distance, speed, fuel, visibility, thrust, torque, and geographic coordinate format — each
  chosen independently.
- **Colour**: global theme colours, dark and light presets.
- **Third party**: paths, hosts and ports for ten third-party FMS, weather-engine and
  avionics products.
- **Other**: touch input helpers, help icons, always-on-top, taskbar hiding, automatic updates,
  exit confirmation, which main buttons show and their order, unpause delay/acceleration, settings
  **password protection** (commercial), print options and footer, window position reset, and
  **GPS data broadcast** to third-party apps (target IP and port).

---

## 14. Info, Access Control, and the rest

- **Info**: support contact form with optional log attachment, licence details and
  *deactivate licence on this computer* (to move it), copyright, changelog browser, hardware key.
- **Access Control** (paid add-on, absent from the surveyed install): locks the simulator until a
  valid **RFID transponder card** is presented on a COM-port reader, then sells access in
  **time packages against a credit balance**, per user, with free-credit allowances, expiry
  dates, a card block list and exportable usage logs. While armed it prevents minimising,
  exiting and keyboard task-switching. Built for commercial sim centres.
- **Dialogs** (19): choose simulator, find object, licence, activation count, message box,
  navigation data update, select aircraft profile / airport / airway / colour / date / procedure /
  runway / time, real-time weather info, two touch input helpers, update available, please-wait.
- **Aircraft support**: the vendor guarantees the aircraft-dependent functions only for the
  simulator's default aircraft; third-party add-ons work as far as they use standard interfaces.

---

## 15. What this means for Open Instructor Station

### 15.1 Mapping to our managers

`done` = shipped on `dev`; `in progress` = open branch or PR; `planned` = in
[`../roadmap.md`](../roadmap.md); `no equivalent` = not in `feature-spec.md` today.

| Their capability | Our manager | Status here |
|---|---|---|
| Runway-anchored placements (final, base, downwind, take-off, vectors) | 1 Position | in progress — 14 placement kinds designed, geodesy on `feature/placement-geodesy` (#6) |
| Named final distances | 1 Position | **broader here** — 20/15/10/8/5/3 NM vs their 3 and 8 |
| SID/STAR waypoint placement | 1 Position | in progress — plus APPCH, which they lack (#9) |
| Placement in a holding | 1 Position | in progress — they only *draw* holdings on the map |
| Gate / parking placement | 1 Position | in progress |
| Custom coordinate / offset from runway | 1 Position | in progress |
| Pre-teleport state (IAS, pitch, gear, flaps, altitude override, HDG/CRS, ILS) | 1 Position + 6 Aircraft | in progress — #8 (full setup), #41 (autopilot fields) |
| Flight situation presets | 14 Training Profiles | planned (phase 2) |
| Random/paged preset UI, rename & delete | 15 Instructor Panel | planned |
| Aircraft profiles (per-type defaults) | 14 Training Profiles | **no equivalent** — we have approach-category defaults, not per-aircraft profiles |
| Moving map with layer stack | 5 Instructor Map | planned (phase 3) |
| Reposition by clicking the map | 5 + 1 | planned (phase 3) |
| Holding / SID / STAR drawing on the map | 5 Instructor Map | planned |
| Measure tool, compass rose, trace, POIs | 5 Instructor Map | planned |
| VATSIM / IVAO / PilotEdge traffic overlay | — | **no equivalent** |
| MSA and grid display | 5 Instructor Map | **no equivalent** |
| Flight plan display, edit, airway routing | 7 Flight Plan | planned (phase 4; radios slice in phase 1) |
| Flight plan import/export (13 formats) and FMS sync | 7 Flight Plan | **no equivalent at that breadth** |
| Weather: layers, clouds, wind, visibility, temperature | 3 Weather | planned (phase 2) |
| Weather presets and themes | 3 + 14 | planned |
| Real-time weather with continuous updates | 3 Weather | **no equivalent** |
| **ILS visibility by CAT category** | 3 Weather | **no equivalent — strong candidate** |
| Crosswind calculator against a runway | 3 Weather | **no equivalent** |
| Runway condition (dry/damp/wet) | 3 Weather | **no equivalent** |
| Season, date, time, simulation rate | 3 Weather | partly planned |
| Failure catalogue (engines, electrical, brakes, leak, gear, flaps, panels) | 4 Failures | planned (phase 2) |
| **Failure conditions: delay, altitude band, speed band** | 4 Failures | planned — must match this |
| **Random failures: rate per hour + minimum spacing** | 4 Failures | **no equivalent — strong candidate** |
| Hide failures from the trainee | 4 Failures | **no equivalent** |
| Pushback with turn angle and post-turn distance | 8 Pushback | planned (phase 3) |
| Fuel per tank, payload stations, ZFW/GW/CG | 9 Fuel & Payload | planned (phase 2) |
| Freeze fuel level | 9 Fuel & Payload | **no equivalent** |
| Camera views, custom positions, external cycling | 10 Camera | planned (phase 3) |
| Slew mode | 10 Camera / 1 Position | **no equivalent** — our reposition covers the intent |
| Live gauges (six-pack, PFD), detachable windows | 6 Aircraft Control | partly — telemetry panel exists, no gauges |
| Engines, electrics, pressurisation, doors, APU, towing | 6 Aircraft Control | partly planned |
| TCAS intruder injection | 13 AI Traffic | planned (phase 3) — theirs needs no plugin |
| ATC window control | — | **no equivalent** |
| Custom buttons bound to arbitrary datarefs/commands | 15 Instructor Panel | **no equivalent — cheap and powerful** |
| Live graphs + CSV import/export + replay scrub | 12 Session Recorder | planned (phase 4) |
| Google Earth export | 12 Session Recorder | **no equivalent** |
| Approach statistics: landing report, LOC and GS deviation | 11 Statistics & Landing Analysis | planned (phase 4) |
| Remote PC control, WoL, startup sequences | — | **no equivalent, and out of scope** |
| Web status page with placeholders | — | **no equivalent** |
| Motion platform / control loading | — | **no equivalent, and out of scope** |
| Access control by RFID card and credits | — | **no equivalent, and out of scope** |
| Independent unit selection (13 quantities) | 15 Instructor Panel | **no equivalent — worth adopting the idea** |
| Tablet/touch-first layout, mobile clients | 15 Instructor Panel | done in principle (LAN + tablet is a first-class scenario) |

### 15.2 Where we are already ahead

- **Placement catalogue.** Six named final distances against their two, plus approach procedures
  and holdings as *placements* rather than drawings, plus a preview endpoint that resolves a
  placement without touching the simulator.
- **Speed as part of a placement.** Their Options block is a set of check-boxes the instructor
  must remember to tick; our `Placement.ias_kt` is required by construction (#39), so a
  placement cannot be defined without answering the question.
- **Transport.** They use X-Plane's legacy UDP on 49000; we use the 12.1+ Web API over REST and
  WebSocket, which is what makes a browser UI on a tablet possible without a client executable.
- **Openness.** Generated API types, an open OpenAPI schema and no per-machine licence.

### 15.3 Gaps worth turning into issues

Ordered by value per unit of work, in my reading:

1. **ILS visibility by CAT category** (weather, phase 2). One click sets DH and RVR for CAT I →
   IIIc against a chosen runway. It converts weather from a meteorological control into a
   training control, which is exactly our product thesis.
2. **Random failures with a rate and a minimum spacing** (failures, phase 2). "0.5 failures per
   hour, never two within 10 minutes" is a training scenario in one line, and it composes with
   the scenario generator (manager 2) rather than competing with it.
3. **Failure arming conditions** — delay, altitude band, speed band. Already implied by our
   scenario YAML, but they belong on a single failure too, not just on a scripted scenario.
4. **Custom instructor buttons** bound to arbitrary datarefs/commands. An escape hatch that makes
   every aircraft-specific gap the user's to close instead of ours.
5. **Independent unit selection.** Thirteen quantities, each independently chosen. Cheap in a
   typed UI, and it is the difference between a tool a European and an American instructor can
   both use without friction.
6. **Freeze fuel level.** One dataref, removes the "we ran out mid-exercise" failure mode.
7. **Crosswind component against a chosen runway**, shown while setting the wind.
8. **Runway condition (dry/damp/wet)** — X-Plane exposes it, and it is a training variable.
9. **Per-aircraft profiles for placement geometry.** We default by ICAO approach category, which
   is more principled; a per-airframe override on top would cover the rest.
10. **MSA and grid on the map** (phase 3).

### 15.4 Explicitly not for us

Motion platforms, control loading, remote PC power management, the RFID access-control add-on,
and the FMS/company-route integrations for specific payware aircraft. All are real businesses,
none belongs in an open external instructor station, and each would drag in a vendor dependency.

---

## Method

The surveyed build was installed locally and walked module by module with no simulator
connected, and its public online manual was read end to end — every feature page, the dialog
index and the general-usage section. Version-specific behaviour was cross-checked against the
build's own changelog. Everything above is a description in our own words of externally
observable behaviour; nothing was decompiled, extracted or copied.
