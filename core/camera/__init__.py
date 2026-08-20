"""Sim-agnostic camera vocabulary.

``core.camera`` is the counterpart of ``core.failures``/``core.pushback`` for
manager 10: a closed five-view catalogue, a per-view adapter support manifest,
and the aircraft-relative offset model a saved custom camera position is built
from. No HTTP, no dataref name, no simulator import.

Alongside the vocabulary the ``SimAdapter`` contract needs
(``models.py``), the package carries the geometry that resolves an
aircraft-relative offset against a live aircraft state — and back
(``geometry.py``, D4/D5) — and the on-disk store the instructor's saved
positions live in (``store.py``, D8). Neither touches a simulator.

The design this package implements is ``docs/designs/camera-manager.md``.
"""

from __future__ import annotations
