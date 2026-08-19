"""Sim-agnostic camera vocabulary.

``core.camera`` is the counterpart of ``core.failures``/``core.pushback`` for
manager 10: a closed five-view catalogue, a per-view adapter support manifest,
and the aircraft-relative offset model a saved custom camera position is built
from. No HTTP, no dataref name, no simulator import.

The geometry that resolves an offset against a live aircraft state
(``core/camera/geometry.py``) and the on-disk saved-position store
(``core/camera/store.py``) are a later, separate track (Track A) — this
package currently carries only the vocabulary the ``SimAdapter`` contract
needs.

The design this package implements is ``docs/designs/camera-manager.md``.
"""

from __future__ import annotations
