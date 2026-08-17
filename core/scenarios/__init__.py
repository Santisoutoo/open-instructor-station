"""Sim-agnostic Flight Scenario Generator vocabulary.

``core.scenarios`` composes the request/setup models of every other manager —
Weather (:mod:`core.weather.models`), Failures (:mod:`core.failures`),
Position (:mod:`core.placements`) and Fuel & Payload's raw
:class:`~core.models.AircraftSetup` fields — into one validated document,
:class:`~core.scenarios.models.ScenarioDocument`. Nothing scenario-specific is
reinvented: a typo'd field fails validation exactly as it would over that
manager's own REST endpoint. No HTTP, no dataref name, no simulator import.

``models.py`` and ``preflight.py`` are what the loader and the engine both
depend on; ``loader.py`` (the directory scan) and ``data/`` (the 14 shipped
YAML files) build on top of them.

The design this package implements is ``docs/designs/scenario-generator.md``.
"""

from __future__ import annotations
