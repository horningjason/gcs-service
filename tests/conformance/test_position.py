"""§7 position derivation (src/geocode/position.py) and its geodesic base.

Weighted towards the three edge cases the specification settled explicitly
because they are the ones an implementer gets wrong quietly: the zero-length
range (decision 48), parity's scope (decision 49), and geometry-only Z at
rung 1 (decision 55).
"""

from __future__ import annotations

import pytest
from shapely import wkt

from src.engine import geometry
from src.engine.models import (
    CRS_2D,
    CRS_3D,
    DataQualityFlag,
    LocationType,
    RclGisRecord,
    Side,
    SsapGisRecord,
)
from src.geocode import position
from src.gis.records import RCLRecord, SSAPRecord

# A ~1.5 km east-west segment near Bismarck, digitised west to east.
SEGMENT = "LINESTRING (-100.800 46.810, -100.780 46.810)"


def _rcl(**kwargs) -> RCLRecord:
    kwargs.setdefault("fid", 1)
    kwargs.setdefault("NGUID", "{RCL}")
    kwargs.setdefault("geometry_wkt", SEGMENT)
    return RclGisRecord.from_record(RCLRecord(**kwargs))


def _ssap(**kwargs) -> SsapGisRecord:
    kwargs.setdefault("fid", 1)
    kwargs.setdefault("NGUID", "{SSAP}")
    return SsapGisRecord.from_record(SSAPRecord(**kwargs))


# ---------------------------------------------------------------------------
# Rung 1 — geometry-only Z (decision 55) as the forward path uses it
# ---------------------------------------------------------------------------

def test_rung1_zero_geometry_z_yields_a_2d_answer():
    """The provisioned data's shape, arriving at §7.1 through the forward path.

    Every SSAP feature is declared Point Z with a zero ordinate. Decision 55
    makes that an empty slot, so the derived position is 2D at EPSG:4326 — not
    EPSG:4979 at 0 m HAE, which at Bismarck is roughly 500 m underground.
    """
    derived = position.ssap_position(_ssap(geometry_wkt="POINT Z (-100.78 46.81 0)"))

    assert derived.altitude is None
    assert derived.is_3d is False
    assert derived.crs == CRS_2D


def test_rung1_zero_geometry_z_ignores_a_populated_elevation():
    """The columns are not a fallback at rung 1 any more than anywhere else."""
    derived = position.ssap_position(
        _ssap(geometry_wkt="POINT Z (-100.78 46.81 0)", Elevation=511.6, Altitude=512.4)
    )

    assert derived.altitude is None
    assert derived.crs == CRS_2D


def test_rung1_non_zero_geometry_z_is_carried():
    derived = position.ssap_position(
        _ssap(geometry_wkt="POINT Z (-100.78 46.81 512.4)")
    )

    assert derived.altitude == 512.4
    assert derived.crs == CRS_3D


def test_rung1_unlocatable_record_derives_no_position():
    record = _ssap(geometry_wkt=None, Longitude=-100.78, Latitude=46.81)

    assert position.ssap_position(record) is None
    assert record.has_flag(DataQualityFlag.NO_GEOMETRY)


# ---------------------------------------------------------------------------
# Decision 48 — zero-length ranges
# ---------------------------------------------------------------------------

def test_zero_length_range_returns_the_segment_midpoint():
    """From equals To: the side asserts one address and says nothing about
    where on the block it sits. The fraction would be 0/0."""
    record = _rcl(FromAddr_L=101, ToAddr_L=101, Parity_L="O")
    placed = position.interpolate(record, 101, offset_m=10.0, endpoint_margin_m=15.0)

    vertices = geometry.vertices_of(record.geometry)
    expected = geometry.midpoint(vertices)

    assert placed is not None
    assert placed.distance_along_m == pytest.approx(geometry.length_m(vertices) / 2.0)
    # Offset aside, the along-track position is the midpoint.
    assert geometry.distance_m(
        placed.position.longitude, placed.position.latitude, expected[0], expected[1]
    ) == pytest.approx(10.0, abs=0.5)


def test_zero_length_range_does_not_apply_the_endpoint_margin():
    """Decision 48 is explicit: the margin does not participate, a midpoint
    being nowhere near an endpoint."""
    record = _rcl(FromAddr_L=101, ToAddr_L=101, Parity_L="O")

    wide = position.interpolate(record, 101, offset_m=10.0, endpoint_margin_m=15.0)
    narrow = position.interpolate(record, 101, offset_m=10.0, endpoint_margin_m=400.0)

    assert wide.margin_applied is False
    assert narrow.margin_applied is False
    assert wide.distance_along_m == pytest.approx(narrow.distance_along_m)


def test_zero_length_range_is_tiered_interpolated_point():
    """Ceiling 75 — the answer is a position, not a corridor, but it is not an
    address point either."""
    record = _rcl(FromAddr_L=101, ToAddr_L=101, Parity_L="O")
    placed = position.interpolate(record, 101, offset_m=10.0, endpoint_margin_m=15.0)

    assert placed.location_type is LocationType.INTERPOLATED_POINT
    assert placed.location_type.ceiling == 75.0


def test_single_address_range_needs_no_separate_rule():
    """Decision 48: a side carrying one address expresses it as From == To and
    is handled by the rule above. Nothing else is required."""
    record = _rcl(FromAddr_L=101, ToAddr_L=101, Parity_L="O")
    assert position.interpolate(record, 101, offset_m=10.0, endpoint_margin_m=15.0)


def test_a_two_address_range_interpolates_normally():
    """The contrast case: From 100, To 102, parity even carries two addresses,
    and the margin is exactly what draws each endpoint inward."""
    record = _rcl(FromAddr_L=100, ToAddr_L=102, Parity_L="E")
    low = position.interpolate(record, 100, offset_m=10.0, endpoint_margin_m=15.0)
    high = position.interpolate(record, 102, offset_m=10.0, endpoint_margin_m=15.0)

    assert low.margin_applied is True
    assert low.distance_along_m == pytest.approx(15.0)
    assert high.distance_along_m == pytest.approx(
        geometry.length_m(geometry.vertices_of(record.geometry)) - 15.0
    )


# ---------------------------------------------------------------------------
# Decision 49 — parity governs side selection, never the match
# ---------------------------------------------------------------------------

def test_parity_selects_the_side():
    record = _rcl(
        FromAddr_L=100, ToAddr_L=200, Parity_L="E",
        FromAddr_R=101, ToAddr_R=201, Parity_R="O",
    )
    assert position.select_side(record, 150).side is Side.LEFT
    assert position.select_side(record, 151).side is Side.RIGHT


def test_parity_never_blocks_a_match_within_the_asserted_range():
    """The decision's sharp end: a side marked even whose range is 100-101, and
    a query for 101. The asserted range governs and the match proceeds — a
    caller asking for a number the data contains receives it.
    """
    record = _rcl(FromAddr_L=100, ToAddr_L=101, Parity_L="E")

    chosen = position.select_side(record, 101)
    assert chosen is not None
    assert chosen.side is Side.LEFT
    assert chosen.parity_admits(101) is False  # the field does contradict itself

    placed = position.interpolate(record, 101, offset_m=10.0, endpoint_margin_m=15.0)
    assert placed is not None


def test_a_parity_defect_is_not_repaired_on_the_wire():
    """§11.3 and §11.4's posture, applied here: the GCS reports what the record
    says. The contradictory Parity_L is passed through untouched."""
    record = _rcl(FromAddr_L=100, ToAddr_L=101, Parity_L="E")
    assert record.source.Parity_L == "E"


def test_a_number_no_side_asserts_falls_through_to_rung_3():
    record = _rcl(FromAddr_L=100, ToAddr_L=200, Parity_L="E")

    assert position.select_side(record, 5000) is None
    assert position.interpolate(record, 5000, offset_m=10.0, endpoint_margin_m=15.0) is None
    assert position.segment_geometry(record) is not None


def test_parity_z_means_the_side_carries_no_addresses():
    """Z is 1,196 of the provisioned left sides. It is a stronger statement
    than an absent value: the side asserts nothing, so it cannot be chosen."""
    record = _rcl(
        FromAddr_L=0, ToAddr_L=0, Parity_L="Z",
        FromAddr_R=101, ToAddr_R=201, Parity_R="O",
    )
    chosen = position.select_side(record, 101)

    assert chosen is not None and chosen.side is Side.RIGHT


def test_parity_both_admits_either_number():
    record = _rcl(FromAddr_L=100, ToAddr_L=200, Parity_L="B")

    assert position.select_side(record, 150).parity_admits(150) is True
    assert position.select_side(record, 151).parity_admits(151) is True


# ---------------------------------------------------------------------------
# §7.3 setback
# ---------------------------------------------------------------------------

def test_the_position_is_never_left_on_the_centerline():
    """§7.3's MUST. The offset is what distinguishes a derived address position
    from a point in the middle of the road."""
    record = _rcl(FromAddr_L=100, ToAddr_L=200, Parity_L="E")
    placed = position.interpolate(record, 150, offset_m=10.0, endpoint_margin_m=15.0)

    vertices = geometry.vertices_of(record.geometry)
    on_line = geometry.interpolate_m(vertices, placed.distance_along_m)
    away = geometry.distance_m(
        placed.position.longitude, placed.position.latitude, on_line[0], on_line[1]
    )

    assert away == pytest.approx(10.0, abs=0.5)


def test_left_and_right_offsets_fall_on_opposite_sides():
    record = _rcl(
        FromAddr_L=100, ToAddr_L=200, Parity_L="E",
        FromAddr_R=101, ToAddr_R=201, Parity_R="O",
    )
    left = position.interpolate(record, 150, offset_m=10.0, endpoint_margin_m=15.0)
    right = position.interpolate(record, 151, offset_m=10.0, endpoint_margin_m=15.0)

    # Digitised west to east, so left is north and right is south.
    assert left.position.latitude > right.position.latitude


def test_a_zero_offset_is_a_configuration_error():
    """Silently returning the centerline position would put a dispatched
    location in the middle of the road."""
    with pytest.raises(ValueError):
        geometry.offset_perpendicular(-100.78, 46.81, 90.0, 0.0, to_left=True)


# ---------------------------------------------------------------------------
# Decision 53 — multi-part segments are refused, not guessed at
# ---------------------------------------------------------------------------

def test_a_multipart_segment_is_not_interpolated():
    record = _rcl(
        geometry_wkt=(
            "MULTILINESTRING ((-100.800 46.810, -100.790 46.810),"
            " (-100.785 46.810, -100.780 46.810))"),
        FromAddr_L=100, ToAddr_L=200, Parity_L="E",
    )

    assert record.is_multipart is True
    assert position.interpolate(record, 150, offset_m=10.0, endpoint_margin_m=15.0) is None
    assert position.segment_geometry(record) is None


def test_a_single_part_multilinestring_interpolates_normally():
    record = _rcl(
        geometry_wkt="MULTILINESTRING ((-100.800 46.810, -100.780 46.810))",
        FromAddr_L=100, ToAddr_L=200, Parity_L="E",
    )
    assert position.interpolate(record, 150, offset_m=10.0, endpoint_margin_m=15.0)


# ---------------------------------------------------------------------------
# Rung 2 carries no Z (spec Appendix C.4 R1, generalized by decision 85)
# ---------------------------------------------------------------------------

def test_an_interpolated_result_is_2d_even_where_the_segment_carries_z():
    """R1: the only Z available is road surface, and §7.3 has just moved the
    position horizontally off the road onto a parcel.

    Unchanged by decision 85, and deliberately kept as the guard that says so.
    Decision 85 makes rung 3 2D as well, on the broader ground that
    RoadCenterLine is not a declared 3D-capable class at all (§10.5) — it
    generalizes R1 rather than altering it, so rung 2's behaviour here must not
    move. R1's original horizontal-displacement argument still holds for this
    rung; it was simply narrower than R1's scope needed."""
    record = _rcl(
        geometry_wkt="LINESTRING Z (-100.800 46.810 500, -100.780 46.810 505)",
        FromAddr_L=100, ToAddr_L=200, Parity_L="E",
    )
    placed = position.interpolate(record, 150, offset_m=10.0, endpoint_margin_m=15.0)

    assert placed.position.altitude is None
    assert placed.position.crs == CRS_2D
    # The record layer still keeps it — §10.5 reads this same geometry.
    assert "Z" in record.source.geometry_wkt


# ---------------------------------------------------------------------------
# The geodesic base
# ---------------------------------------------------------------------------

def test_distances_are_metres_not_degrees():
    """§10.2, decision 40. 0.02 degrees of longitude at 46.81 N is about
    1.5 km, and nothing in this service ever measures it as 0.02."""
    metres = geometry.distance_m(-100.800, 46.810, -100.780, 46.810)
    assert 1500 < metres < 1550


def test_interpolation_walks_the_bend_not_the_chord():
    """§7.2 — proportional along actual vertex geometry, bends and curves. A
    right-angled path is measurably longer than its chord, and the midpoint by
    distance sits on the path rather than across it."""
    dogleg = geometry.vertices_of(
        wkt.loads(
            "LINESTRING (-100.800 46.810, -100.790 46.810, -100.790 46.820)")
    )
    chord = geometry.distance_m(-100.800, 46.810, -100.790, 46.820)

    assert geometry.length_m(dogleg) > chord
    midpoint = geometry.midpoint(dogleg)
    assert midpoint[0] == pytest.approx(-100.790, abs=1e-3)


def test_interpolation_clamps_outside_the_path():
    vertices = geometry.vertices_of(
        wkt.loads(SEGMENT))

    assert geometry.interpolate_m(vertices, -50)[0] == pytest.approx(-100.800)
    assert geometry.interpolate_m(vertices, 1e9)[0] == pytest.approx(-100.780)


def test_multipart_geometry_is_refused_by_the_vertex_walker():
    """The backstop behind RclGisRecord.is_multipart."""
    multi = wkt.loads(
        "MULTILINESTRING ((0 0, 1 1), (2 2, 3 3))")
    with pytest.raises(ValueError):
        geometry.vertices_of(multi)


def test_z_is_interpolated_within_a_leg_where_the_vertices_carry_it():
    """§3.7.1 — one interpolation carrying whatever dimensions the vertices
    have. Rung 2 declines to propagate the result (R1); the primitive still
    computes it, because §10.5 reads the vertical band from this geometry."""
    vertices = geometry.vertices_of(
        wkt.loads(
            "LINESTRING Z (-100.800 46.810 500, -100.780 46.810 600)"))
    total = geometry.length_m(vertices)
    _, _, height = geometry.interpolate_m(vertices, total / 2.0)

    assert height == pytest.approx(550.0, abs=1.0)


def test_degenerate_geometry_does_not_crash_the_walker():
    with pytest.raises(ValueError):
        geometry.vertices_of(None)
    with pytest.raises(ValueError):
        geometry.vertices_of(
            wkt.loads("POINT (0 0)"))
