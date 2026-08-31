"""Training Profiles — a saved scenario with a name and metadata.

Per ``docs/designs/training-profiles.md`` (see the design's own "Addendum:
as-built" section for the one judgement call this package resolved
differently from the original draft): :class:`~core.profiles.models.TrainingProfile`
embeds :class:`core.scenarios.models.ScenarioDocument` directly rather than
redeclaring a parallel ``ProfileScenario``/``ProfilePlacement`` family — the
Flight Scenario Generator had already built exactly the "saved scenario"
model this manager needs by the time this package was written.

``models.py`` is the wire shape; ``store.py`` is the flat-JSON-directory
storage layer; ``paths.py`` computes where that directory lives on each OS.
No HTTP, no dataref name, no simulator import — applying a profile is
orchestrated in ``server/profile_routes.py`` (D10), never here.
"""

from __future__ import annotations
