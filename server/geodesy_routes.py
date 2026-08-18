"""``/api/geodesy/*`` — exact WGS84 arithmetic. No adapter, no navdata.

One route, serving the Instructor Map's measurement tool
(``docs/designs/instructor-map.md`` §2.1): the map draws its *live* readout with
a client-side spherical approximation, then replaces it with this endpoint's
geodesic answer once both points are settled — the same solver every placement's
geometry already goes through (:func:`core.geodesy.distance_and_bearing`).

The route is ``def``, not ``async def`` — pure arithmetic on Starlette's
threadpool; there is nothing to await. The only error case is FastAPI's own
``422`` for out-of-range coordinates: no 404 (nothing to look up), no 503 (no
navdata involved), no 501 (no capability involved). This is the simplest
endpoint in the project, deliberately.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.geodesy import distance_and_bearing
from core.models import GeoPosition

__all__ = ["MeasureResult", "router"]

router = APIRouter(prefix="/api/geodesy", tags=["geodesy"])


class MeasureResult(BaseModel):
    """The exact geodesic answer between two points, WGS84."""

    distance_nm: float = Field(description="Geodesic distance, nautical miles.")
    initial_bearing_true_deg: float = Field(
        ge=0.0, lt=360.0, description="Initial true bearing from point 1 to point 2, degrees."
    )


@router.get("/measure", response_model=MeasureResult)
def measure(
    lat1: float = Query(ge=-90.0, le=90.0),
    lon1: float = Query(ge=-180.0, le=180.0),
    lat2: float = Query(ge=-90.0, le=90.0),
    lon2: float = Query(ge=-180.0, le=180.0),
) -> MeasureResult:
    """The exact WGS84 distance and initial true bearing from point 1 to point 2."""
    a = GeoPosition(latitude=lat1, longitude=lon1)
    b = GeoPosition(latitude=lat2, longitude=lon2)
    distance_nm, bearing_deg = distance_and_bearing(a, b)
    return MeasureResult(distance_nm=distance_nm, initial_bearing_true_deg=bearing_deg)
