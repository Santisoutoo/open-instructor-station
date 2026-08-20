# `bridge/` — Optional XPPython3 plugin

**Status: implemented, Phase 3.** `PI_OISBridge.py` is the production plugin. This file (the
transport protocol and its rationale) is written for whoever installs it or extends the
`adapters/xplane/` half that talks to it — the full design is
[`../docs/designs/ai-traffic.md`](../docs/designs/ai-traffic.md).

---

## Installing it

1. Install [XPPython3](https://xppython3.readthedocs.io/) into your X-Plane 12 install (a
   one-time, user-driven step — the application never does this for you).
2. Copy `bridge/PI_OISBridge.py` into
   `<X-Plane 12>/Resources/plugins/PythonPlugins/`.
3. Start X-Plane and load a flight. The Web API indexes datarefs at startup, so the plugin must
   be present *before* X-Plane launches — copying it in while X-Plane is already running will not
   be picked up until the next restart.
4. The station's X-Plane adapter probes for `ois/bridge/heartbeat_s` at connect time (see
   "Capability gating" below) and flips `can_spawn_traffic` on automatically. No configuration
   step in the station itself.

Uninstalling is deleting the file — nothing else in the application depends on its presence.

---

## What it is for

**AI traffic — and nothing else.**

Spawning and driving AI aircraft, ground vehicles and birds is **the one thing the X-Plane Web
API cannot do**. Everything else this application needs — reading state, repositioning the
aircraft, weather, failures, radios, commands — is reachable over the network from outside the
simulator. Traffic is not: it requires code running *inside* X-Plane.

That is the entire justification for this directory. `bridge/` is an **XPPython3 plugin** that
the user optionally installs into their X-Plane plugins folder, and it exists to serve the
[AI Traffic Manager](../docs/feature-spec.md#13-ai-traffic-manager):

- TCAS conflicts leading to a resolution advisory
- Runway incursions
- Taxi traffic
- Approach traffic (sequencing and spacing)

The bridge stays as thin as possible. Traffic *paths* — the geometry of a converging conflict, an
incursion timed to the student's rollout, an approach sequence — are computed in `core/` and sent
across as plain waypoint tracks. The plugin spawns, moves and despawns. It does not make
decisions.

---

## The hard rule

> **The application must work 100% without this plugin, for everything except AI traffic.**

This is not a design preference; it is [hard rule 1 in `CLAUDE.md`](../CLAUDE.md):

> **The app is 100% external.** It connects to the simulator over the network. The user never
> opens or launches anything inside the sim. In-sim components (`bridge/`) are *optional*
> add-ons, and every feature outside AI traffic must work without them.

Concretely, with the bridge **not installed**:

- the application starts normally;
- every other manager works normally;
- the traffic panel and the traffic-dependent scenarios (TCAS RA, runway incursion) are
  **disabled in the UI with a stated reason**, never offered and then failed at runtime.

There is a test for this. An adapter declaring `can_spawn_traffic = False` must run the full
suite green — see the Phase 3 exit criteria in [`../docs/roadmap.md`](../docs/roadmap.md).

**Never let a bridge dependency leak into a non-traffic feature.** If a manager starts needing
the plugin, that manager has been designed wrong.

---

## Capability gating

The whole surface sits behind **`can_spawn_traffic`**, following the project's
*capabilities, not failures* rule: adapters declare what they support, and unsupported features
are disabled in the UI rather than left to throw.

```
bridge installed + reachable   →  can_spawn_traffic = True   →  traffic UI enabled
bridge absent or unreachable   →  can_spawn_traffic = False  →  traffic UI disabled, with reason
```

The flag is discovered by the **X-Plane adapter** at connect time and published to the UI with
the rest of the capability set. `core/` and `server/` never reach the plugin directly — it is
reached *through* `adapters/xplane/`, like every other simulator detail.

Adding `can_spawn_traffic` to the `Capabilities` contract is a **shared-foundation change**: made
once, alone, before the bridge work branches off it, and it must **extend the contract suite**
(`tests/adapters/test_contract.py`) like any other capability. It is never parallelised.

---

## Phase 3

The bridge is scheduled for **Phase 3 — Instructor Map + AI Traffic**
([roadmap](../docs/roadmap.md#phase-3--instructor-map--ai-traffic)). It is the **first component
in the whole project that runs inside the simulator**, which is exactly why it is deliberately
late and deliberately optional.

Phase 3 exit criteria that bear on this directory:

- With the bridge **not installed**: the application starts, every non-traffic feature works, and
  traffic controls are disabled with a stated reason — verified by a test against an adapter
  declaring `can_spawn_traffic = False`.
- With the bridge installed: a TCAS RA scenario and a runway incursion scenario run in a live
  X-Plane.

---

## Transport: custom datarefs through the existing Web API connection

The plugin registers four custom datarefs via XPPython3's `XPLMRegisterDataAccessor` — the same
mechanism any XPPython3 plugin uses to publish state, so they show up in the Web API's own
dataref index with no bridge-specific server code:

| Custom dataref | Type | Direction | Purpose |
|---|---|---|---|
| `ois/bridge/heartbeat_s` | float | bridge → adapter | Wall-clock seconds since the plugin loaded, advanced every flight-loop tick. Lets the adapter tell "loaded and alive" from "loaded and hung." |
| `ois/traffic/command` | data (byte array) | adapter → bridge | One pending command, JSON-encoded UTF-8: `{"op": "spawn"|"despawn"|"clear_all", "seq": ..., "traffic_id": str|null, "track": <TrafficTrack.model_dump()>|null}`. Read once, acted on, cleared, by the flight loop. |
| `ois/traffic/command_ack` | data | bridge → adapter | JSON ack for the most recently processed command: `{"seq", "op", "traffic_id", "ok": bool, "error": str|null, ...op-specific fields}`. A spawn ack additionally carries `object_path` (which library object resolved, or `null`) and `tcas_target` (`bool`) — the honest "what actually happened" the capabilities-not-failures rule asks for. A capacity refusal sets `"error_kind": "capacity"` plus `capacity`/`active_count` so the adapter can raise `core.traffic.TrafficCapacityExceeded` instead of a generic error. |
| `ois/traffic/contacts` | data | bridge → adapter | JSON array of every live entity's current state, written every flight-loop tick — the wire shape mirrors `TrafficContact` minus `label`/`scenario_shape` (kept adapter-side), plus `vertical_speed_fpm` derived from the current leg's altitude slope. |

This is a **request/poll** protocol, not a queue: the adapter writes one command and polls
`command_ack` for a matching `seq`/`traffic_id`, and reads `contacts` on every status/stream tick.
**At most one command is in flight at a time** — the simplest correct thing, and safe because
`server/traffic_routes.py` never issues two spawn/despawn calls concurrently against one adapter
instance. Measured live against X-Plane 12 at LEMD (`ai-traffic.md` §10.4, 2026-08-18): median
round trip **26.9 ms**, ack present on the bridge's first poll every time, and no measured payload
ceiling up to 64 KB (a realistic 8-waypoint spawn command is ~1.6 kB) — the transport has margin
to spare.

## Spawn mechanism: `XPLMInstance`, not multiplayer slots

Earlier drafts of this design assumed AI traffic could be driven through the legacy multiplayer
aircraft slots (`sim/multiplayer/position/plane1…19`). **That does not work on a real install** —
measured live: `XPLMAcquirePlanes` fails whenever another plugin already controls the aircraft
set (the common case: xPilot, IVAO, AutoDGS, BetterPushback all contend for it), and writes to
the `plane1_x/y/z/psi` datarefs do not stick even when `writable = true` is reported.

What **does** work, and is what `PI_OISBridge.py` uses for all three entity kinds
(`aircraft` / `ground_vehicle` / `bird`): `XPLMInstance`. On first spawn of a kind, the plugin
resolves a library object via `lookupObjects`, `loadObject`s it, `createInstance`s it, and drives
it every tick with `instanceSetPosition`. A kind whose library path does not resolve (birds were
untested end to end on the spike install) degrades honestly — the entity still exists, moves and
is reported in `contacts`, it simply has no visual, and the spawn ack's `error` field says so
rather than the spawn silently failing.

For `kind="aircraft"` entities, the plugin additionally attempts a **TCAS-target** entry
(`sim/operation/override/override_TCAS` + `sim/cockpit2/tcas/targets/modeS_id`, a 64-entry table)
so the student's own TCAS instrument can see the traffic. These datarefs are present and
`writable = true`, but **the write has not been verified to stick** — the multiplayer-slot result
above is the standing reminder that `writable = true` is not proof. The write is attempted and
guarded: a failure disables TCAS-target writes for the rest of the session and every aircraft
entity degrades to instance-only (visible, maybe not on TCAS) rather than taking the plugin down.
`tests/sim/test_live_traffic.py` owns the read-back verdict — nothing in this plugin claims the
TCAS write works, only that it is attempted safely.

## Track interpolation: a deliberate, small duplication of `core/traffic.py`

`architecture.md`'s dependency diagram draws no `bridge/` → `core/` edge, and this plugin does not
import `core/` — it re-implements the handful of lines `core.traffic.interpolate_track` needs
(constant ground speed per leg, along the great-circle connecting two waypoints) directly against
the wire JSON, using stdlib `math` instead of `geographiclib`. The two are pinned to agree against
the same reference values (`ai-traffic.md` §8.1) in the plugin's own docstrings; the spherical
approximation here differs from `core/`'s WGS-84 ellipsoid by well under 0.5% over the sub-20 NM
legs every shipped geometry builder produces.

## Notes for whoever extends it

- **XPPython3** is a third-party X-Plane plugin that runs Python plugins inside the sim. The user
  installs it themselves; the application never installs anything into their simulator.
- **Never copy code from third-party projects.** This is a private, proprietary project — no
  license file, no license headers.
- Fail soft: if the plugin disappears mid-session, `SimAdapter.spawn_traffic` /
  `despawn_traffic` / `clear_all_traffic` fail with a plain connectivity error rather than taking
  the session down. Per `ai-traffic.md` D4, `Capabilities` itself is not mutated mid-session (it
  is a frozen, resolved-once-at-`connect()` value) — this is a real, disclosed gap versus the
  ideal of a control that disables itself the instant the bridge dies; see that design's §10.1.
- The bridge enforces its own capacity (`MAX_ENTITIES = 19` in `PI_OISBridge.py`, mirroring
  X-Plane's historical multiplayer-slot count for test realism) and is the source of truth for
  "how many slots are actually free," per D6 — the adapter never guesses a limit independently.
