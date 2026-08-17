"""§9 — request admission: eight input shapes, one search origin.

All eight RFC 5491 §5 GeoShape forms are accepted. i3 §4.5 says only that the
request contains "a geodetic representation" and cites RFC 4119, 5139 and 5491
without narrowing the shape vocabulary, so accepting only a Point would be a
restriction i3 does not impose — which decision 2's corollary forbids as firmly
as it forbids adding capability.

ONE ORIGIN, NO SHAPE-SPECIFIC PATHS DOWNSTREAM

Every shape reduces here to a single origin by the §7.5 centroid convention:
the footprint centroid for X/Y, the vertical midpoint for Z. A Point supplies
itself, a Circle its centre, a Polygon its footprint centroid, a Prism its
footprint centroid at mid-height. §10 then receives exactly one origin whatever
arrived, and nothing after this module branches on shape.

THE EXTENT IS NOT DISCARDED WITH THE SHAPE

Reducing to an origin would throw away the thing that makes a vague query
vague. The shape is therefore carried alongside the origin, because §10.3 tests
containment against it and §10.6 damps the spatial-fit score by it — a query
expressing two kilometres of uncertainty must not score as though it expressed
two metres.

This is where §7.4's rule that the GCS does not reason about its input's
uncertainty stops applying, and §9 says so explicitly. On the Geocode side an
input's uncertainty is metadata attached to a civic address and properly
ignored. Here the input geometry IS the query, so its extent is not metadata
about the question but the substance of it.

WHERE THE GML GOES

This module takes parsed shapes, not XML. Turning an RFC 5491 GML document into
one of the types below belongs to src/api/wire/gml_xml.py. Keeping the split
means the eight-shape vocabulary is testable without a serialiser, and the
serialiser has one obvious set of types to produce.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from src.engine import geometry


@dataclass(frozen=True, slots=True)
class SearchOrigin:
    """The one origin §10 searches from, plus what the shape still says."""

    longitude: float
    latitude: float
    altitude: Optional[float] = None

    #: Characteristic horizontal extent of the input shape in metres — the
    #: distance from the origin to its farthest edge. Zero for a Point, which
    #: is what makes a Point contain nothing (§10.3).
    extent_m: float = 0.0

    #: Vertical extent in metres where the shape has one, None otherwise.
    vertical_extent_m: Optional[float] = None

    #: The shape the origin came from, retained for the containment test.
    shape: Optional["GeoShape"] = None

    @property
    def has_extent(self) -> bool:
        return self.extent_m > 0


class GeoShape:
    """Base for the eight RFC 5491 §5 forms.

    Subclasses supply `origin()` and `contains()`. `contains` answers §10.3's
    question and nothing else: a Point returns False for everything, because a
    point has no area and therefore contains nothing — which is why the
    commonest input in the system never reaches the containment rule and orders
    by pure proximity.
    """

    def origin(self) -> SearchOrigin:  # pragma: no cover - interface
        raise NotImplementedError

    def contains(self, lon: float, lat: float, alt: Optional[float] = None) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class Point(GeoShape):
    longitude: float
    latitude: float
    altitude: Optional[float] = None

    def origin(self) -> SearchOrigin:
        return SearchOrigin(
            self.longitude, self.latitude, self.altitude, extent_m=0.0, shape=self
        )

    def contains(self, lon, lat, alt=None) -> bool:
        """A point has no area. §10.3 depends on this being False."""
        return False


@dataclass(frozen=True, slots=True)
class Circle(GeoShape):
    longitude: float
    latitude: float
    radius_m: float
    altitude: Optional[float] = None

    def origin(self) -> SearchOrigin:
        return SearchOrigin(
            self.longitude, self.latitude, self.altitude,
            extent_m=self.radius_m, shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        return geometry.distance_m(self.longitude, self.latitude, lon, lat) <= self.radius_m


@dataclass(frozen=True, slots=True)
class Sphere(GeoShape):
    longitude: float
    latitude: float
    altitude: float
    radius_m: float

    def origin(self) -> SearchOrigin:
        return SearchOrigin(
            self.longitude, self.latitude, self.altitude,
            extent_m=self.radius_m, vertical_extent_m=2 * self.radius_m, shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        horizontal = geometry.distance_m(self.longitude, self.latitude, lon, lat)
        if horizontal > self.radius_m:
            return False
        if alt is None:
            return True
        vertical = abs(alt - self.altitude)
        return math.hypot(horizontal, vertical) <= self.radius_m


@dataclass(frozen=True, slots=True)
class Ellipse(GeoShape):
    """Semi-major axis oriented `orientation_deg` clockwise from north."""

    longitude: float
    latitude: float
    semi_major_m: float
    semi_minor_m: float
    orientation_deg: float = 0.0
    altitude: Optional[float] = None

    def origin(self) -> SearchOrigin:
        return SearchOrigin(
            self.longitude, self.latitude, self.altitude,
            extent_m=self.semi_major_m, shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        return _within_ellipse(
            self.longitude, self.latitude, self.semi_major_m,
            self.semi_minor_m, self.orientation_deg, lon, lat,
        )


@dataclass(frozen=True, slots=True)
class Ellipsoid(GeoShape):
    longitude: float
    latitude: float
    altitude: float
    semi_major_m: float
    semi_minor_m: float
    vertical_axis_m: float
    orientation_deg: float = 0.0

    def origin(self) -> SearchOrigin:
        return SearchOrigin(
            self.longitude, self.latitude, self.altitude,
            extent_m=self.semi_major_m,
            vertical_extent_m=2 * self.vertical_axis_m, shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        if not _within_ellipse(
            self.longitude, self.latitude, self.semi_major_m,
            self.semi_minor_m, self.orientation_deg, lon, lat,
        ):
            return False
        if alt is None or self.vertical_axis_m <= 0:
            return True
        return abs(alt - self.altitude) <= self.vertical_axis_m


@dataclass(frozen=True, slots=True)
class ArcBand(GeoShape):
    """An annular sector: the region between two radii, across an angle.

    The RFC 5491 centre is the arc's apex, which lies OUTSIDE the band. Using
    it as the search origin would place the origin outside the caller's own
    query shape and make containment behave absurdly, so §7.5's footprint
    centroid is taken literally here and the centroid of the annular sector is
    computed instead.
    """

    longitude: float
    latitude: float
    inner_radius_m: float
    outer_radius_m: float
    start_angle_deg: float
    opening_angle_deg: float

    def origin(self) -> SearchOrigin:
        bisector = self.start_angle_deg + self.opening_angle_deg / 2.0
        half = math.radians(self.opening_angle_deg / 2.0)
        r1, r2 = self.inner_radius_m, self.outer_radius_m

        # Centroid of an annular sector, measured from the apex along the
        # bisector. Degenerates to the mid-radius as the opening angle shrinks.
        if r2 <= r1:
            reach = r2
        elif half == 0:
            reach = (r1 + r2) / 2.0
        else:
            reach = (2.0 / 3.0) * (math.sin(half) / half) * (
                (r2 ** 3 - r1 ** 3) / (r2 ** 2 - r1 ** 2)
            )

        lon, lat, _ = geometry.GEOD.fwd(
            self.longitude, self.latitude, bisector % 360.0, reach
        )
        return SearchOrigin(
            float(lon), float(lat), None,
            # The farthest the band reaches from its own centroid.
            extent_m=max(abs(r2 - reach), abs(reach - r1)),
            shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        distance = geometry.distance_m(self.longitude, self.latitude, lon, lat)
        if not (self.inner_radius_m <= distance <= self.outer_radius_m):
            return False
        azimuth = geometry.azimuth_deg(self.longitude, self.latitude, lon, lat)
        return _within_arc(azimuth, self.start_angle_deg, self.opening_angle_deg)


@dataclass(frozen=True, slots=True)
class Polygon(GeoShape):
    """A closed footprint. Vertices are (longitude, latitude), unclosed."""

    vertices: tuple[tuple[float, float], ...]
    altitude: Optional[float] = None

    def origin(self) -> SearchOrigin:
        lon, lat = geometry.mean_position(list(self.vertices))
        return SearchOrigin(
            lon, lat, self.altitude,
            extent_m=geometry.max_distance_from_m((lon, lat), list(self.vertices)),
            shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        return _within_ring(self.vertices, lon, lat)


@dataclass(frozen=True, slots=True)
class Prism(GeoShape):
    """A polygon footprint extruded vertically — §7.5's volume, when one exists."""

    vertices: tuple[tuple[float, float], ...]
    base_altitude: float
    height_m: float

    def origin(self) -> SearchOrigin:
        lon, lat = geometry.mean_position(list(self.vertices))
        return SearchOrigin(
            lon, lat,
            # §7.5: the vertical midpoint, not the floor. Naming floor 1 of a
            # twenty-storey structure puts a responder up to sixty metres out;
            # the midpoint bounds the worst case at thirty.
            self.base_altitude + self.height_m / 2.0,
            extent_m=geometry.max_distance_from_m((lon, lat), list(self.vertices)),
            vertical_extent_m=self.height_m,
            shape=self,
        )

    def contains(self, lon, lat, alt=None) -> bool:
        if not _within_ring(self.vertices, lon, lat):
            return False
        if alt is None:
            return True
        return self.base_altitude <= alt <= self.base_altitude + self.height_m


def origin_of(shape: GeoShape) -> SearchOrigin:
    """Reduce any accepted shape to the one origin §10 searches from."""
    return shape.origin()


# ---------------------------------------------------------------------------
# Local-frame helpers
# ---------------------------------------------------------------------------
# Containment is decided in a tangent frame centred on the shape, with
# longitudes scaled by cos(latitude) so a unit means the same distance on both
# axes. At the scale a query shape has — metres to a few kilometres — the error
# is far below the positional accuracy of the underlying GIS data, and the
# alternative is a projected CRS this service does not otherwise need.

def _local_offsets_m(
    centre_lon: float, centre_lat: float, lon: float, lat: float
) -> tuple[float, float]:
    metres_per_degree = 111_320.0
    east = (lon - centre_lon) * metres_per_degree * math.cos(math.radians(centre_lat))
    north = (lat - centre_lat) * metres_per_degree
    return east, north


def _within_ellipse(
    centre_lon, centre_lat, semi_major_m, semi_minor_m, orientation_deg, lon, lat
) -> bool:
    if semi_major_m <= 0 or semi_minor_m <= 0:
        return False
    east, north = _local_offsets_m(centre_lon, centre_lat, lon, lat)
    # Orientation is clockwise from north; rotate into the axis frame.
    theta = math.radians(orientation_deg)
    along_major = north * math.cos(theta) + east * math.sin(theta)
    along_minor = -north * math.sin(theta) + east * math.cos(theta)
    return (along_major / semi_major_m) ** 2 + (along_minor / semi_minor_m) ** 2 <= 1.0


def _within_arc(azimuth_deg: float, start_deg: float, opening_deg: float) -> bool:
    if opening_deg >= 360:
        return True
    delta = (azimuth_deg - start_deg) % 360.0
    return delta <= opening_deg % 360.0 or opening_deg == 0 and delta == 0


def _within_ring(vertices: Sequence[tuple[float, float]], lon: float, lat: float) -> bool:
    """Even-odd ray casting in the tangent frame."""
    if len(vertices) < 3:
        return False
    centre_lon, centre_lat = geometry.mean_position(list(vertices))
    ring = [_local_offsets_m(centre_lon, centre_lat, v[0], v[1]) for v in vertices]
    x, y = _local_offsets_m(centre_lon, centre_lat, lon, lat)

    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < crossing:
                inside = not inside
    return inside
