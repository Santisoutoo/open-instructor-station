"""X-Plane execution for the cockpit control catalog (docs/designs/cockpit-control-catalog.md §5).

Kept out of ``xplane_adapter.py`` for the same reason ``camera_commands.py`` and
``failure_datarefs.py`` are: that module is already large, and this is one
self-contained concern — catalog directory loading, live detection by dataref
probe (D5), lazy per-name binding resolution with its cache (D6), the
aircraft-change hook (D7) and the five per-kind executors (D2, §5.5).

:class:`CockpitRuntime` never imports :class:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter`
— it talks to it only through :class:`CockpitHost`, a small structural
protocol, so nothing here needs to know that module's shape and there is no
import cycle. ``adapters/xplane/xplane_adapter.py`` owns one
``CockpitRuntime`` instance per connection and is the only caller.

No dataref name lives in ``core/`` (hard rule 2); this module and
``adapters/xplane/cockpit_catalogs/*.yaml`` are where the Zibo's paths
actually appear.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

import httpx

from core.cockpit.actuation import (
    dial_confirmed,
    is_on,
    selector_index,
    selector_steps,
    toggle_needs_press,
    validate_actuation,
)
from core.cockpit.catalog import load_all_catalogs, publish
from core.cockpit.errors import (
    CockpitCatalogInactive,
    CockpitControlUnknown,
    CockpitPreconditionUnmet,
    CockpitWriteRejected,
)
from core.cockpit.models import (
    CockpitActuation,
    CockpitActuationResult,
    CockpitCatalog,
    CockpitCatalogDocument,
    CockpitControlDefinition,
    CockpitControlState,
    CockpitStateSnapshot,
    CockpitValue,
)
from core.cockpit.preconditions import referenced_control_ids, unmet_preconditions

__all__ = [
    "COCKPIT_CATALOGS_DIR",
    "COCKPIT_READBACK_ATTEMPTS",
    "COCKPIT_READBACK_GAP_S",
    "CockpitHost",
    "CockpitRuntime",
]

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: Every catalog directory this adapter ships, one subdirectory per aircraft
#: (§5.1). Read as ``cockpit_controls.COCKPIT_CATALOGS_DIR`` at connect() time
#: — never imported by name into ``xplane_adapter.py`` — so
#: ``tests/adapters/test_xplane_cockpit.py`` can monkeypatch the module
#: attribute and have the adapter actually see the patched value (§8.4).
COCKPIT_CATALOGS_DIR: Path = Path(__file__).resolve().parent / "cockpit_catalogs"

#: §5.5's read-back window: up to this many reads, spaced this far apart,
#: before a write is declared unconfirmed (``CockpitWriteRejected``, D8).
#: Module constants rather than inline literals so a slow suite can
#: monkeypatch the gap to ``0``.
COCKPIT_READBACK_ATTEMPTS = 4
COCKPIT_READBACK_GAP_S = 0.15

#: The array-element suffix a binding string may carry, e.g.
#: ``"laminar/B738/ap/nav_status[0]"`` (§3.2's ``CockpitBinding`` docstring).
_INDEX_SUFFIX = re.compile(r"^(?P<base>.+)\[(?P<index>\d+)\]$")

#: D7's second signal: a 404 naming one of these error codes means a
#: previously-resolved id no longer exists (a plugin reload, most likely),
#: never that the path was never valid — that case is already handled by
#: :func:`_lookup_id` returning ``None`` before any id is cached.
_STALE_ID_ERROR_CODES = frozenset({"invalid_dataref_id", "invalid_command_id"})


class CockpitHost(Protocol):
    """The slice of :class:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter`
    :class:`CockpitRuntime` needs. Structural — no import of that class here.
    """

    def _require_client(self) -> httpx.AsyncClient: ...

    async def _read_by_id(self, dataref_id: int) -> Any: ...

    async def _write_by_id(
        self, dataref_id: int, value: float | int | bool, index: int | None = None
    ) -> None: ...

    async def _activate_by_id(self, command_id: int) -> None: ...

    async def _read_acf_relative_path(self) -> str | None: ...


class _StaleBinding(Exception):
    """Internal signal: a resolved id was rejected by the sim (D7's second signal).

    Never escapes :class:`CockpitRuntime` — caught by the one retry wrapper
    each public method installs, which re-detects and replays the whole
    operation exactly once.
    """


def _split_index(path: str) -> tuple[str, int | None]:
    """Split ``"dataref/path[3]"`` into ``("dataref/path", 3)``; no suffix -> ``(path, None)``."""
    match = _INDEX_SUFFIX.match(path)
    if match is None:
        return path, None
    return match.group("base"), int(match.group("index"))


async def _lookup_id(
    client: httpx.AsyncClient, collection: Literal["datarefs", "commands"], path: str
) -> int | None:
    """The numeric id X-Plane gives one dataref/command path, or ``None`` if it has none.

    The generalised sibling of
    :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter._lookup_command_id`
    (issue #217, §5.2's ``_lookup_id``): a ``filter[name]`` miss on either
    ``/api/v2/datarefs`` or ``/api/v2/commands`` answers a bare **404** on the
    real Web API — confirmed live for commands (issue #217) and for datarefs
    (``docs/research/zibo-737-autopilot-dataref-mapping.md`` §7). Any other
    error status still propagates.

    Matches the returned entry's own ``name`` against ``path`` rather than
    trusting entry order or an empty check alone, so a test double that
    answers ``filter[name]`` with more than the one matching row (or the
    whole index) cannot make a probe pass for the wrong reason.
    """
    response = await client.get(f"/api/v2/{collection}", params={"filter[name]": path})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    for entry in response.json().get("data", []):
        if entry.get("name") == path:
            return int(entry["id"])
    return None


def _coerce_value(raw: Any) -> CockpitValue | None:
    """A raw JSON-decoded dataref value as a :data:`CockpitValue`, or ``None``.

    ``bool`` is checked before ``int``/``float`` deliberately — Python's
    ``bool`` is an ``int`` subclass, and X-Plane booleans arrive as ``0``/``1``
    ints, so without the explicit check every toggle would coerce to ``int``
    instead of staying ``bool``-shaped where the sim already sent one.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float, str)):
        return raw
    return None


def published_value(
    control: CockpitControlDefinition, value: CockpitValue | None
) -> CockpitValue | None:
    """The value the catalog *publishes* for a control, from what the sim read.

    A toggle's read binding is a dataref, and the Web API reports every numeric
    dataref as a float — ``1.0`` for a flight director that is on. Inside the
    adapter that is fine (:func:`core.cockpit.actuation.is_on` compares it to
    the binding's ``on_value``), but the binding never leaves the adapter (D3),
    so a client cannot make that comparison: the generic Cockpit panel showed
    "Unknown" for every live toggle and judged every ``fd_capt == true``
    precondition unmet (issue #253's live pass, 2026-09-04). A toggle's
    published state is therefore the ``bool`` :func:`is_on` yields — the same
    shape ``CockpitActuation`` demands on the way in. Every other kind passes
    through untouched; ``None`` stays "unknown".
    """
    if value is None or control.kind != "toggle":
        return value
    return is_on(value, control.binding.on_value)


def _is_stale_binding_error(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code != 404:
        return False
    try:
        body = exc.response.json()
    except ValueError:
        return False
    return body.get("error_code") in _STALE_ID_ERROR_CODES


def _parked_reason(document: CockpitCatalogDocument, control_id: str) -> str | None:
    for entry in document.parked:
        if entry.control_id == control_id:
            return entry.reason
    return None


class CockpitRuntime:
    """Live state for the cockpit control catalog on one X-Plane connection.

    Owned exclusively by :class:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter`
    — one instance per connection, replaced (never mutated back to empty) on
    :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.disconnect`.
    """

    def __init__(self) -> None:
        #: Every catalog directory this build ships, loaded once at connect()
        #: (§5.2). Detection re-runs (D7) against this same tuple — the YAML
        #: never changes mid-session.
        self._documents: tuple[CockpitCatalogDocument, ...] = ()
        self._active: CockpitCatalogDocument | None = None
        #: 0 before any detection (CockpitCatalog.revision's own contract);
        #: bumped on every (re)detection, hit or miss (§5.2).
        self._revision: int = 0
        self._last_path: str | None = None
        self._detection_note: str | None = None
        self._no_catalog_reason: str | None = None
        #: (collection, base_path) -> resolved id, or ``None`` for "looked up
        #: this revision, does not resolve" (D6). Cleared wholesale on every
        #: (re)detection — the cheapest correct invalidation, and the one D7
        #: already prescribes.
        self._ids: dict[tuple[str, str], int | None] = {}

    @property
    def active_document(self) -> CockpitCatalogDocument | None:
        """The currently detected catalog document, or ``None``.

        Used by :meth:`XPlaneSimAdapter._write_autopilot`'s D11 hook to reach
        ``setup_overrides`` without this module knowing anything about
        ``AircraftSetup``.
        """
        return self._active

    def load_catalogs(self, root: Path) -> None:
        """Load every catalog directory under ``root`` (§5.2). Call once, at connect().

        A directory that fails to load is logged and skipped — never fails
        the connect (the scenario loader's posture, carried over by
        ``core.cockpit.catalog.load_all_catalogs``).
        """
        documents, errors = load_all_catalogs(root)
        for error in errors:
            logger.warning("cockpit catalog %s failed to load: %s", error.path, error.error)
        self._documents = documents

    # -- Detection and the aircraft-change hook (D5, D7) -------------------

    async def ensure_current(self, host: CockpitHost) -> None:
        """D7: re-detect only when the aircraft looks like it changed.

        ``acf_relative_path`` unavailable degrades to "always re-detect" —
        one extra round trip per cockpit call, and still correct (§5.2).
        """
        current_path = await host._read_acf_relative_path()
        if current_path is None or current_path != self._last_path:
            await self._detect(host, current_path)

    async def force_refresh(self, host: CockpitHost) -> CockpitCatalog:
        """``refresh_cockpit_catalog()``: step 2 of D7, unconditionally."""
        current_path = await host._read_acf_relative_path()
        await self._detect(host, current_path)
        return self._build_catalog()

    async def _detect(self, host: CockpitHost, path: str | None) -> None:
        """Probe every loaded document's ``detect.dataref_exists``; the first hit wins (D5)."""
        self._ids.clear()
        self._revision += 1
        self._last_path = path
        client = host._require_client()
        for document in self._documents:
            found = await _lookup_id(client, "datarefs", document.detect.dataref_exists)
            if found is not None:
                self._active = document
                self._detection_note = (
                    f"Probed {document.detect.dataref_exists!r} — found; "
                    f"aircraft path {path or 'unknown'}."
                )
                self._no_catalog_reason = None
                return
        self._active = None
        self._detection_note = None
        self._no_catalog_reason = (
            f"No cockpit catalog matched the loaded aircraft ({path or 'path unknown'})."
        )

    def _build_catalog(self) -> CockpitCatalog:
        if self._active is None:
            return CockpitCatalog(
                supported=True,
                reason=self._no_catalog_reason,
                aircraft=None,
                revision=self._revision,
                detection_note=self._detection_note,
                panels=[],
                controls=[],
                parked=[],
            )
        return publish(self._active, revision=self._revision, detection_note=self._detection_note)

    async def get_catalog(self, host: CockpitHost) -> CockpitCatalog:
        await self.ensure_current(host)
        return self._build_catalog()

    # -- Binding resolution and I/O (D6, D8) --------------------------------

    async def _resolve(
        self, host: CockpitHost, collection: Literal["datarefs", "commands"], path: str
    ) -> tuple[int, int | None]:
        base_path, index = _split_index(path)
        cache_key = (collection, base_path)
        if cache_key not in self._ids:
            client = host._require_client()
            self._ids[cache_key] = await _lookup_id(client, collection, base_path)
        resolved = self._ids[cache_key]
        if resolved is None:
            raise CockpitWriteRejected(f"{base_path!r} does not resolve on this aircraft.")
        return resolved, index

    async def _read_binding(self, host: CockpitHost, path: str) -> Any:
        dataref_id, index = await self._resolve(host, "datarefs", path)
        try:
            raw = await host._read_by_id(dataref_id)
        except httpx.HTTPStatusError as exc:
            if _is_stale_binding_error(exc):
                raise _StaleBinding from exc
            raise
        if index is not None:
            if not isinstance(raw, list) or index >= len(raw):
                return None
            return raw[index]
        return raw

    async def _write_binding(self, host: CockpitHost, path: str, value: float | int | bool) -> None:
        dataref_id, index = await self._resolve(host, "datarefs", path)
        try:
            await host._write_by_id(dataref_id, value, index=index)
        except httpx.HTTPStatusError as exc:
            if _is_stale_binding_error(exc):
                raise _StaleBinding from exc
            raise

    async def _activate_binding(self, host: CockpitHost, path: str) -> None:
        command_id, _ = await self._resolve(host, "commands", path)
        try:
            await host._activate_by_id(command_id)
        except httpx.HTTPStatusError as exc:
            if _is_stale_binding_error(exc):
                raise _StaleBinding from exc
            raise

    async def _await_settle(self, settle_s: float) -> None:
        if settle_s > 0:
            await asyncio.sleep(settle_s)

    async def _await_readback_value(
        self,
        host: CockpitHost,
        path: str,
        is_confirmed: Callable[[CockpitValue | None], bool],
    ) -> tuple[CockpitValue | None, bool]:
        """§5.5's read-back window: up to :data:`COCKPIT_READBACK_ATTEMPTS` reads."""
        value: CockpitValue | None = None
        for attempt in range(COCKPIT_READBACK_ATTEMPTS):
            raw = await self._read_binding(host, path)
            value = _coerce_value(raw)
            if is_confirmed(value):
                return value, True
            if attempt < COCKPIT_READBACK_ATTEMPTS - 1:
                await asyncio.sleep(COCKPIT_READBACK_GAP_S)
        return value, False

    async def _read_soft(self, host: CockpitHost, control: CockpitControlDefinition) -> Any:
        """A control's value, degrading to ``None`` rather than raising (read_cockpit_states'
        and a precondition check's posture — "unknown is an answer", never a 502)."""
        if not control.readable:
            return None
        path = control.binding.read or control.binding.write
        if path is None:
            return None
        try:
            raw = await self._read_binding(host, path)
        except CockpitWriteRejected:
            return None
        return _coerce_value(raw)

    # -- Reads ---------------------------------------------------------------

    async def read_states(
        self, host: CockpitHost, control_ids: Sequence[str] | None
    ) -> CockpitStateSnapshot:
        await self.ensure_current(host)

        async def _do() -> CockpitStateSnapshot:
            document = self._active
            if document is None:
                return CockpitStateSnapshot(catalog_id=None, revision=self._revision, states=[])
            by_id = {control.control_id: control for control in document.controls}
            if control_ids is None:
                ids: list[str] = [
                    control.control_id for control in document.controls if control.readable
                ]
            else:
                ids = list(control_ids)
                for control_id in ids:
                    if control_id not in by_id:
                        raise CockpitControlUnknown(
                            control_id, _parked_reason(document, control_id)
                        )
            states = [
                CockpitControlState(
                    control_id=control_id,
                    value=published_value(
                        by_id[control_id], await self._read_soft(host, by_id[control_id])
                    ),
                )
                for control_id in ids
            ]
            return CockpitStateSnapshot(
                catalog_id=document.aircraft.catalog_id, revision=self._revision, states=states
            )

        return await self._retrying(host, _do)

    async def _retrying(self, host: CockpitHost, operation: Callable[[], Awaitable[_T]]) -> _T:
        """D7's second signal: one retry, after an unconditional re-detect."""
        try:
            return await operation()
        except _StaleBinding:
            await self.force_refresh(host)
            return await operation()

    # -- Actuation (D2, D8, D9, §5.5) ----------------------------------------

    async def actuate(
        self, host: CockpitHost, actuation: CockpitActuation
    ) -> CockpitActuationResult:
        await self.ensure_current(host)

        async def _do() -> CockpitActuationResult:
            document = self._active
            if document is None:
                raise CockpitCatalogInactive(
                    "No cockpit catalog is active for the loaded aircraft."
                )
            by_id = {control.control_id: control for control in document.controls}
            control = by_id.get(actuation.control_id)
            if control is None:
                raise CockpitControlUnknown(
                    actuation.control_id, _parked_reason(document, actuation.control_id)
                )
            validate_actuation(control, actuation)

            referenced = referenced_control_ids(control)
            current_values = {
                control_id: await self._read_soft(host, by_id[control_id])
                for control_id in referenced
            }
            unmet = unmet_preconditions(control, current_values)
            if unmet:
                raise CockpitPreconditionUnmet(
                    actuation.control_id, tuple(group.hint for group in unmet)
                )

            if control.kind == "toggle":
                actions_taken, value = await self._actuate_toggle(host, control, actuation)
            elif control.kind == "press":
                actions_taken, value = await self._actuate_press(host, control)
            elif control.kind == "dial":
                actions_taken, value = await self._actuate_dial(host, control, actuation)
            elif control.kind == "encoder":
                actions_taken, value = await self._actuate_encoder(host, control, actuation)
            else:
                actions_taken, value = await self._actuate_selector(host, control, actuation)

            return CockpitActuationResult(
                requested=actuation,
                state=CockpitControlState(
                    control_id=control.control_id, value=published_value(control, value)
                ),
                actions_taken=actions_taken,
                catalog_id=document.aircraft.catalog_id,
                revision=self._revision,
            )

        return await self._retrying(host, _do)

    async def _actuate_toggle(
        self, host: CockpitHost, control: CockpitControlDefinition, actuation: CockpitActuation
    ) -> tuple[int, CockpitValue | None]:
        """Research §1: press only when the read state disagrees (the guarded-toggle rule)."""
        assert control.binding.read is not None
        assert control.binding.press is not None
        current = _coerce_value(await self._read_binding(host, control.binding.read))
        requested = bool(actuation.value)
        if not toggle_needs_press(current, requested, control.binding.on_value):
            return 0, current

        await self._activate_binding(host, control.binding.press)
        await self._await_settle(control.binding.settle_s)
        value, confirmed = await self._await_readback_value(
            host,
            control.binding.read,
            lambda v: is_on(v, control.binding.on_value) == requested,
        )
        if not confirmed:
            raise CockpitWriteRejected(
                f"{control.control_id!r}: requested {requested}, read back {value!r} after "
                f"{COCKPIT_READBACK_ATTEMPTS} attempts."
            )
        return 1, value

    async def _actuate_press(
        self, host: CockpitHost, control: CockpitControlDefinition
    ) -> tuple[int, CockpitValue | None]:
        assert control.binding.press is not None
        await self._activate_binding(host, control.binding.press)
        await self._await_settle(control.binding.settle_s)
        return 1, None

    async def _actuate_dial(
        self, host: CockpitHost, control: CockpitControlDefinition, actuation: CockpitActuation
    ) -> tuple[int, CockpitValue | None]:
        assert control.binding.write is not None
        assert actuation.value is not None
        written = float(actuation.value)
        await self._write_binding(host, control.binding.write, written)
        await self._await_settle(control.binding.settle_s)
        # §5.7: the read binding may differ from the write (the mcp_speed
        # drum echo this rule exists for) and defaults to it when absent.
        read_path = control.binding.read or control.binding.write
        tolerance = control.readback_tolerance
        value, confirmed = await self._await_readback_value(
            host, read_path, lambda v: dial_confirmed(written, v, tolerance)
        )
        if not confirmed:
            raise CockpitWriteRejected(
                f"{control.control_id!r}: wrote {written}, read back {value!r} "
                f"(tolerance {tolerance})."
            )
        return 1, value

    async def _actuate_encoder(
        self, host: CockpitHost, control: CockpitControlDefinition, actuation: CockpitActuation
    ) -> tuple[int, CockpitValue | None]:
        assert actuation.delta is not None
        assert control.binding.inc is not None
        assert control.binding.dec is not None
        command_path = control.binding.inc if actuation.delta > 0 else control.binding.dec
        # Sequential, never concurrent (§5.5): X-Plane serialises commands per
        # frame and a burst of concurrent activations can coalesce.
        for _ in range(abs(actuation.delta)):
            await self._activate_binding(host, command_path)
        await self._await_settle(control.binding.settle_s)
        if not control.readable or control.binding.read is None:
            return 1, None
        value = _coerce_value(await self._read_binding(host, control.binding.read))
        return 1, value

    async def _actuate_selector(
        self, host: CockpitHost, control: CockpitControlDefinition, actuation: CockpitActuation
    ) -> tuple[int, CockpitValue | None]:
        assert actuation.value is not None
        assert control.options is not None
        assert control.binding.read is not None
        read_path = control.binding.read
        target_index = selector_index(control, actuation.value)
        if target_index is None:
            raise CockpitWriteRejected(
                f"{control.control_id!r}: {actuation.value!r} is not among its options."
            )

        if control.binding.write is not None:
            if isinstance(actuation.value, str):
                # X-Plane's dataref write endpoint takes numbers, not text —
                # a string-valued selector option has nothing to write here.
                # No catalog ships one yet (§10.6 flags selectors as
                # otherwise unverified), so this is a defensive refusal, not
                # a case Wave 1 Track B needs to support.
                raise CockpitWriteRejected(
                    f"{control.control_id!r}: string-valued selector writes are not "
                    "supported by this adapter."
                )
            await self._write_binding(host, control.binding.write, actuation.value)
            await self._await_settle(control.binding.settle_s)
            value, confirmed = await self._await_readback_value(
                host, read_path, lambda v: selector_index(control, v) == target_index
            )
            if not confirmed:
                raise CockpitWriteRejected(
                    f"{control.control_id!r}: wrote {actuation.value!r}, read back {value!r}."
                )
            return 1, value

        # inc/dec stepping (D2's selector shape, §5.5): bounded, never wraps.
        assert control.binding.inc is not None
        assert control.binding.dec is not None
        current_value = _coerce_value(await self._read_binding(host, read_path))
        current_index = selector_index(control, current_value)
        if current_index is None:
            # An unreadable/unexpected current value: 0 is the safest assumed
            # start — the read-back loop below is what actually decides.
            current_index = 0
        if current_index == target_index:
            return 0, current_value

        steps = selector_steps(current_index, target_index, len(control.options))
        direction_path = control.binding.inc if steps > 0 else control.binding.dec
        max_steps = len(control.options)
        for actions in range(1, max_steps + 1):
            await self._activate_binding(host, direction_path)
            await self._await_settle(control.binding.settle_s)
            stepped_value = _coerce_value(await self._read_binding(host, read_path))
            if selector_index(control, stepped_value) == target_index:
                return actions, stepped_value
        raise CockpitWriteRejected(
            f"{control.control_id!r}: did not reach {actuation.value!r} after {max_steps} steps."
        )
