"""Readers for the X-Plane data file formats.

This package names a **file format**, not a simulator: the Laminar
``apt.dat 1200`` / ``earth_* 1200`` / CIFP ARINC-424-subset specification,
versioned by the header numbers in the files themselves. A user can point the
provider at an X-Plane data tree while flying something else, and that works.
``core/navdata/msfs_bgl/`` will sit beside it.

**This file stays empty of exports on purpose.** Its modules are written by
independent parallel tracks — the CIFP parser and the ``apt.dat``/``earth_*``
indexer — and a package ``__init__`` that re-exported from both would be the one
file both tracks had to edit. Import from the leaf modules instead.
"""

from __future__ import annotations
