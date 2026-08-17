"""Sim-agnostic Flight Scenario Generator vocabulary.

``core.scenarios`` composes the request/setup models of every other manager —
Weather (:mod:`core.weather.models`), Failures (:mod:`core.failures`),
Position (:mod:`core.placements`) and Fuel & Payload's raw
:class:`~core.models.AircraftSetup` fields — into one validated document,
:class:`~core.scenarios.models.ScenarioDocument`. Nothing scenario-specific is
reinvented: a typo'd field fails validation exactly as it would over that
manager's own REST endpoint. No HTTP, no dataref name, no simulator import.

The directory scan (``core/scenarios/loader.py``) and the shipped YAML files
(``core/scenarios/data/``) are a later, separate track — this package
currently carries only the document model (``models.py``) and the capability
pre-flight check (``preflight.py``), the two pieces the loader and the engine
both depend on.

The design this package implements is ``docs/designs/scenario-generator.md``.
"""

from __future__ import annotations
