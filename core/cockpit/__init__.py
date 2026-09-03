"""Sim-agnostic cockpit control catalog vocabulary, loader and pure logic.

``core.cockpit`` is manager 6's "aircraft-specific override layer keyed on
the loaded aircraft": a data-driven, per-aircraft catalog of cockpit
controls — each with an id, a label, a panel group, a control kind, an
adapter-private binding, a read-back and preconditions — so that adding a
control to an aircraft's catalog is a data edit, never a code change.

* ``models.py`` — the schema (§3.1), the file-side models (§3.2) and the wire
  models (§3.3/§3.4). No file I/O, no HTTP, no simulator import.
* ``catalog.py`` — the YAML directory loader (§6.1), the ``core/scenarios/
  loader.py`` pattern extended to merge several files into one document.
* ``actuation.py`` / ``preconditions.py`` — pure rules an adapter drives by
  kind (§6.2/§6.3): the guarded-toggle rule, read-back confirmation,
  selector stepping, precondition evaluation and ordering.
* ``errors.py`` — adapter-agnostic exceptions the server maps to HTTP status.

No dataref name, no command path, no simulator import anywhere in this
package (hard rule 2) — every binding string is opaque here (D3).

The design this package implements is
``docs/designs/cockpit-control-catalog.md``.
"""

from __future__ import annotations
