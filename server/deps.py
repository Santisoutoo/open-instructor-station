"""Settings and dependency wiring.

Every setting is overridable through an ``OIS_``-prefixed environment variable,
e.g. ``OIS_ADAPTER=xplane OIS_XPLANE_HOST=192.168.1.20``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from core.sim_adapter import SimAdapter

__all__ = ["Settings", "get_adapter", "get_settings", "reset_adapter"]

AdapterName = Literal["fake", "xplane"]


class Settings(BaseSettings):
    """Runtime configuration, read from the environment."""

    model_config = SettingsConfigDict(env_prefix="OIS_", env_file=".env", extra="ignore")

    adapter: AdapterName = "fake"
    xplane_host: str = "localhost"
    xplane_port: int = 8086
    # Bound to all interfaces on purpose: using the station from a tablet on
    # the same LAN is a first-class scenario.
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def _build_adapter(settings: Settings) -> SimAdapter:
    """Construct the adapter named by ``settings``. Performs no I/O."""
    if settings.adapter == "xplane":
        from adapters.xplane import XPlaneSimAdapter

        return XPlaneSimAdapter(host=settings.xplane_host, port=settings.xplane_port)

    from adapters.fake import FakeSimAdapter

    return FakeSimAdapter()


@lru_cache(maxsize=1)
def get_adapter() -> SimAdapter:
    """Return the process-wide adapter singleton for the configured simulator.

    Constructing an adapter never opens a connection; the app's lifespan is
    what awaits :meth:`~core.sim_adapter.SimAdapter.connect`.
    """
    return _build_adapter(get_settings())


def reset_adapter() -> None:
    """Drop the cached settings and adapter. For tests and for reconfiguration."""
    get_adapter.cache_clear()
    get_settings.cache_clear()
