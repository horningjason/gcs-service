"""Geodesic primitives on the WGS84 spheroid (spec §10.2, decision 40).

Distances are true geodesic metres, never decimal degrees. §10.2 is explicit
about this and the reason is not pedantry: a degree of longitude is 76 km at
Bismarck's latitude and 111 km at the equator, so a radius or an offset
expressed in degrees means a different thing in every jurisdiction. Degrees are
how coordinates serialise; they are never how a configured distance is
measured.

This module lives in src/engine/ rather than beside its first caller because
both directions read it. §7.2's forward interpolation walks a segment; §11.2's
reverse inversion walks the same segment the other way and §14.1 requires the
two traverse the same path. §10.2's search radius and §10.5's candidate
distances are the same measurement again.

WHAT "WALKED ALONG ACTUAL VERTEX GEOMETRY" MEANS

§7.2 interpolates "proportional to address number, walked along the segment's
actual vertex geometry (bends and curves), not a straight chord between
endpoints." Implemented literally: the segment's length is the sum of the
geodesic lengths of its vertex-to-vertex legs, a distance along it is located
by walking those legs until the remaining distance falls inside one, and the
position within that leg is computed by geodesic projection from its start
vertex along the leg's own azimuth. No planar arithmetic on the coordinates and
no chord shortcut anywhere in the walk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from pyproj import Geod

#: The WGS84 spheroid. Every distance and azimuth in the service comes from
#: this one object, so there is a single answer to "which ellipsoid".
GEOD = Geod(ellps="WGS84")

#: (longitude, latitude, optional height). Z rides along so a caller that wants
#: it has it; whether a given rung propagates it is that rung's decision.
Vertex = tuple[float, float, Optional[float]]


def distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Geodesic distance in metres between two points."""
    return abs(GEOD.inv(lon1, lat1, lon2, lat2)[2])


def azimuth_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Forward azimuth in degrees, clockwise from north."""
    return GEOD.inv(lon1, lat1, lon2, lat2)[0]


def vertices_of(geometry) -> list[Vertex]:
    """The vertex list of a single-part line geometry.

    A MultiLineString is accepted only when it wraps exactly one part. More
    than one part is decision 53's data-quality condition: there is no
    specified traversal order, so this module refuses rather than picking one.
    Callers detect the condition earlier through
    RclGisRecord.is_multipart — this is the backstop, not the check.
    """
    if geometry is None:
        raise ValueError("no geometry")

    kind = geometry.geom_type
    if kind == "MultiLineString":
        parts = list(geometry.geoms)
        if len(parts) != 1:
            raise ValueError(
                f"multi-part segment ({len(parts)} parts) has no defined traversal "
                "order; see decision 53"
            )
        geometry = parts[0]
        kind = geometry.geom_type
    if kind != "LineString":
        raise ValueError(f"not a line geometry: {kind}")

    has_z = geometry.has_z
    out: list[Vertex] = []
    for coord in geometry.coords:
        if has_z and len(coord) >= 3:
            out.append((float(coord[0]), float(coord[1]), float(coord[2])))
        else:
            out.append((float(coord[0]), float(coord[1]), None))
    if len(out) < 2:
        raise ValueError("a line needs at least two vertices")
    return out


def leg_lengths_m(vertices: Sequence[Vertex]) -> list[float]:
    """Geodesic length of each vertex-to-vertex leg, in order."""
    return [
        distance_m(a[0], a[1], b[0], b[1])
        for a, b in zip(vertices, vertices[1:])
    ]


def length_m(vertices: Sequence[Vertex]) -> float:
    """Total geodesic length along the vertex path."""
    return math.fsum(leg_lengths_m(vertices))


def interpolate_m(vertices: Sequence[Vertex], distance_from_start_m: float) -> Vertex:
    """The point a given distance along the vertex path.

    Walks legs in order and projects geodesically inside the leg the distance
    lands in. Distances outside the path clamp to its ends — a caller that
    needs to know it was out of range checks before calling, because clamping
    silently is right for §7.2 (a house number outside the asserted range is
    handled by side selection, not here) and wrong to discover afterwards.

    Z is interpolated linearly within the leg where both ends carry one. That
    is what §3.7.1's "one interpolation carrying whatever dimensions the
    vertices have" asks for. Whether a rung propagates the result is a separate
    decision — rung 2 does not (spec Appendix C.4 R1).
    """
    legs = leg_lengths_m(vertices)
    total = math.fsum(legs)

    if distance_from_start_m <= 0 or total == 0:
        return vertices[0]
    if distance_from_start_m >= total:
        return vertices[-1]

    walked = 0.0
    for index, leg in enumerate(legs):
        if walked + leg >= distance_from_start_m:
            start, end = vertices[index], vertices[index + 1]
            into_leg = distance_from_start_m - walked
            if leg == 0:
                return start
            azimuth = azimuth_deg(start[0], start[1], end[0], end[1])
            lon, lat, _ = GEOD.fwd(start[0], start[1], azimuth, into_leg)
            height: Optional[float] = None
            if start[2] is not None and end[2] is not None:
                height = start[2] + (end[2] - start[2]) * (into_leg / leg)
            return (float(lon), float(lat), height)
        walked += leg

    return vertices[-1]


def azimuth_at_m(vertices: Sequence[Vertex], distance_from_start_m: float) -> float:
    """Direction of travel at a distance along the path.

    The azimuth of the leg that distance falls in — the segment's digitised
    direction there, which is what makes "left" and "right" mean anything
    (§7.2, §7.3).
    """
    legs = leg_lengths_m(vertices)
    walked = 0.0
    for index, leg in enumerate(legs):
        if leg == 0:
            continue
        if walked + leg >= distance_from_start_m:
            start, end = vertices[index], vertices[index + 1]
            return azimuth_deg(start[0], start[1], end[0], end[1])
        walked += leg

    for index in range(len(legs) - 1, -1, -1):
        if legs[index] > 0:
            start, end = vertices[index], vertices[index + 1]
            return azimuth_deg(start[0], start[1], end[0], end[1])
    raise ValueError("zero-length path has no direction")


def offset_perpendicular(
    lon: float,
    lat: float,
    azimuth: float,
    distance_m_: float,
    *,
    to_left: bool,
) -> tuple[float, float]:
    """Step perpendicular to `azimuth` by `distance_m_`.

    Left and right are taken relative to the segment's digitised direction,
    which is the same convention the L/R attribute columns use. §7.3 requires
    the result never sit on the centerline itself, so a non-positive distance
    is a configuration error rather than a no-op: silently returning the input
    would put a dispatched position in the middle of the road.
    """
    if distance_m_ <= 0:
        raise ValueError(
            "GCS_RCL_OFFSET_M must be positive — §7.3 requires the derived "
            "position never lie on the centerline"
        )
    bearing = azimuth - 90.0 if to_left else azimuth + 90.0
    out_lon, out_lat, _ = GEOD.fwd(lon, lat, bearing % 360.0, distance_m_)
    return float(out_lon), float(out_lat)


def midpoint(vertices: Sequence[Vertex]) -> Vertex:
    """The point half way along the path, by distance rather than by vertex
    count. §3.7.3's minimise-maximum-error position for a segment that asserts
    an address without saying where on the block it sits (decision 48).
    """
    return interpolate_m(vertices, length_m(vertices) / 2.0)


@dataclass(frozen=True, slots=True)
class Projection:
    """Where a point falls on a path, and how far off it is."""

    longitude: float
    latitude: float
    #: Along-track distance from the path's start, in metres. This is the same
    #: quantity §7.2's forward interpolation produces, which is what lets
    #: §11.2 invert the forward walk rather than run a parallel one.
    distance_along_m: float
    #: Perpendicular distance from the input point to the path, in metres.
    offset_m: float
    #: Which side of the path the input point fell on, by the path's own
    #: digitised direction — the same sense the L/R attribute columns use.
    to_left: bool


def project_onto_path(
    vertices: Sequence[Vertex], lon: float, lat: float
) -> Projection:
    """Project a point onto a vertex path (§10.5, §11.2).

    Each leg is solved in a local tangent frame centred on the input point:
    longitudes are scaled by cos(latitude) so that one unit means the same
    distance on both axes, the closest point on the leg is found by ordinary
    vector projection there, and the result is converted back and measured with
    a true geodesic distance. The planar step is confined to picking WHICH
    point on the leg is closest; every distance this function reports comes
    from GEOD.

    That is accurate to well under a metre for legs of the length real
    centerline segments have, and it avoids the alternative of an iterative
    geodesic solve for a quantity that then feeds a house-number interpolation
    across a range of a hundred addresses.
    """
    if len(vertices) < 2:
        raise ValueError("a path needs at least two vertices")

    scale = math.cos(math.radians(lat))

    best: Optional[Projection] = None
    walked = 0.0
    for start, end in zip(vertices, vertices[1:]):
        leg_m = distance_m(start[0], start[1], end[0], end[1])

        ax = (start[0] - lon) * scale
        ay = start[1] - lat
        bx = (end[0] - lon) * scale
        by = end[1] - lat
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy

        if denominator == 0:
            t = 0.0
        else:
            t = min(1.0, max(0.0, -(ax * dx + ay * dy) / denominator))

        near_lon = start[0] + (end[0] - start[0]) * t
        near_lat = start[1] + (end[1] - start[1]) * t
        offset_m = distance_m(lon, lat, near_lon, near_lat)

        if best is None or offset_m < best.offset_m:
            # Cross product in the tangent frame: positive means the input
            # point lies left of the leg's direction of travel.
            cross = dx * (0.0 - ay) - dy * (0.0 - ax)
            best = Projection(
                longitude=near_lon,
                latitude=near_lat,
                distance_along_m=walked + leg_m * t,
                offset_m=offset_m,
                to_left=cross > 0,
            )
        walked += leg_m

    assert best is not None
    return best


def mean_position(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Arithmetic mean of a set of coordinates.

    Used only for §6.3's merge, which by construction runs on candidates within
    GCS_AMBIGUITY_TOLERANCE_M of each other — a few hundred metres at most,
    where the difference between this and a spheroidal mean is far below the
    positional accuracy of the underlying GIS data. It would be the wrong
    function for a continental-scale set, and §6.3 never hands it one.
    """
    if not points:
        raise ValueError("no points to average")
    return (
        math.fsum(p[0] for p in points) / len(points),
        math.fsum(p[1] for p in points) / len(points),
    )


def max_distance_from_m(
    origin: tuple[float, float],
    points: Sequence[tuple[float, float]],
) -> float:
    """Greatest geodesic distance from `origin` to any of `points`.

    §6.3 sizes the merged uncertainty to the candidates' extent; this is that
    extent measured from the position actually returned.
    """
    if not points:
        return 0.0
    return max(distance_m(origin[0], origin[1], p[0], p[1]) for p in points)
