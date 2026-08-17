"""RFC 5491 §4/§5 on the wire — eight shapes in, three out.

§9 accepts all eight GeoShape forms because i3 §4.5 says only that the request
contains "a geodetic representation" and narrows the shape vocabulary nowhere.
Accepting only a Point would be a restriction i3 does not impose, which
decision 2's corollary forbids as firmly as adding capability — so "all eight
parse" is a conformance property, not a completeness nicety.
"""

from __future__ import annotations

import os

import pytest
from lxml import etree

from src.api.wire import gml_xml
from src.api.wire.gml_xml import GmlParseError
from src.api.wire.xml_ns import XML_PARSER
from src.engine.models import CRS_2D, CRS_3D, Position
from src.reverse import origin as shapes

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")

NS = (
    'xmlns:gml="http://www.opengis.net/gml" '
    'xmlns:gs="http://www.opengis.net/pidflo/1.0"'
)
LAT, LON = 46.810000, -100.780000


def _parse(xml_text: str):
    return gml_xml.parse_shape(etree.fromstring(xml_text.encode("utf-8"), XML_PARSER))


# ---------------------------------------------------------------------------
# The eight shapes (§9, decision 37)
# ---------------------------------------------------------------------------

POINT = f'<gml:Point {NS}><gml:pos>{LAT} {LON}</gml:pos></gml:Point>'

POLYGON = f"""<gml:Polygon {NS}><gml:exterior><gml:LinearRing>
  <gml:posList>46.809 -100.781 46.811 -100.781 46.811 -100.779 46.809 -100.779
               46.809 -100.781</gml:posList>
</gml:LinearRing></gml:exterior></gml:Polygon>"""

CIRCLE = f"""<gs:Circle {NS} srsName="urn:ogc:def:crs:EPSG::4326">
  <gml:pos>{LAT} {LON}</gml:pos>
  <gs:radius uom="urn:ogc:def:uom:EPSG::9001">150</gs:radius>
</gs:Circle>"""

ELLIPSE = f"""<gs:Ellipse {NS}>
  <gml:pos>{LAT} {LON}</gml:pos>
  <gs:semiMajorAxis uom="urn:ogc:def:uom:EPSG::9001">200</gs:semiMajorAxis>
  <gs:semiMinorAxis uom="urn:ogc:def:uom:EPSG::9001">100</gs:semiMinorAxis>
  <gs:orientation uom="urn:ogc:def:uom:EPSG::9102">45</gs:orientation>
</gs:Ellipse>"""

ARC_BAND = f"""<gs:ArcBand {NS}>
  <gml:pos>{LAT} {LON}</gml:pos>
  <gs:innerRadius uom="urn:ogc:def:uom:EPSG::9001">100</gs:innerRadius>
  <gs:outerRadius uom="urn:ogc:def:uom:EPSG::9001">300</gs:outerRadius>
  <gs:startAngle uom="urn:ogc:def:uom:EPSG::9102">0</gs:startAngle>
  <gs:openingAngle uom="urn:ogc:def:uom:EPSG::9102">90</gs:openingAngle>
</gs:ArcBand>"""

SPHERE = f"""<gs:Sphere {NS}>
  <gml:pos>{LAT} {LON} 500</gml:pos>
  <gs:radius uom="urn:ogc:def:uom:EPSG::9001">50</gs:radius>
</gs:Sphere>"""

ELLIPSOID = f"""<gs:Ellipsoid {NS}>
  <gml:pos>{LAT} {LON} 500</gml:pos>
  <gs:semiMajorAxis uom="urn:ogc:def:uom:EPSG::9001">200</gs:semiMajorAxis>
  <gs:semiMinorAxis uom="urn:ogc:def:uom:EPSG::9001">100</gs:semiMinorAxis>
  <gs:verticalAxis uom="urn:ogc:def:uom:EPSG::9001">30</gs:verticalAxis>
  <gs:orientation uom="urn:ogc:def:uom:EPSG::9102">45</gs:orientation>
</gs:Ellipsoid>"""

PRISM = f"""<gs:Prism {NS}>
  <gs:base><gml:Polygon><gml:exterior><gml:LinearRing>
    <gml:posList srsDimension="3">46.809 -100.781 500 46.811 -100.781 500
                                  46.811 -100.779 500</gml:posList>
  </gml:LinearRing></gml:exterior></gml:Polygon></gs:base>
  <gs:height uom="urn:ogc:def:uom:EPSG::9001">30</gs:height>
</gs:Prism>"""

ALL_EIGHT = {
    "Point": (POINT, shapes.Point),
    "Polygon": (POLYGON, shapes.Polygon),
    "Circle": (CIRCLE, shapes.Circle),
    "Ellipse": (ELLIPSE, shapes.Ellipse),
    "ArcBand": (ARC_BAND, shapes.ArcBand),
    "Sphere": (SPHERE, shapes.Sphere),
    "Ellipsoid": (ELLIPSOID, shapes.Ellipsoid),
    "Prism": (PRISM, shapes.Prism),
}


@pytest.mark.parametrize("name", sorted(ALL_EIGHT))
def test_every_rfc_5491_shape_parses_to_a_search_origin(name):
    """All eight forms reduce to exactly one origin by §7.5's centroid
    convention — footprint centroid for X/Y, vertical midpoint for Z — so
    nothing downstream of §9 branches on shape."""
    xml_text, expected_type = ALL_EIGHT[name]
    shape = _parse(xml_text)
    assert isinstance(shape, expected_type)

    origin = shapes.origin_of(shape)
    assert -180 <= origin.longitude <= 180
    assert -90 <= origin.latitude <= 90
    assert origin.extent_m >= 0
    assert origin.shape is shape


def test_coordinate_order_on_the_wire_is_lat_lon():
    """RFC 5491 §4 / GML with EPSG::4326 is latitude first; the engine works
    longitude first. The swap happens here and only here (§7.1)."""
    point = _parse(POINT)
    assert point.latitude == pytest.approx(46.81)
    assert point.longitude == pytest.approx(-100.78)


def test_a_point_has_no_extent_and_therefore_contains_nothing():
    """§10.3 depends on this: the commonest input in the system never reaches
    the containment rule and orders by pure proximity."""
    origin = shapes.origin_of(_parse(POINT))
    assert origin.extent_m == 0.0
    assert origin.has_extent is False
    assert origin.shape.contains(LON, LAT) is False


def test_a_circle_yields_its_centre_and_its_radius_as_extent():
    origin = shapes.origin_of(_parse(CIRCLE))
    assert origin.latitude == pytest.approx(46.81)
    assert origin.extent_m == pytest.approx(150.0)
    assert origin.shape.contains(LON, LAT) is True


def test_a_prism_yields_its_footprint_centroid_at_mid_height():
    """§7.5 — the vertical midpoint, not the floor. Naming floor 1 of a
    twenty-storey structure puts a responder up to sixty metres out."""
    origin = shapes.origin_of(_parse(PRISM))
    assert origin.altitude == pytest.approx(515.0)  # base 500 + height 30 / 2
    assert origin.vertical_extent_m == pytest.approx(30.0)


def test_an_arc_band_origin_lands_inside_the_band():
    """RFC 5491's centre is the arc's apex, which lies OUTSIDE the band. Using
    it as the origin would put the origin outside the caller's own query shape
    and make containment behave absurdly, so §7.5's footprint centroid is taken
    literally and the annular sector's centroid computed instead."""
    shape = _parse(ARC_BAND)
    origin = shapes.origin_of(shape)
    assert shape.contains(origin.longitude, origin.latitude) is True


def test_a_polygon_ring_closing_vertex_is_not_counted_twice():
    """GML closes a ring by repeating the first vertex. Counting it twice would
    drag the centroid toward that corner."""
    polygon = _parse(POLYGON)
    assert len(polygon.vertices) == 4
    origin = shapes.origin_of(polygon)
    assert origin.latitude == pytest.approx(46.810, abs=1e-6)
    assert origin.longitude == pytest.approx(-100.780, abs=1e-6)


def test_a_polygon_accepts_the_pos_spelling_as_well_as_poslist():
    """Both GML spellings are legal and both appear in the wild."""
    xml_text = f"""<gml:Polygon {NS}><gml:exterior><gml:LinearRing>
      <gml:pos>46.809 -100.781</gml:pos>
      <gml:pos>46.811 -100.781</gml:pos>
      <gml:pos>46.811 -100.779</gml:pos>
    </gml:LinearRing></gml:exterior></gml:Polygon>"""
    assert len(_parse(xml_text).vertices) == 3


# ---------------------------------------------------------------------------
# What does not parse
# ---------------------------------------------------------------------------

def test_a_shape_outside_the_eight_is_refused():
    xml_text = f'<gml:LineString {NS}><gml:posList>0 0 1 1</gml:posList></gml:LineString>'
    with pytest.raises(GmlParseError, match="not one of the eight"):
        _parse(xml_text)


def test_a_solid_with_no_height_is_refused_rather_than_defaulted():
    """A zero would be a specific claim about height the caller did not make.
    §3.7's whole posture (decision 55) is that an unpopulated vertical slot
    asserts nothing, so inventing one here would contradict it."""
    xml_text = f"""<gs:Sphere {NS}>
      <gml:pos>{LAT} {LON}</gml:pos>
      <gs:radius uom="urn:ogc:def:uom:EPSG::9001">50</gs:radius>
    </gs:Sphere>"""
    with pytest.raises(GmlParseError, match="without inventing one"):
        _parse(xml_text)


def test_a_non_numeric_coordinate_is_refused():
    xml_text = f'<gml:Point {NS}><gml:pos>north west</gml:pos></gml:Point>'
    with pytest.raises(GmlParseError):
        _parse(xml_text)


# ---------------------------------------------------------------------------
# The write side (§8, decision 30)
# ---------------------------------------------------------------------------

def test_a_2d_position_declares_epsg_4326_and_writes_two_ordinates():
    """Dimensionality follows the data (§3.7.1, decision 55), so the declared
    CRS and the ordinate count always agree."""
    element = gml_xml.build_point(Position(longitude=LON, latitude=LAT))
    assert element.get("srsName") == CRS_2D
    assert len(element[0].text.split()) == 2


def test_a_3d_position_declares_epsg_4979_and_writes_three():
    element = gml_xml.build_point(
        Position(longitude=LON, latitude=LAT, altitude=512.0)
    )
    assert element.get("srsName") == CRS_3D
    assert len(element[0].text.split()) == 3


def test_the_written_point_is_lat_lon():
    rendered = gml_xml.to_string(gml_xml.build_point(Position(LON, LAT)))
    assert "46.81" in rendered.split("<gml:pos>")[1].split()[0]


def test_a_rung_3_line_answer_declares_4326_rather_than_omitting_srsname():
    """Decision 85 (resolves Q22) — this test asserted srsName was ABSENT while
    Q22 was open, because Candidate.crs abstained between 4326 and 4979 and GML
    makes the attribute optional, so absence rendered the abstention honestly.
    Decision 85 supplies the CRS instead: RoadCenterLine is not a declared
    3D-capable feature class (§10.5), so a rung-3 answer is 2D at EPSG:4326.
    Q22's own closing observation — that a consumer requiring a CRS on every
    geometry would see the gap — is honoured by filling it."""
    from shapely.geometry import LineString

    element = gml_xml.build_line_string(
        LineString([(-100.78, 46.81), (-100.77, 46.81)])
    )
    assert element.get("srsName") == CRS_2D
    assert element[0].get("srsDimension") == "2"


def test_a_rung_3_line_drops_the_layers_per_vertex_z():
    """The half of decision 85 that is a real wire change rather than an added
    attribute. The provisioned RoadCenterLine layer is MultiLineString Z, so
    every vertex carries a Z slot, and this builder used to write all three
    ordinates with srsDimension="3" — a 3D coordinate list with no srsName,
    which asserted more than the abstention claimed to. The Z is an export
    artifact, never authoritative attribution (§10.5), so a 4326 LineString
    carries lat/lon pairs only and the ordinate count agrees with the declared
    CRS."""
    from shapely.geometry import LineString

    element = gml_xml.build_line_string(
        LineString([(-100.78, 46.81, 500.0), (-100.77, 46.81, 502.5)])
    )

    assert element.get("srsName") == CRS_2D
    assert element[0].get("srsDimension") == "2"
    ordinates = element[0].text.split()
    assert len(ordinates) == 4  # two vertices, two values each
    assert "500" not in element[0].text and "502" not in element[0].text


def test_the_merged_case_writes_a_circle_with_the_measured_radius():
    """Decision 57 — §7.4's anti-synthesis rule is scoped to single matches. The
    merged case genuinely measured an extent, so the Circle reports a
    measurement rather than dressing up a guess."""
    element = gml_xml.answer_geometry_element(
        position=Position(LON, LAT), horizontal_uncertainty_m=42.5
    )
    assert etree.QName(element).localname == "Circle"
    radius = element[1]
    assert float(radius.text) == pytest.approx(42.5)
    assert radius.get("uom") == gml_xml.UOM_METRE


def test_an_unmerged_position_writes_a_point_not_a_circle():
    """No synthesised uncertainty shape around a single match (§7.4)."""
    element = gml_xml.answer_geometry_element(position=Position(LON, LAT))
    assert etree.QName(element).localname == "Point"


# ---------------------------------------------------------------------------
# RFC 7459 confidence
# ---------------------------------------------------------------------------

def test_confidence_serialises_as_a_decimal_inside_the_open_interval():
    element = gml_xml.build_confidence(80.0)
    assert float(element.text) == pytest.approx(80.0)


@pytest.mark.parametrize("value", [0.0, 100.0, -1.0, 101.0])
def test_confidence_at_or_beyond_the_bounds_serialises_as_unknown(value):
    """RFC 7459's schema is minExclusive 0.0 / maxExclusive 100.0, so neither
    bound is expressible as a number and "unknown" is the only other permitted
    value. Clamping to 99.999 would report a number the service did not compute
    (spec Appendix C.4 Q5)."""
    assert gml_xml.build_confidence(value).text == "unknown"


def test_confidence_validates_against_the_master_schema():
    from src.app import lifecycle

    schema = lifecycle._load_schema()
    assert schema is not None
    for value in (0.0, 50.0, 100.0):
        element = etree.fromstring(
            gml_xml.to_string(gml_xml.build_confidence(value)).encode("utf-8")
        )
        assert schema.validate(element), schema.error_log.last_error
