# `bridge/` — Optional XPPython3 plugin

**Status: placeholder. Lands in Phase 3.** Nothing here is implemented yet.

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

## Notes for whoever builds it

- **XPPython3** is a third-party X-Plane plugin that runs Python plugins inside the sim. The user
  installs it themselves; the application never installs anything into their simulator.
- Keep the transport simple and local (the plugin and the station may be on the same machine or
  on the same LAN). Whatever it is, it is an implementation detail of `adapters/xplane/`.
- **Never copy code from third-party projects.** This is a private, proprietary project — no
  license file, no license headers.
- Fail soft: if the plugin disappears mid-session, the adapter flips `can_spawn_traffic` to
  `False` and the UI disables traffic controls. It does not take the session down.
