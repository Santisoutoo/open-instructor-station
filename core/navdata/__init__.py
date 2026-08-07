"""Read-only access to the navigation world: the static data on disk.

``core.navdata`` is the counterpart of ``core.sim_adapter``, and the two are
deliberately unrelated. :class:`~core.navdata.provider.NavdataProvider` reads
airports, runways, parking, navaids, fixes, holds and instrument procedures from
the data files the user already has installed; it has no connection, no
lifecycle and no capabilities, and it is equally useful with no simulator
running at all.

Selecting a provider is independent of selecting an adapter: the fake simulator
with real navdata is the intended development loop, and the real simulator with
in-memory navdata is how repositioning is tested without depending on anyone's
install.

The design this package implements is ``docs/designs/navdata-provider.md``.
"""

from __future__ import annotations
