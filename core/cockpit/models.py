"""The cockpit control catalog's vocabulary — sim-agnostic, no dataref name.

Per ``docs/designs/cockpit-control-catalog.md`` §3. Three families of model:

* §3.1 — the catalog SCHEMA: what a control declares (:class:`CockpitControlSpec`
  and its supporting vocabulary), published binding-free to the server and UI.
* §3.2 — the FILE-side models: :class:`CockpitBinding` (opaque adapter-private
  strings — a dataref path, a command path; core validates only which fields
  are present per kind, never their content, per hard rule 2) and
  :class:`CockpitCatalogDocument`, one aircraft's whole catalog after the
  loader has merged its directory.
* §3.3/§3.4 — the WIRE models: state snapshots, actuation requests/results,
  and the manifest :meth:`~core.sim_adapter.SimAdapter.get_cockpit_catalog`
  answers.

No file I/O, no HTTP, no simulator import here — that is ``core.cockpit.catalog``
(the loader) and the adapters.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models import AircraftSetup

__all__ = [
    "CATALOG_ID_PATTERN",
    "CONTROL_ID_PATTERN",
    "CockpitActuation",
    "CockpitActuationResult",
    "CockpitAircraft",
    "CockpitBinding",
    "CockpitCatalog",
    "CockpitCatalogDocument",
    "CockpitCatalogManifest",
    "CockpitControlDefinition",
    "CockpitControlKind",
    "CockpitControlSpec",
    "CockpitControlState",
    "CockpitDetection",
    "CockpitPanel",
    "CockpitStateSnapshot",
    "CockpitUnit",
    "CockpitValue",
    "ControlCondition",
    "ParkedControl",
    "PreconditionGroup",
    "SelectorOption",
]

#: The five control kinds, closed (D2).
CockpitControlKind = Literal["toggle", "press", "dial", "encoder", "selector"]

#: What a control's state or requested value can be. Declaration order matters
#: to pydantic's smart-union matching: ``bool`` before ``int`` before
#: ``float``, so a JSON ``true`` stays a bool and is never coerced to ``1``.
CockpitValue = bool | int | float | str

#: Unit vocabulary for dial/encoder entries. Closed so the UI formats every one.
CockpitUnit = Literal[
    "ft", "kt", "mach", "deg", "fpm", "ratio", "count", "khz", "mhz", "psi", "units"
]

#: snake_case, e.g. ``mcp_alt``, ``fd_capt``.
CONTROL_ID_PATTERN = r"^[a-z0-9]+(?:_[a-z0-9]+)*$"
#: kebab-case, e.g. ``zibo-b738``.
CATALOG_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

#: Autopilot ``AircraftSetup`` field names whose Python type is ``bool | None``
#: — the only field shape ``setup_overrides`` may map onto a ``toggle`` control.
_AIRCRAFT_SETUP_BOOL_KIND: Literal["bool"] = "bool"
#: The only field shape ``setup_overrides`` may map onto a ``dial`` control.
_AIRCRAFT_SETUP_FLOAT_KIND: Literal["float"] = "float"


def _setup_field_kind(field_name: str) -> Literal["bool", "float"] | None:
    """The scalar type of an ``AircraftSetup`` field, or ``None`` when unknown.

    Only ``bool | None`` and ``float | None`` fields are recognised — the two
    shapes ``setup_overrides`` may target (D11: "a bool field maps to a
    toggle, a float field to a dial").
    """
    field = AircraftSetup.model_fields.get(field_name)
    if field is None:
        return None
    args = get_args(field.annotation)
    if bool in args or field.annotation is bool:
        return _AIRCRAFT_SETUP_BOOL_KIND
    if float in args or field.annotation is float:
        return _AIRCRAFT_SETUP_FLOAT_KIND
    return None


# ---------------------------------------------------------------------------
# §3.1 — the catalog schema
# ---------------------------------------------------------------------------


class CockpitPanel(BaseModel):
    """One group in the panel picker. Catalog-defined — different aircraft, different panels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    panel_id: str = Field(pattern=CONTROL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=40)
    order: int = Field(ge=0, description="Display order, ascending.")


class ControlCondition(BaseModel):
    """One member of a :class:`PreconditionGroup`'s ``any_of``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    equals: CockpitValue = Field(description="The state the referenced control must be in.")


class PreconditionGroup(BaseModel):
    """Satisfied when ANY condition holds. A control's list of groups must ALL hold (D9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    any_of: list[ControlCondition] = Field(min_length=1)
    hint: str = Field(
        min_length=1,
        max_length=120,
        description="Shown to the instructor when the group is unmet.",
    )


class SelectorOption(BaseModel):
    """One position of a ``selector`` control."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: int | str = Field(
        description="The value the read binding reports / the write binding takes."
    )
    label: str = Field(min_length=1, max_length=30)


class CockpitControlSpec(BaseModel):
    """The PUBLISHED half of a control — what the server and UI see. No binding (D3)."""

    model_config = ConfigDict(frozen=True)

    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=60)
    panel_id: str = Field(pattern=CONTROL_ID_PATTERN)
    kind: CockpitControlKind
    hint: str | None = Field(default=None, max_length=120)
    preconditions: list[PreconditionGroup] = Field(default_factory=list)
    readable: bool = Field(
        description="True when the adapter can report this control's state. Derived from the "
        "binding at load time: always True for toggle/dial/selector, False for press, "
        "binding-dependent for encoder."
    )
    # --- toggle ---
    on_label: str = "On"
    off_label: str = "Off"
    # --- dial / encoder ---
    unit: CockpitUnit | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = Field(
        default=None,
        gt=0.0,
        description="Dial: the UI stepper increment (NOT enforced on writes — X-Plane accepts "
        "any value; the sim rounds if it wants to). Encoder: the value change one click "
        "produces, in `unit`, for display.",
    )
    readback_tolerance: float = Field(
        default=0.0, ge=0.0, description="Dial: |read_back - written| allowed, in `unit`."
    )
    # --- encoder ---
    max_delta: int | None = Field(
        default=None, ge=1, le=200, description="Largest |delta| one actuation may request."
    )
    # --- selector ---
    options: list[SelectorOption] | None = Field(default=None, min_length=2)
    # --- provenance (D10) ---
    verified_on: date = Field(description="Date the entry was read-back confirmed on a live sim.")
    live_sweep: bool = Field(
        default=True,
        description="False when the generic live sweep must not flip this control (battery off, "
        "start levers, TO/GA). Requires live_sweep_note.",
    )
    live_sweep_note: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> CockpitControlSpec:
        """Per-kind required/forbidden field rules (§3.1's table)."""
        kind = self.kind
        dial_or_selector_fields = ("unit", "min_value", "max_value", "step", "max_delta", "options")

        if kind in ("toggle", "press"):
            for field_name in dial_or_selector_fields:
                if getattr(self, field_name) is not None:
                    raise ValueError(f"{kind!r} forbids field {field_name!r}.")
            if kind == "press" and (self.on_label != "On" or self.off_label != "Off"):
                raise ValueError("'press' forbids a non-default on_label/off_label.")
        elif kind == "dial":
            if self.unit is None or self.step is None:
                raise ValueError("'dial' requires unit, min_value, max_value and step.")
            if self.min_value is None or self.max_value is None:
                raise ValueError("'dial' requires unit, min_value, max_value and step.")
            if not self.min_value < self.max_value:
                raise ValueError("'dial' requires min_value < max_value.")
            if self.max_delta is not None or self.options is not None:
                raise ValueError("'dial' forbids max_delta/options.")
        elif kind == "encoder":
            if self.unit is None or self.step is None or self.max_delta is None:
                raise ValueError("'encoder' requires unit, step and max_delta.")
            if self.min_value is not None or self.max_value is not None or self.options is not None:
                raise ValueError("'encoder' forbids min_value/max_value/options.")
        elif kind == "selector":
            if self.options is None:
                raise ValueError("'selector' requires options.")
            values = [option.value for option in self.options]
            labels = [option.label for option in self.options]
            if len(set(values)) != len(values):
                raise ValueError("'selector' options must have unique values.")
            if len(set(labels)) != len(labels):
                raise ValueError("'selector' options must have unique labels.")
            for field_name in ("unit", "min_value", "max_value", "step", "max_delta"):
                if getattr(self, field_name) is not None:
                    raise ValueError(f"'selector' forbids field {field_name!r}.")

        if self.live_sweep is False and self.live_sweep_note is None:
            raise ValueError("live_sweep=False requires live_sweep_note.")
        return self


# ---------------------------------------------------------------------------
# §3.2 — the file-side models: binding and document
# ---------------------------------------------------------------------------


class CockpitBinding(BaseModel):
    """Adapter-private. Every field is an OPAQUE string to core/ (D3): a dataref path, a
    command path, an MSFS event — core validates only which fields are present per kind.
    An optional ``[i]`` suffix on ``read``/``write`` denotes an array element (adapter-parsed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    press: str | None = None
    read: str | None = None
    write: str | None = None
    inc: str | None = None
    dec: str | None = None
    on_value: float = Field(default=1.0, description="toggle: the `read` value meaning ON.")
    settle_s: float = Field(
        default=0.0, ge=0.0, le=5.0, description="Wait before the first read-back attempt."
    )


class CockpitControlDefinition(CockpitControlSpec):
    """A spec plus its binding — what a catalog FILE contains. ``readable`` is not written
    in files; the loader derives it from the binding and rejects a file that states it.
    """

    binding: CockpitBinding

    @model_validator(mode="after")
    def _validate_binding(self) -> CockpitControlDefinition:
        """Per-kind binding rules (§3.2's table)."""
        binding = self.binding
        kind = self.kind

        if kind == "toggle":
            if binding.press is None or binding.read is None:
                raise ValueError("'toggle' binding requires press and read.")
            if binding.write is not None or binding.inc is not None or binding.dec is not None:
                raise ValueError("'toggle' binding forbids write/inc/dec.")
        elif kind == "press":
            if binding.press is None:
                raise ValueError("'press' binding requires press.")
            if (
                binding.read is not None
                or binding.write is not None
                or binding.inc is not None
                or binding.dec is not None
            ):
                raise ValueError("'press' binding forbids read/write/inc/dec.")
        elif kind == "dial":
            if binding.write is None:
                raise ValueError("'dial' binding requires write.")
            if binding.press is not None or binding.inc is not None or binding.dec is not None:
                raise ValueError("'dial' binding forbids press/inc/dec.")
        elif kind == "encoder":
            if binding.inc is None or binding.dec is None:
                raise ValueError("'encoder' binding requires inc and dec.")
            if binding.press is not None or binding.write is not None:
                raise ValueError("'encoder' binding forbids press/write.")
        elif kind == "selector":
            if binding.read is None:
                raise ValueError("'selector' binding requires read.")
            has_write = binding.write is not None
            has_inc_dec = binding.inc is not None and binding.dec is not None
            if has_write == has_inc_dec:
                raise ValueError(
                    "'selector' binding requires exactly one of write, or inc AND dec."
                )
            if binding.press is not None:
                raise ValueError("'selector' binding forbids press.")
        return self

    @property
    def spec(self) -> CockpitControlSpec:
        """The published half — everything but ``binding`` (D3)."""
        return CockpitControlSpec(**self.model_dump(exclude={"binding"}))


class CockpitDetection(BaseModel):
    """How the adapter probes whether this aircraft's catalog applies (D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataref_exists: str = Field(
        min_length=1, description="Opaque to core/: the adapter probes this name per-name (D5)."
    )


class CockpitAircraft(BaseModel):
    """One catalog's identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_id: str = Field(pattern=CATALOG_ID_PATTERN)
    label: str = Field(min_length=1, max_length=60)
    path_hints: list[str] = Field(
        default_factory=list,
        description="Substrings of the sim's aircraft path that suggest this aircraft is "
        "loaded. NEVER used for detection — only so a live test can fail loudly when the "
        "aircraft looks loaded but the probe is negative, and for the manifest's detection "
        "note.",
    )
    verified_against: str | None = Field(default=None, max_length=120)


class ParkedControl(BaseModel):
    """Exists on the aircraft, has no verified mapping (D10). Rendered disabled with the reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    label: str = Field(min_length=1, max_length=60)
    panel_id: str = Field(pattern=CONTROL_ID_PATTERN)
    reason: str = Field(min_length=1, max_length=200)
    since: date


def _condition_type_error(target_kind: str, control_id: str) -> str:
    return (
        f"Precondition equals for {target_kind!r} control {control_id!r} has an incompatible type."
    )


def _check_condition_type(target: CockpitControlDefinition, equals: CockpitValue) -> None:
    """The equals value is type-compatible with the referenced control's kind."""
    if target.kind == "toggle":
        if not isinstance(equals, bool):
            raise ValueError(_condition_type_error(target.kind, target.control_id))
    elif target.kind == "selector":
        options = target.options or []
        matches = any(
            type(equals) is type(option.value) and equals == option.value for option in options
        )
        if not matches:
            raise ValueError(
                f"Precondition equals {equals!r} for selector {target.control_id!r} is not "
                "among its options."
            )
    elif target.kind in ("dial", "encoder") and (
        isinstance(equals, bool) or not isinstance(equals, (int, float))
    ):
        raise ValueError(_condition_type_error(target.kind, target.control_id))


def _ensure_acyclic(edges: dict[str, frozenset[str]]) -> None:
    """Raise ``ValueError`` when the precondition graph ``edges`` has a cycle.

    A minimal, self-contained Kahn's-algorithm cycle check. Deliberately not
    shared with ``core.cockpit.preconditions.precondition_order`` (which
    depends on this module and cannot be depended on in return) — the
    duplication is a handful of lines, and keeps ``core.cockpit.models`` free
    of any dependency on the rest of the package.
    """
    remaining = set(edges)
    resolved: set[str] = set()
    while remaining:
        progressed = False
        for control_id in list(remaining):
            if edges[control_id] <= resolved:
                resolved.add(control_id)
                remaining.discard(control_id)
                progressed = True
        if not progressed:
            raise ValueError(f"Precondition cycle detected among {sorted(remaining)!r}.")


class CockpitCatalogDocument(BaseModel):
    """One aircraft's whole catalog, after the loader has merged its directory (D4)."""

    model_config = ConfigDict(frozen=True)

    aircraft: CockpitAircraft
    detect: CockpitDetection
    panels: list[CockpitPanel] = Field(min_length=1)
    controls: list[CockpitControlDefinition] = Field(default_factory=list)
    parked: list[ParkedControl] = Field(default_factory=list)
    setup_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="AircraftSetup field name -> control_id (D11). A bool field maps to a "
        "toggle, a float field to a dial.",
    )

    @model_validator(mode="after")
    def _validate_document(self) -> CockpitCatalogDocument:
        panel_ids = [panel.panel_id for panel in self.panels]
        if len(set(panel_ids)) != len(panel_ids):
            raise ValueError("Duplicate panel_id among panels.")
        panel_id_set = set(panel_ids)

        control_ids = [control.control_id for control in self.controls]
        parked_ids = [entry.control_id for entry in self.parked]
        all_ids = control_ids + parked_ids
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("Duplicate control_id across controls and parked.")

        by_id = {control.control_id: control for control in self.controls}

        for control in self.controls:
            if control.panel_id not in panel_id_set:
                raise ValueError(
                    f"Control {control.control_id!r} references unknown panel_id "
                    f"{control.panel_id!r}."
                )
        for entry in self.parked:
            if entry.panel_id not in panel_id_set:
                raise ValueError(
                    f"Parked control {entry.control_id!r} references unknown panel_id "
                    f"{entry.panel_id!r}."
                )

        edges: dict[str, frozenset[str]] = {}
        for control in self.controls:
            referenced: set[str] = set()
            for group in control.preconditions:
                for condition in group.any_of:
                    target = by_id.get(condition.control_id)
                    if target is None or not target.readable:
                        raise ValueError(
                            f"Control {control.control_id!r} has a precondition referencing "
                            f"{condition.control_id!r}, which is not a readable control on "
                            "this catalog."
                        )
                    _check_condition_type(target, condition.equals)
                    referenced.add(condition.control_id)
            edges[control.control_id] = frozenset(referenced)
        _ensure_acyclic(edges)

        for field_name, control_id in self.setup_overrides.items():
            expected_kind = _setup_field_kind(field_name)
            if expected_kind is None:
                raise ValueError(
                    f"setup_overrides names {field_name!r}, which is not an AircraftSetup field."
                )
            target = by_id.get(control_id)
            if target is None:
                raise ValueError(
                    f"setup_overrides {field_name!r} -> unknown control {control_id!r}."
                )
            if expected_kind == _AIRCRAFT_SETUP_BOOL_KIND and target.kind != "toggle":
                raise ValueError(
                    f"setup_overrides {field_name!r} is a bool field and must map to a "
                    f"toggle control; {control_id!r} is {target.kind!r}."
                )
            if expected_kind == _AIRCRAFT_SETUP_FLOAT_KIND and target.kind != "dial":
                raise ValueError(
                    f"setup_overrides {field_name!r} is a float field and must map to a "
                    f"dial control; {control_id!r} is {target.kind!r}."
                )

        return self


# ---------------------------------------------------------------------------
# §3.3 — state and actuation, the wire models
# ---------------------------------------------------------------------------


class CockpitControlState(BaseModel):
    """One control's confirmed state."""

    model_config = ConfigDict(frozen=True)

    control_id: str
    value: CockpitValue | None = Field(
        description="None for a control that is not readable, or whose read failed — "
        "'unknown' is an answer."
    )


class CockpitStateSnapshot(BaseModel):
    """``GET /api/cockpit/state`` — confirmed values of the readable controls asked for."""

    model_config = ConfigDict(frozen=True)

    catalog_id: str | None = Field(description="None when no catalog is active.")
    revision: int = Field(ge=0)
    states: list[CockpitControlState]


class CockpitActuation(BaseModel):
    """One instructor intent. ``value`` for toggle/dial/selector, ``delta`` for encoder,
    neither for press.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    control_id: str = Field(pattern=CONTROL_ID_PATTERN)
    value: CockpitValue | None = None
    delta: int | None = Field(default=None, description="Signed click count for an encoder.")

    @model_validator(mode="after")
    def _one_intent(self) -> CockpitActuation:
        if self.value is not None and self.delta is not None:
            raise ValueError("An actuation carries either value or delta, never both.")
        return self


class CockpitActuationResult(BaseModel):
    """The outcome of one actuation, confirmed by read-back (D8)."""

    model_config = ConfigDict(frozen=True)

    requested: CockpitActuation
    state: CockpitControlState = Field(
        description="The CONFIRMED state read back after the write. value=None only for "
        "press, or an encoder without a read binding."
    )
    actions_taken: int = Field(
        ge=0,
        description="Presses/writes performed. 0 means the control was already in the "
        "requested state — the guarded-toggle rule made visible.",
    )
    catalog_id: str
    revision: int


# ---------------------------------------------------------------------------
# §3.4 — the manifest
# ---------------------------------------------------------------------------


class CockpitCatalog(BaseModel):
    """What ``SimAdapter.get_cockpit_catalog()`` answers. Binding-free (D3)."""

    model_config = ConfigDict(frozen=True)

    supported: bool = Field(description="The adapter declares can_control_cockpit.")
    reason: str | None = Field(
        description="Why nothing is actuable: no flag, or no catalog detected for the "
        "loaded aircraft. None when `aircraft` is set."
    )
    aircraft: CockpitAircraft | None
    revision: int = Field(
        ge=0, description="Bumped on every (re)detection. 0 before any detection."
    )
    detection_note: str | None = Field(
        description="Human text: what was probed and what the sim's aircraft path currently reads."
    )
    panels: list[CockpitPanel]
    controls: list[CockpitControlSpec]
    parked: list[ParkedControl]


class CockpitCatalogManifest(CockpitCatalog):
    """The REST shape: the catalog plus the adapter's name (the CameraManifest precedent)."""

    model_config = ConfigDict(frozen=True)

    adapter: str
