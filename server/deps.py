"""Settings and dependency wiring.

Every setting is overridable through an ``OIS_``-prefixed environment variable,
e.g. ``OIS_ADAPTER=xplane OIS_XPLANE_HOST=192.168.1.20``.

**The simulator and the navdata are chosen independently**, because they are
independent: the fake adapter reading a real X-Plane install is the intended
development loop, and the real adapter over in-memory navdata is how
repositioning is tested without depending on anyone's install. Nothing here
couples ``OIS_ADAPTER`` to ``OIS_NAVDATA``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from core.navdata.provider import NavdataProvider
from core.sim_adapter import SimAdapter

__all__ = [
    "Settings",
    "get_adapter",
    "get_navdata",
    "get_settings",
    "reset_adapter",
    "reset_navdata",
]

AdapterName = Literal["fake", "xplane"]
NavdataProviderName = Literal["xplane_native", "in_memory"]


class Settings(BaseSettings):
    """Runtime configuration, read from the environment."""

    model_config = SettingsConfigDict(env_prefix="OIS_", env_file=".env", extra="ignore")

    adapter: AdapterName = "fake"
    xplane_host: str = "localhost"
    xplane_port: int = 8086
    navdata: NavdataProviderName = "xplane_native"
    #: The X-Plane installation to read navdata from. ``None`` autodetects.
    navdata_root: str | None = None
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


def _build_navdata(settings: Settings) -> NavdataProvider:
    """Construct the navdata provider named by ``settings``.

    Discovering the X-Plane root touches the filesystem, which the provider
    protocol forbids a *provider* from doing in its constructor. Doing it here
    instead is deliberate and is not the same rule: this is the composition
    root, it runs once behind an ``lru_cache``, and a handful of ``is_dir``
    checks is what "where is the install" costs. The provider still autodetects
    on its own when nothing is configured — the root is resolved here only to
    give the procedure source a path, since ``XPNativeCifpSource`` needs a
    concrete tree and the provider does not build one for itself.
    """
    if settings.navdata == "in_memory":
        from core.navdata.in_memory import InMemoryNavdataProvider

        return InMemoryNavdataProvider()

    from core.navdata.sources import discover_xplane_root
    from core.navdata.xplane_native.cifp import XPNativeCifpSource
    from core.navdata.xplane_native.provider import XPNativeNavdataProvider

    configured = Path(settings.navdata_root) if settings.navdata_root else None
    root = discover_xplane_root(configured)
    if root is None:
        # No install found. The provider reports "unavailable" with a reason and
        # the UI disables the panel — it never discovers this by failing a query.
        return XPNativeNavdataProvider(configured)

    # The procedure source resolves its legs' 4-part ARINC keys through the
    # provider's own index, so the two are mutually dependent. The closure binds
    # late, after both exist; a leg parsed before the index is built resolves to
    # None, which is exactly the "fix did not resolve" case the leg model
    # already carries a reason for.
    holder: dict[str, NavdataProvider] = {}
    cifp = XPNativeCifpSource(root, resolve_fix=lambda ref: holder["provider"].resolve_fix(ref))
    provider = XPNativeNavdataProvider(root, cifp_source=cifp)
    holder["provider"] = provider
    return provider


@lru_cache(maxsize=1)
def get_navdata() -> NavdataProvider:
    """Return the process-wide navdata provider singleton.

    Constructing a provider builds no index; ``POST /api/navdata/index`` does,
    and until it has run the provider honestly reports itself as unavailable.
    """
    return _build_navdata(get_settings())


def reset_adapter() -> None:
    """Drop the cached settings, adapter and navdata provider.

    All three together: they are read from the same ``Settings`` object, so a
    test that reconfigures one and leaves another cached would be running
    against a mismatched pair.
    """
    get_adapter.cache_clear()
    get_navdata.cache_clear()
    get_settings.cache_clear()


def reset_navdata() -> None:
    """Drop only the cached navdata provider, keeping the adapter connected."""
    get_navdata.cache_clear()
