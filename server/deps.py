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

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.camera.store import CameraPositionStore, app_data_camera_positions_dir
from core.models import AirframeInfo
from core.navdata.provider import NavdataProvider
from core.profiles.paths import default_profiles_root
from core.profiles.store import ProfileStore
from core.sim_adapter import SimAdapter

__all__ = [
    "Settings",
    "get_adapter",
    "get_airframe_info",
    "get_camera_position_store",
    "get_navdata",
    "get_profile_store",
    "get_settings",
    "load_airframe_info",
    "reset_adapter",
    "reset_camera_position_store",
    "reset_navdata",
    "reset_profile_store",
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
    #: Where training profiles are stored. ``None`` uses the per-OS default
    #: (``core.profiles.paths.default_profiles_root``) — the same override
    #: convention ``navdata_root`` uses for navdata autodetection.
    profiles_root: str | None = None
    #: Where saved camera positions are stored. ``None`` uses the per-OS
    #: default (``core.camera.store.app_data_camera_positions_dir``). A
    #: separate setting from ``profiles_root`` because the two stores are
    #: independent managers (camera-manager.md D8), not one directory with two
    #: tenants.
    camera_positions_root: str | None = None
    # Bound to all interfaces on purpose: using the station from a tablet on
    # the same LAN is a first-class scenario.
    host: str = "0.0.0.0"
    port: int = 8000
    #: Whether the packaged executable should open a browser once the server
    #: answers. ``None`` means "not set" — ``server.__main__`` then falls back
    #: to "packaged runs open one, a source checkout does not". Explicit
    #: string spellings are parsed by :meth:`_parse_open_browser` rather than
    #: left to pydantic's own bool coercion: that coercion accepts more
    #: spellings than this ever did (``"y"``, ``"t"``), does not strip
    #: whitespace, and raises on anything else instead of treating it as
    #: false — three behaviour changes ``server.__main__``'s hand-rolled
    #: ``os.environ.get(...).strip().lower() in {...}`` check never had.
    open_browser: bool | None = None

    @field_validator("open_browser", mode="before")
    @classmethod
    def _parse_open_browser(cls, value: object) -> object:
        """Reproduce the exact hand-rolled parsing this field replaces.

        Only ``"1"``, ``"true"``, ``"yes"`` and ``"on"`` — case-insensitive,
        surrounding whitespace stripped — count as true. Every other string,
        including ``"0"``/``"false"``/``"no"``/``"off"`` and anything
        unrecognised, is false. Never raises on an unrecognised spelling.
        """
        if not isinstance(value, str):
            return value
        return value.strip().lower() in {"1", "true", "yes", "on"}


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


#: What the loaded airframe is known to be, read once at adapter connect. A
#: module-level value next to the adapter singleton rather than an ``lru_cache``
#: because it is *written* by the lifespan, not computed on first read — the
#: all-``None`` model is the honest answer until a connect has happened.
_airframe_info: AirframeInfo = AirframeInfo()


async def load_airframe_info() -> AirframeInfo:
    """Read the loaded airframe from the connected adapter and cache it.

    Called from the app lifespan, immediately after
    :meth:`~core.sim_adapter.SimAdapter.connect` succeeds. This is the **only**
    place the airframe is read from the simulator: everything downstream —
    notably the approach-category derivation in the position routes (issue
    #82) — reads the cache through :func:`get_airframe_info` instead, so no
    request handler ever awaits the simulator for it.
    """
    global _airframe_info
    _airframe_info = await get_adapter().get_airframe()
    return _airframe_info


def get_airframe_info() -> AirframeInfo:
    """The airframe cached at adapter connect. Synchronous, no simulator I/O.

    ``preview_placement`` is deliberately ``def`` and never awaits the
    simulator, which is why this is a cache read and not a call.

    **The cache can be stale.** The loaded airframe changes rarely, but a user
    who swaps aircraft mid-session is served the *previous* aircraft's stall
    speed — and therefore its approach category — until the server reconnects.
    That is accepted: the failure mode is exactly the pre-#82 status quo, a
    wrong-but-disclosed category default, and the preview's notes still say
    where the number came from. A lazy TTL re-read is the noted follow-up if
    mid-session swaps turn out to matter in practice.

    Before any connect (or after a failed one) this is the all-``None`` model,
    which downstream reads as "unknown" and degrades to the category B default.
    """
    return _airframe_info


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


def _build_profile_store(settings: Settings) -> ProfileStore:
    """Construct the profile store named by ``settings``. Performs no I/O.

    Constructing a :class:`~core.profiles.store.ProfileStore` never creates
    its directory (that module's own import-safety guarantee) — ``profiles_root``
    is resolved here purely to decide *where* it would write, the same
    composition-root reasoning ``_build_navdata`` uses for the navdata root.
    """
    root = Path(settings.profiles_root) if settings.profiles_root else default_profiles_root()
    return ProfileStore(root)


@lru_cache(maxsize=1)
def get_profile_store() -> ProfileStore:
    """Return the process-wide training-profile store singleton."""
    return _build_profile_store(get_settings())


def _build_camera_position_store(settings: Settings) -> CameraPositionStore:
    """Construct the saved-camera-position store. Performs no I/O.

    Same composition-root reasoning as :func:`_build_profile_store`:
    constructing a :class:`~core.camera.store.CameraPositionStore` never
    creates its directory, so resolving the root here only decides *where* it
    would write.
    """
    root = (
        Path(settings.camera_positions_root)
        if settings.camera_positions_root
        else app_data_camera_positions_dir()
    )
    return CameraPositionStore(root)


@lru_cache(maxsize=1)
def get_camera_position_store() -> CameraPositionStore:
    """Return the process-wide saved-camera-position store singleton."""
    return _build_camera_position_store(get_settings())


def reset_adapter() -> None:
    """Drop every cached singleton — settings, adapter, navdata, both stores, airframe.

    All of them together: each store and provider is built from the same
    ``Settings`` object, so a test that reconfigures one and leaves another
    cached would be running against a mismatched pair — and the airframe was
    read from the adapter being dropped, so keeping it would serve the old
    simulator's aircraft against the new one.
    """
    global _airframe_info
    get_adapter.cache_clear()
    get_navdata.cache_clear()
    get_profile_store.cache_clear()
    get_camera_position_store.cache_clear()
    get_settings.cache_clear()
    _airframe_info = AirframeInfo()


def reset_navdata() -> None:
    """Drop only the cached navdata provider, keeping the adapter connected."""
    get_navdata.cache_clear()


def reset_profile_store() -> None:
    """Drop only the cached profile store. The ``reset_navdata()`` pattern, for tests."""
    get_profile_store.cache_clear()


def reset_camera_position_store() -> None:
    """Drop only the cached camera-position store. The ``reset_navdata()`` pattern, for tests."""
    get_camera_position_store.cache_clear()
