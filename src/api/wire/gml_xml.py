"""RFC 5491 §4's GML subset and §5's GeoShape, plus RFC 7459 confidence.

COORDINATE ORDER IS LAT LON

Throughout, on both sides. RFC 5491 §4 requires GML with the EPSG::4326 /
EPSG::4979 axis order, which is latitude first. The engine works in (x, y) —
longitude first — because that is what shapely means, so this module is where
the two conventions meet and the swap happens exactly once (§7.1).

READ: EIGHT SHAPES, ONE ORIGIN

All eight RFC 5491 §5 forms parse (§9, decision 37). Accepting only a Point
would be a restriction i3 does not impose, and decision 2's corollary forbids
that as firmly as it forbids adding capability. Each parses to the matching
src/reverse/origin.py type, and the reduction to a single search origin is that
module's, not this one's — this module produces shapes, never origins.

WRITE: THREE SHAPES, AND NOTHING SYNTHESISED

    rung 1, rung 2      gml:Point
    rung 3              gml:LineString — the segment's own geometry
    §6.3's merge        gs:Circle — centre and radius the core measured

§7.4's geometry-as-answer rule (decision 30) is what keeps this list short.
Nothing here invents an uncertainty shape around a point: the matched geometry
IS the uncertainty statement, and a rung-3 line is returned whole rather than
collapsed to a position it does not assert. The Circle is the one shape this
layer renders rather than copies, and decision 57 scopes it narrowly — the
merged case has genuinely measured an extent, so a Circle reports a measurement
rather than dressing up a guess.

UNITS

RFC 5491 §5 requires metres for every length and degrees for every angle. Values
are read as such. A `uom` attribute naming anything else is logged and the value
is still read as metres, because the alternative is either refusing a request i3
does not let this service refuse or inventing a conversion table the standard
does not supply.
"""

from __future__ import annotations

import logging
from typing import Optional

from lxml import etree

from src.api.wire.xml_ns import (
    NS_GEOSHAPE,
    NS_GML,
    NSMAP,
    Q_CONFIDENCE,
    q,
)
from src.engine import geometry as engine_geometry
from src.engine.models import CRS_2D, CRS_3D, Position
from src.reverse import origin as shapes

log = logging.getLogger(__name__)

#: EPSG::9001 — metre. RFC 5491 §5's required unit for every length.
UOM_METRE = "urn:ogc:def:uom:EPSG::9001"
#: EPSG::9102 — degree.
UOM_DEGREE = "urn:ogc:def:uom:EPSG::9102"

Q_POINT = q(NS_GML, "Point")
Q_LINE_STRING = q(NS_GML, "LineString")
Q_POLYGON = q(NS_GML, "Polygon")
Q_EXTERIOR = q(NS_GML, "exterior")
Q_LINEAR_RING = q(NS_GML, "LinearRing")
Q_POS = q(NS_GML, "pos")
Q_POS_LIST = q(NS_GML, "posList")

Q_CIRCLE = q(NS_GEOSHAPE, "Circle")
Q_ELLIPSE = q(NS_GEOSHAPE, "Ellipse")
Q_ARC_BAND = q(NS_GEOSHAPE, "ArcBand")
Q_SPHERE = q(NS_GEOSHAPE, "Sphere")
Q_ELLIPSOID = q(NS_GEOSHAPE, "Ellipsoid")
Q_PRISM = q(NS_GEOSHAPE, "Prism")


class GmlParseError(ValueError):
    """A geodetic chunk that is well-formed XML but not a readable shape."""


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def _numbers(text: Optional[str]) -> list[float]:
    if not text:
        return []
    try:
        return [float(token) for token in text.split()]
    except ValueError as exc:
        raise GmlParseError(f"coordinate list is not numeric: {text!r}") from exc


def _position(element: etree._Element) -> tuple[float, float, Optional[float]]:
    """A `gml:pos` as (longitude, latitude, optional altitude).

    The wire order is lat lon [alt]; the return order is the engine's.
    """
    values = _numbers(element.text)
    if len(values) < 2:
        raise GmlParseError(
            f"<gml:pos> needs at least two ordinates, got {len(values)}"
        )
    latitude, longitude = values[0], values[1]
    altitude = values[2] if len(values) >= 3 else None
    return longitude, latitude, altitude


def _centre(element: etree._Element) -> tuple[float, float, Optional[float]]:
    """The `gs:centerGroup` choice: a gml:pos, or a gml:pointProperty."""
    pos = element.find(Q_POS)
    if pos is not None:
        return _position(pos)
    nested = element.find(f".//{Q_POINT}/{Q_POS}")
    if nested is not None:
        return _position(nested)
    raise GmlParseError(f"{etree.QName(element).localname} carries no centre position")


def _length(parent: etree._Element, local: str) -> float:
    child = parent.find(q(NS_GEOSHAPE, local))
    if child is None:
        raise GmlParseError(f"missing <gs:{local}>")
    uom = child.get("uom")
    if uom and uom != UOM_METRE:
        log.info(
            "<gs:%s> declares uom=%r; RFC 5491 §5 requires metres and the value "
            "is read as metres",
            local,
            uom,
        )
    values = _numbers(child.text)
    if not values:
        raise GmlParseError(f"<gs:{local}> has no numeric value")
    return values[0]


def _angle(parent: etree._Element, local: str) -> float:
    child = parent.find(q(NS_GEOSHAPE, local))
    if child is None:
        raise GmlParseError(f"missing <gs:{local}>")
    values = _numbers(child.text)
    if not values:
        raise GmlParseError(f"<gs:{local}> has no numeric value")
    return values[0]


def _ring_vertices(
    polygon: etree._Element,
) -> tuple[tuple[tuple[float, float], ...], Optional[float]]:
    """A polygon's exterior ring as (lon, lat) pairs, plus its altitude if any.

    Both GML spellings are accepted: a `gml:posList` of flattened ordinates, or
    a sequence of `gml:pos` elements.
    """
    ring = polygon.find(f"{Q_EXTERIOR}/{Q_LINEAR_RING}")
    if ring is None:
        raise GmlParseError("<gml:Polygon> has no exterior LinearRing")

    vertices: list[tuple[float, float]] = []
    altitude: Optional[float] = None

    pos_list = ring.find(Q_POS_LIST)
    if pos_list is not None:
        values = _numbers(pos_list.text)
        dimension = int(pos_list.get("srsDimension", "2"))
        if dimension not in (2, 3):
            raise GmlParseError(f"unsupported srsDimension {dimension}")
        if len(values) % dimension:
            raise GmlParseError(
                f"<gml:posList> has {len(values)} ordinates, not a multiple of "
                f"{dimension}"
            )
        for index in range(0, len(values), dimension):
            chunk = values[index: index + dimension]
            vertices.append((chunk[1], chunk[0]))  # lat lon -> lon lat
            if dimension == 3 and altitude is None:
                altitude = chunk[2]
    else:
        for pos in ring.findall(Q_POS):
            longitude, latitude, height = _position(pos)
            vertices.append((longitude, latitude))
            if altitude is None:
                altitude = height

    # GML closes a ring by repeating the first vertex; the shape types take an
    # unclosed vertex list, so the duplicate is dropped rather than counted
    # twice in the centroid.
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices = vertices[:-1]

    if len(vertices) < 3:
        raise GmlParseError("a polygon needs at least three distinct vertices")

    return tuple(vertices), altitude


def parse_shape(element: etree._Element) -> shapes.GeoShape:
    """Read one RFC 5491 geodetic chunk into an origin.GeoShape.

    Raises GmlParseError for a chunk that is not one of the eight, or is one of
    the eight with something essential missing. The caller maps that to 454: it
    is the same class of failure as a schema violation — the document is
    well-formed but does not carry a readable location.
    """
    tag = element.tag

    if tag == Q_POINT:
        pos = element.find(Q_POS)
        if pos is None:
            raise GmlParseError("<gml:Point> carries no <gml:pos>")
        longitude, latitude, altitude = _position(pos)
        return shapes.Point(longitude, latitude, altitude)

    if tag == Q_POLYGON:
        vertices, altitude = _ring_vertices(element)
        return shapes.Polygon(vertices, altitude)

    if tag == Q_CIRCLE:
        longitude, latitude, altitude = _centre(element)
        return shapes.Circle(longitude, latitude, _length(element, "radius"), altitude)

    if tag == Q_ELLIPSE:
        longitude, latitude, altitude = _centre(element)
        return shapes.Ellipse(
            longitude,
            latitude,
            _length(element, "semiMajorAxis"),
            _length(element, "semiMinorAxis"),
            _angle(element, "orientation"),
            altitude,
        )

    if tag == Q_ARC_BAND:
        longitude, latitude, _ = _centre(element)
        return shapes.ArcBand(
            longitude,
            latitude,
            _length(element, "innerRadius"),
            _length(element, "outerRadius"),
            _angle(element, "startAngle"),
            _angle(element, "openingAngle"),
        )

    if tag == Q_SPHERE:
        longitude, latitude, altitude = _centre(element)
        if altitude is None:
            raise GmlParseError(_NO_HEIGHT.format(shape="Sphere", part="centre"))
        return shapes.Sphere(longitude, latitude, altitude, _length(element, "radius"))

    if tag == Q_ELLIPSOID:
        longitude, latitude, altitude = _centre(element)
        if altitude is None:
            raise GmlParseError(_NO_HEIGHT.format(shape="Ellipsoid", part="centre"))
        return shapes.Ellipsoid(
            longitude,
            latitude,
            altitude,
            _length(element, "semiMajorAxis"),
            _length(element, "semiMinorAxis"),
            _length(element, "verticalAxis"),
            _angle(element, "orientation"),
        )

    if tag == Q_PRISM:
        base = element.find(f"{q(NS_GEOSHAPE, 'base')}/{Q_POLYGON}")
        if base is None:
            raise GmlParseError("<gs:Prism> carries no base polygon")
        vertices, altitude = _ring_vertices(base)
        if altitude is None:
            raise GmlParseError(_NO_HEIGHT.format(shape="Prism", part="base polygon"))
        return shapes.Prism(vertices, altitude, _length(element, "height"))

    raise GmlParseError(
        f"{tag!r} is not one of the eight RFC 5491 §5 shapes"
    )


#: A solid whose vertical placement is absent is refused rather than defaulted.
#: Supplying a zero would put the query at the ellipsoid surface — a specific
#: claim about height that the caller did not make — and §3.7's whole posture is
#: that an unpopulated vertical slot asserts nothing (decision 55).
_NO_HEIGHT = (
    "<gs:{shape}> is a solid but its {part} carries no height ordinate; a "
    "vertical position cannot be supplied for it without inventing one"
)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _pos_text(longitude: float, latitude: float, altitude: Optional[float]) -> str:
    """lat lon [alt] — RFC 5491 / GML order."""
    if altitude is None:
        return f"{latitude:.8f} {longitude:.8f}"
    return f"{latitude:.8f} {longitude:.8f} {altitude:.3f}"


def build_point(position: Position) -> etree._Element:
    """A rung-1 or rung-2 answer.

    srsName follows decision 55: EPSG::4979 where the geometry's Z was
    admitted, EPSG::4326 where it was not. Dimensionality follows the data, so
    the declared CRS and the ordinate count always agree.
    """
    element = etree.Element(Q_POINT, nsmap=NSMAP)
    element.set("srsName", CRS_3D if position.is_3d else CRS_2D)
    pos = etree.SubElement(element, Q_POS)
    pos.text = _pos_text(position.longitude, position.latitude, position.altitude)
    return element


def build_line_string(line_geometry, *, srs_name: str = CRS_2D) -> etree._Element:
    """A rung-3 answer — the segment's own geometry (§7.4, decision 30).

    Always 2D, and always srsName'd (decision 85, resolving Appendix C.4 Q22).
    This function used to omit srsName entirely, because Candidate.crs
    abstained for a line answer and GML makes the attribute optional, so
    absence was an honest rendering of "the specification has not chosen
    between 4326 and 4979." Decision 85 chose: RoadCenterLine is not a declared
    3D-capable feature class (§10.5), so the provisioned layer's
    MultiLineString Z type is a GeoPackage export artifact rather than
    authoritative vertical attribution, and its Z is never consulted at any
    rung.

    Hence the vertex Z is DROPPED here rather than written. The old code
    emitted srsDimension="3" and three ordinates per vertex whenever every
    vertex carried a Z — which the provisioned layer always does — so the
    abstention was never actually neutral on the wire: it shipped a 3D
    coordinate list with no CRS to interpret it by, which is closer to
    asserting 4979 than to asserting nothing. A 4326 LineString carries
    lat/lon pairs only, and the ordinate count and the declared CRS now agree
    the way build_point's already do.
    """
    vertices = engine_geometry.vertices_of(line_geometry)
    element = etree.Element(Q_LINE_STRING, nsmap=NSMAP)
    element.set("srsName", srs_name)

    pos_list = etree.SubElement(element, Q_POS_LIST)
    pos_list.set("srsDimension", "2")
    pos_list.text = " ".join(
        _pos_text(lon, lat, None)
        for lon, lat, _height in vertices
    )
    return element


def build_circle(position: Position, radius_m: float) -> etree._Element:
    """§6.3's merged answer (decision 57).

    The core measured the centre and the radius; this renders them. The radius
    is the greatest geodesic distance from the averaged centre to any merged
    candidate, so the Circle reports an extent that was measured rather than an
    uncertainty that was assumed — which is why §7.4's anti-synthesis rule
    admits this one shape and no other.
    """
    element = etree.Element(Q_CIRCLE, nsmap=NSMAP)
    element.set("srsName", CRS_3D if position.is_3d else CRS_2D)
    pos = etree.SubElement(element, Q_POS)
    pos.text = _pos_text(position.longitude, position.latitude, position.altitude)
    radius = etree.SubElement(element, q(NS_GEOSHAPE, "radius"))
    radius.set("uom", UOM_METRE)
    radius.text = f"{radius_m:.3f}"
    return element


def build_confidence(value: float) -> etree._Element:
    """RFC 7459's confidence element (§7.4).

    The schema's decimal form is minExclusive 0.0 / maxExclusive 100.0, so
    neither bound is expressible as a number and the only other permitted value
    is the token "unknown". A confidence at or beyond either bound therefore
    serialises as "unknown" rather than being clamped to 99.999: clamping would
    report a number the service did not compute, and "unknown" is a value RFC
    7459 defines for exactly this. Spec decision 97 (Appendix C.4 Q5).

    pdf is left at its "unknown" default. RFC 7459 §2 ties normal and
    rectangular to a probability density over an uncertainty region, and §7.4's
    confidence is a match-quality dial rather than a statistical distribution —
    naming a pdf would assert a statistical claim the number does not carry.
    """
    element = etree.Element(Q_CONFIDENCE, nsmap={"conf": NSMAP["conf"]})
    if 0.0 < value < 100.0:
        element.text = f"{value:.1f}"
    else:
        element.text = "unknown"
    return element


def answer_geometry_element(
    *,
    position: Optional[Position],
    line_geometry=None,
    srs_name: str = CRS_2D,
    horizontal_uncertainty_m: Optional[float] = None,
) -> etree._Element:
    """The single geometry element an assembled answer serialises to.

    Dispatches §7.4's three cases: a merged position with a measured extent is a
    Circle, any other position is a Point, and no position at all means the
    answer is the segment's line.

    `srs_name` reaches only the line case — the Point and Circle builders read
    the CRS off the position's own dimensionality (decision 55). Its default is
    CRS_2D rather than None since decision 85: the caller supplies
    ForwardAnswer.crs, which no longer abstains for a line answer.
    """
    if position is not None:
        if horizontal_uncertainty_m is not None and horizontal_uncertainty_m > 0:
            return build_circle(position, horizontal_uncertainty_m)
        return build_point(position)

    if line_geometry is None:
        raise GmlParseError("an answer carries neither a position nor a geometry")
    return build_line_string(line_geometry, srs_name=srs_name)


def to_string(element: etree._Element) -> str:
    return etree.tostring(element, pretty_print=True).decode("utf-8")
