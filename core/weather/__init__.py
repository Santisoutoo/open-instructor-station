"""Sim-agnostic weather vocabulary.

``core.weather`` is the counterpart of ``core.failures`` for manager 3: a typed
read model (:class:`~core.weather.models.WeatherState`), a sparse write model
(:class:`~core.weather.models.WeatherSetup`) and the layer models both are
built from. No HTTP, no dataref name, no simulator import.

The preset catalogue and its resolver (``core/weather/presets.py``) are a
later, separate track — this package currently carries only the vocabulary
the ``SimAdapter`` contract needs.

The design this package implements is ``docs/designs/weather-manager.md``.
"""

from __future__ import annotations
