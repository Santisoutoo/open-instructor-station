"""X-Plane named-view command mapping — docs/designs/camera-manager.md §5.1.

**Nothing in this file has been verified against a live X-Plane.** Every
command path below is the design's *candidate* for a view, carried here with
the confidence §5.1 assigned it and nothing more; ``failure_datarefs.py``'s
honesty convention applies unchanged, only without that module's live-run
findings, because no camera spike has been run yet. Read every row as "verify
in spike".

What makes shipping unverified guesses safe is the same two-tier resolution
the rest of this adapter already uses:

* Each path is looked up against the Web API's own command index at
  :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.connect` time, as an
  **optional** command — one that does not resolve is simply absent from
  ``_command_ids``. It never fails the connection (unlike
  :data:`~adapters.xplane.xplane_adapter.COMMANDS` proper, whose entries are
  load-bearing) and it never raises at call time.
* :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.get_camera_support`
  reports exactly what resolved, so a wrong guess costs one disabled button
  with a stated reason — hard rule 3, "capabilities, not failures".

The residual risk a probe cannot cover is a name that *exists* and selects a
different camera than intended. That is what the manifest caveat in the
adapter says out loud, and what only a live run can settle.

Custom (free-camera) positioning is deliberately **not** mapped here: §5.2's
spike has not been run, ``XPLMCameraControl`` is plugin-only, and the design's
own answer for that case is ``custom_positions_supported=False`` with a stated
reason — not an invented dataref.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal, NamedTuple

from core.camera.models import CAMERA_VIEW_IDS, CameraViewId

__all__ = [
    "CAMERA_COMMANDS",
    "CAMERA_COMMAND_PATHS",
    "CameraCommandConfidence",
    "CameraCommandMapping",
    "command_key_for",
]

CameraCommandConfidence = Literal["high", "medium", "low"]

#: Prefix for the short ``_command_ids`` keys this mapping occupies. Kept
#: distinct from :data:`~adapters.xplane.xplane_adapter.COMMANDS`' own keys so
#: the two namespaces cannot collide as either grows.
_KEY_PREFIX = "camera_view_"


class CameraCommandMapping(NamedTuple):
    """One catalogue view resolved to a candidate X-Plane command.

    ``command is None`` means the design names no candidate at all — there is
    nothing to probe, so ``unsupported_reason`` is always set and the view
    ships permanently unsupported until a human upgrades this file with a
    fact. Every row currently *has* a candidate; the shape exists because
    ``failure_datarefs.py`` needed it and a camera row can plausibly end up
    there after the spike.
    """

    view_id: CameraViewId
    command: str | None
    confidence: CameraCommandConfidence
    unsupported_reason: str | None = None


_ENTRIES: tuple[CameraCommandMapping, ...] = (
    CameraCommandMapping(
        view_id="cockpit",
        # §5.1: "a 3D-cockpit-forward view command" — the design names no
        # path, so this is a guess at X-Plane's own sim/view/ namespace, not
        # a confirmed name.
        command="sim/view/3d_cockpit_cmd_look",
        confidence="medium",
    ),
    CameraCommandMapping(
        view_id="chase",
        # §5.1: "sim/view/chase (or equivalent)".
        command="sim/view/chase",
        confidence="medium",
    ),
    CameraCommandMapping(
        view_id="tower",
        # §5.1: "sim/view/tower (or equivalent)".
        command="sim/view/tower",
        confidence="medium",
    ),
    CameraCommandMapping(
        view_id="wing",
        # §5.1's only *low*-confidence row, and the design says why: it names
        # no command at all, only "a spot/external side view". A still spot
        # camera is the closest candidate, but whether it frames the wing is
        # exactly what a probe cannot answer — the command resolving does not
        # prove the framing.
        command="sim/view/still_spot",
        confidence="low",
    ),
    CameraCommandMapping(
        view_id="drone",
        # §5.1: "sim/view/circle / an orbit or free-camera command". The
        # orbit candidate is taken because the design names it explicitly.
        # Note that selecting it is *not* free positioning — that is §5.2's
        # unresolved question, and it stays unsupported regardless of this row.
        command="sim/view/circle",
        confidence="medium",
    ),
)

CAMERA_COMMANDS: MappingProxyType[CameraViewId, CameraCommandMapping] = MappingProxyType(
    {entry.view_id: entry for entry in _ENTRIES}
)

#: The drift guard ``failure_datarefs.py`` uses, restated: every catalogue
#: view needs a row here (even an unsupported one), and this file must never
#: invent a view the catalogue does not have.
assert set(CAMERA_COMMANDS) == set(CAMERA_VIEW_IDS), (
    "adapters/xplane/camera_commands.py is out of sync with core/camera/models.py's "
    "CAMERA_VIEW_IDS — every catalogue view needs a row here, even an unsupported one."
)


def command_key_for(view_id: CameraViewId) -> str:
    """The short ``_command_ids`` key one view's command is resolved under."""
    return f"{_KEY_PREFIX}{view_id}"


#: Short key -> command path, for every view that has something to probe. Fed
#: to :meth:`~adapters.xplane.xplane_adapter.XPlaneSimAdapter.connect` as the
#: *optional* command set: a path missing from the install's command index
#: leaves its key out of ``_command_ids`` instead of failing the connection.
CAMERA_COMMAND_PATHS: MappingProxyType[str, str] = MappingProxyType(
    {
        command_key_for(entry.view_id): entry.command
        for entry in _ENTRIES
        if entry.command is not None
    }
)
