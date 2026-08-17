"""The engine element model (src/engine/models.py).

Weighted towards decision 55 — position comes from the shape geometry and from
nothing else. It is the one rule in this model whose failure mode is silent
rather than loud: every way of getting it wrong produces a well-formed
response. A placeholder Z reported as a height places a dispatched address
roughly 500 m below ground; a height borrowed from a column produces a
coordinate no single source in the data asserts; an attribute-column fallback
produces a located match for a record that has no shape. None of the three is
visible on the i3 interface, which §8.1 gives no vocabulary to qualify.

Decision 55 supersedes 51 and 52. The tests that asserted the old fall-through
into Altitude and Elevation now assert the opposite, and several of them are
kept deliberately in that inverted form — a populated Elevation sitting unread
beside a zero geometry Z is the sharp end of the change.

Decision 53 (multi-part centerline detection) is covered for the same reason at
lower stakes: a segment silently concatenated in storage order still returns a
position, just not one anybody chose.
"""

from __future__ import annotations

import math

import pytest

from src.engine.models import (
    CIVIC_ELEMENTS,
    CRS_2D,
    CRS_3D,
    NON_CIVIC_SSAP_COLUMNS,
    TIER_CEILINGS,
    Candidate,
    CivicAddress,
    DataQualityFlag,
    LocationType,
    MatchQuality,
    Position,
    RclGisRecord,
    Side,
    SsapGisRecord,
    z_is_admissible,
)
from src.gis.records import SSAP_COLUMNS, RCLRecord, SSAPRecord


def _ssap(**kwargs) -> SSAPRecord:
    kwargs.setdefault("fid", 1)
    kwargs.setdefault("NGUID", "{ABC}")
    return SSAPRecord(**kwargs)


def _rcl(**kwargs) -> RCLRecord:
    kwargs.setdefault("fid", 1)
    kwargs.setdefault("NGUID", "{DEF}")
    return RCLRecord(**kwargs)


# ---------------------------------------------------------------------------
# Decision 55 — the admission test, now applied to the geometry's own Z
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, 0.0, -0.0, 0, float("nan")])
def test_null_and_zero_are_both_inadmissible(value):
    """Decision 51's test, carried forward by 55 unchanged: absence and a
    placeholder are treated alike, because presence alone carries no
    information about height.

    -0.0 and integer 0 are included because the source is a GIS export, not a
    hand-written literal; 0.0 == -0.0 == 0 and all three must fail the test.
    NaN is included because a geometry ordinate does not pass through the row
    conversion that normalises NaN to None.
    """
    assert z_is_admissible(value) is False


@pytest.mark.parametrize("value", [511.6, -3.2, 0.001, -0.001, 1e-9])
def test_any_non_zero_value_is_admissible(value):
    """The test is non-zero, not 'large enough'. There is no magnitude
    threshold to tune — that would be a second, invented rule."""
    assert z_is_admissible(value) is True


def test_zero_elevation_survives_row_conversion_and_still_fails_admission():
    """Two layers, two different jobs, and they must not be confused.

    src/gis/records.py deliberately keeps 0.0 as a value rather than
    normalising it to None — there is a test asserting exactly that. Admission
    operates a rung above: the record faithfully carries what the SI wrote, and
    the test decides whether it asserts a height.
    """
    from src.gis import records

    assert records._plain(0.0) == 0.0
    assert z_is_admissible(0.0) is False


# --- Z comes from the geometry, or from nowhere -----------------------------

def test_a_non_zero_geometry_z_is_used():
    record = _ssap(geometry_wkt="POINT Z (-100.78 46.81 512.4)")
    position = SsapGisRecord.from_record(record).position

    assert position.altitude == 512.4
    assert position.is_3d is True
    assert position.crs == CRS_3D


def test_placeholder_geometry_z_yields_a_2d_position():
    """The shape of every SSAP feature in the provisioned data: declared
    Point Z, ordinate uniformly zero. Reported as a height this is EPSG:4979 at
    0 m HAE — roughly 500 m below ground at Bismarck.
    """
    record = _ssap(geometry_wkt="POINT Z (-100.78 46.81 0)")
    position = SsapGisRecord.from_record(record).position

    assert position.altitude is None
    assert position.is_3d is False
    assert position.crs == CRS_2D


def test_two_dimensional_geometry_yields_a_2d_position():
    record = _ssap(geometry_wkt="POINT (-100.78 46.81)")
    position = SsapGisRecord.from_record(record).position

    assert position.altitude is None
    assert position.crs == CRS_2D


def test_a_populated_elevation_does_not_rescue_a_placeholder_z():
    """The sharp behavioural reversal from decision 51.

    This is the 8.5% of records that carry real vertical data, and under the
    superseded chain this exact record answered 511.6 m at EPSG:4979. Under
    decision 55 the column is not consulted: the geometry's Z is a zero
    placeholder, so the point is 2D and the surveyed elevation goes unread.

    The height is not wrong — it is unread on purpose. Mixing it with X and Y
    from the geometry would produce a coordinate no single source asserts.
    """
    record = _ssap(
        geometry_wkt="POINT Z (-100.78 46.81 0)",
        Altitude=None,
        Elevation=511.6,
    )
    position = SsapGisRecord.from_record(record).position

    assert position.altitude is None
    assert position.is_3d is False
    assert position.crs == CRS_2D


def test_a_populated_altitude_does_not_rescue_a_placeholder_z():
    """Altitude sits on the same footing as Elevation under decision 55, even
    though STA-006.3 makes it the geometry Z's own measurement."""
    record = _ssap(geometry_wkt="POINT Z (-100.78 46.81 0)", Altitude=512.4)
    position = SsapGisRecord.from_record(record).position

    assert position.altitude is None
    assert position.crs == CRS_2D


def test_columns_are_unread_even_with_no_z_ordinate_at_all():
    """Not merely "the placeholder loses" — there is no fall-through path. A
    2D geometry beside populated vertical columns is still a 2D position."""
    record = _ssap(
        geometry_wkt="POINT (-100.78 46.81)", Altitude=512.4, Elevation=511.6)
    position = SsapGisRecord.from_record(record).position

    assert position.altitude is None
    assert position.crs == CRS_2D


def test_the_geometry_z_is_used_even_where_the_columns_disagree():
    """Decision 55 is not a precedence rule with the columns ranked lower —
    they are not in the comparison at all, so a disagreement is not resolved
    so much as never posed."""
    record = _ssap(
        geometry_wkt="POINT Z (-100.78 46.81 512.4)",
        Altitude=99.0,
        Elevation=1.0,
    )
    assert SsapGisRecord.from_record(record).position.altitude == 512.4


# --- X and Y come from the geometry, or from nowhere ------------------------

def test_x_and_y_come_from_the_geometry():
    record = _ssap(
        geometry_wkt="POINT (-100.78 46.81)", Longitude=-99.0, Latitude=45.0)
    position = SsapGisRecord.from_record(record).position

    assert (position.longitude, position.latitude) == (-100.78, 46.81)


def test_no_geometry_yields_no_position_and_is_flagged():
    """Decision 55: a record with no shape is not a located match."""
    gis = SsapGisRecord.from_record(_ssap(geometry_wkt=None))

    assert gis.position is None
    assert gis.has_flag(DataQualityFlag.NO_GEOMETRY)
    assert gis.is_located is False


def test_populated_columns_do_not_rescue_a_record_with_no_geometry():
    """The other half of the same rule, and the one an implementer is most
    likely to undo by accident: the columns hold a perfectly good coordinate
    and are still not read. Answering from them would manufacture a located
    match for a record the SI never drew a shape for.
    """
    gis = SsapGisRecord.from_record(
        _ssap(geometry_wkt=None, Longitude=-100.78, Latitude=46.81,
              Elevation=511.6))

    assert gis.position is None
    assert gis.is_located is False
    assert gis.has_flag(DataQualityFlag.NO_GEOMETRY)
    # The columns are still on the record — unread, not discarded.
    assert gis.source.Longitude == -100.78


def test_unusable_geometry_is_flagged_like_absent_geometry():
    """One condition, because it has one consequence. Which of the two it was
    stays recoverable from the record's own geometry_wkt."""
    gis = SsapGisRecord.from_record(_ssap(geometry_wkt="POINT ZZ (nope)"))

    assert gis.geometry is None
    assert gis.position is None
    assert gis.is_located is False
    assert gis.has_flag(DataQualityFlag.NO_GEOMETRY)
    assert gis.source.geometry_wkt == "POINT ZZ (nope)"


def test_empty_geometry_is_unusable():
    gis = SsapGisRecord.from_record(_ssap(geometry_wkt="POINT EMPTY"))

    assert gis.is_located is False
    assert gis.has_flag(DataQualityFlag.NO_GEOMETRY)


def test_a_non_point_on_the_address_point_layer_is_unusable():
    """SSAP is provisioned Point Z. Anything else there is a shape this model
    has no rule for reading a single position from, so it is flagged rather
    than guessed at — a centroid here would be an invented rule."""
    gis = SsapGisRecord.from_record(
        _ssap(geometry_wkt="LINESTRING (-100.78 46.81, -100.77 46.82)"))

    assert gis.position is None
    assert gis.is_located is False
    assert gis.has_flag(DataQualityFlag.NO_GEOMETRY)


def test_a_usable_record_is_located():
    gis = SsapGisRecord.from_record(_ssap(geometry_wkt="POINT (-100.78 46.81)"))

    assert gis.is_located is True
    assert gis.flags == frozenset()


# ---------------------------------------------------------------------------
# Decision 53 — multi-part centerline detection
# ---------------------------------------------------------------------------

def test_multipart_segment_is_flagged():
    record = _rcl(geometry_wkt=(
        "MULTILINESTRING Z ((-101.7 46.8 500, -101.6 46.9 505),"
        " (-101.5 46.9 505, -101.4 47.0 510))"))
    gis = RclGisRecord.from_record(record)

    assert gis.part_count == 2
    assert gis.is_multipart is True
    assert gis.has_flag(DataQualityFlag.MULTIPART_SEGMENT)


def test_single_part_multilinestring_is_not_multipart():
    """The provisioned layer declares MultiLineString for every feature, so the
    container says nothing on its own — only the part count does. Flagging on
    the type would flag the entire layer and make the signal useless."""
    record = _rcl(geometry_wkt=(
        "MULTILINESTRING Z ((-101.7 46.8 500, -101.6 46.9 505))"))
    gis = RclGisRecord.from_record(record)

    assert gis.part_count == 1
    assert gis.is_multipart is False
    assert not gis.has_flag(DataQualityFlag.MULTIPART_SEGMENT)


def test_plain_linestring_is_single_part():
    gis = RclGisRecord.from_record(
        _rcl(geometry_wkt="LINESTRING (-101.7 46.8, -101.6 46.9)"))

    assert gis.part_count == 1
    assert gis.is_multipart is False


@pytest.mark.parametrize("parts", [3, 5])
def test_detection_holds_beyond_two_parts(parts):
    chunks = ", ".join(
        f"(-101.{i} 46.8, -101.{i} 46.9)" for i in range(parts))
    gis = RclGisRecord.from_record(
        _rcl(geometry_wkt=f"MULTILINESTRING ({chunks})"))

    assert gis.part_count == parts
    assert gis.is_multipart is True


def test_multipart_geometry_is_carried_not_discarded():
    """Flagged, not dropped. §10.5's reverse-side search reads this geometry,
    and a multi-part segment is still the nearest feature to something."""
    record = _rcl(geometry_wkt=(
        "MULTILINESTRING ((-101.7 46.8, -101.6 46.9),"
        " (-101.5 46.9, -101.4 47.0))"))
    gis = RclGisRecord.from_record(record)

    assert gis.geometry is not None
    assert gis.geometry_type == "MultiLineString"
    assert gis.source is record


def test_detection_does_not_file_a_discrepancy_report():
    """Decision 99 settles what the GCS files about, and filing now exists
    (src/discrepancy/discrepancy_report.py) — but not here. from_record()
    stays a pure construction step: it records the flag and does nothing
    else, no raise, no outbound call. Filing is the job of the call sites
    that consume the resulting GisRecord (src/geocode/candidates.py,
    src/reverse/search.py — see tests/conformance/test_reverse_search.py's
    filing tests), never the engine's own model construction."""
    gis = RclGisRecord.from_record(_rcl(geometry_wkt=(
        "MULTILINESTRING ((0 0, 1 1), (2 2, 3 3))")))

    assert gis.flags == frozenset({DataQualityFlag.MULTIPART_SEGMENT})


# ---------------------------------------------------------------------------
# locationType tiers (§7.4, decision 31)
# ---------------------------------------------------------------------------

def test_tiers_are_ordered_by_precision():
    assert (LocationType.STREET_SEGMENT
            < LocationType.INTERPOLATED_POINT
            < LocationType.ADDRESS_POINT
            < LocationType.FOOTPRINT_2D
            < LocationType.SPACE_3D)


def test_the_most_precise_tier_sorts_last():
    tiers = [LocationType.ADDRESS_POINT, LocationType.SPACE_3D,
             LocationType.STREET_SEGMENT]
    assert max(tiers) is LocationType.SPACE_3D


def test_tier_ceilings_are_the_specified_values():
    """Fixed in the specification, not configured, so that two GCS
    implementations cannot disagree about what a confidence value means."""
    assert TIER_CEILINGS == {
        LocationType.SPACE_3D: 100.0,
        LocationType.FOOTPRINT_2D: 90.0,
        LocationType.ADDRESS_POINT: 80.0,
        LocationType.INTERPOLATED_POINT: 75.0,
        LocationType.STREET_SEGMENT: 50.0,
    }


def test_ceilings_decrease_with_precision():
    ordered = sorted(LocationType, reverse=True)
    ceilings = [tier.ceiling for tier in ordered]
    assert ceilings == sorted(ceilings, reverse=True)


@pytest.mark.parametrize("geometry_type,derived,expected", [
    ("Point", False, LocationType.ADDRESS_POINT),
    ("MultiPoint", False, LocationType.ADDRESS_POINT),
    ("LineString", True, LocationType.INTERPOLATED_POINT),
    ("MultiLineString", True, LocationType.INTERPOLATED_POINT),
    ("LineString", False, LocationType.STREET_SEGMENT),
    ("MultiLineString", False, LocationType.STREET_SEGMENT),
    ("Polygon", False, LocationType.FOOTPRINT_2D),
    ("MultiPolygon", False, LocationType.FOOTPRINT_2D),
])
def test_tier_follows_the_matched_geometry_class(geometry_type, derived, expected):
    assert LocationType.for_geometry(
        geometry_type, position_derived=derived) is expected


def test_a_point_match_is_the_same_tier_regardless_of_derivation():
    """Tiers key to geometry class, not to a ladder rung. An address point is
    an address point however the search reached it."""
    assert (LocationType.for_geometry("Point", position_derived=True)
            is LocationType.for_geometry("Point", position_derived=False))


def test_unknown_geometry_class_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        LocationType.for_geometry("GeometryCollection")


def test_space_3d_has_no_geometry_class_yet():
    """§7.4 as corrected in Session 4: no volumetric feature class exists in
    STA-006.3, so nothing keys to this tier. It exists so the ordering and the
    ceiling arithmetic are complete when a layer arrives."""
    reachable = {
        LocationType.for_geometry(name, position_derived=derived)
        for name in ("Point", "MultiPoint", "LineString", "MultiLineString",
                     "Polygon", "MultiPolygon")
        for derived in (True, False)
    }
    assert LocationType.SPACE_3D not in reachable


# ---------------------------------------------------------------------------
# The three quality fields (§7.4)
# ---------------------------------------------------------------------------

def test_confidence_is_match_score_scaled_to_the_tier_ceiling():
    quality = MatchQuality(
        match_score=90.0, location_type=LocationType.ADDRESS_POINT)
    assert quality.confidence == pytest.approx(72.0)


def test_confidence_cannot_be_set_independently_of_the_primaries():
    """It is a derived dial, never stored, so it cannot drift out of agreement
    with the two fields it is computed from."""
    with pytest.raises(TypeError):
        MatchQuality(
            match_score=90.0,
            location_type=LocationType.ADDRESS_POINT,
            confidence=100.0,
        )


def test_a_perfect_score_reaches_only_the_tier_ceiling():
    """The ordering §7.4 wants: a shaky point match can rank below a perfect
    street match, and a perfect street match still says 50."""
    perfect_street = MatchQuality(
        match_score=100.0, location_type=LocationType.STREET_SEGMENT)
    shaky_point = MatchQuality(
        match_score=60.0, location_type=LocationType.ADDRESS_POINT)

    assert perfect_street.confidence == pytest.approx(50.0)
    assert shaky_point.confidence == pytest.approx(48.0)
    assert shaky_point.confidence < perfect_street.confidence


@pytest.mark.parametrize("score", [-0.1, 100.1, 1000.0])
def test_match_score_out_of_range_is_rejected(score):
    with pytest.raises(ValueError):
        MatchQuality(match_score=score, location_type=LocationType.ADDRESS_POINT)


def test_field_scores_default_to_empty_for_the_reverse_direction():
    """§10.6: a reverse request has no query address to decompose into street,
    HNO and community, so there is nothing to break down."""
    quality = MatchQuality(
        match_score=80.0, location_type=LocationType.ADDRESS_POINT)
    assert quality.field_scores == {}


# ---------------------------------------------------------------------------
# CivicAddress
# ---------------------------------------------------------------------------

def test_civic_vocabulary_accounts_for_every_ssap_column():
    """Guards the element model against the record layer moving underneath it:
    every provisioned civic column is either an element or explicitly named as
    something else, with a reason."""
    accounted = set(CIVIC_ELEMENTS) | set(NON_CIVIC_SSAP_COLUMNS)
    assert accounted == set(SSAP_COLUMNS)


def test_every_non_civic_column_carries_a_reason():
    for name, reason in NON_CIVIC_SSAP_COLUMNS.items():
        assert reason.strip(), f"{name} excluded with no reason"


def test_civic_elements_all_exist_on_the_dataclass():
    names = set(CivicAddress.__dataclass_fields__)
    assert not set(CIVIC_ELEMENTS) - names


def test_civic_is_read_straight_off_the_record():
    """§11.1 — no derivation, inference or synthesis at rung 1."""
    record = _ssap(
        Add_Number=701, St_Name="16th", St_PosTyp="St", St_PreDir="N",
        A1="ND", A2="Burleigh", A3="Bismarck", Post_Code="58501",
        Placement="Parcel", Elevation=511.6,
    )
    civic = SsapGisRecord.from_record(record).civic()

    assert civic.Add_Number == 701
    assert civic.St_Name == "16th"
    assert civic.A3 == "Bismarck"
    assert not hasattr(civic, "Placement")
    assert not hasattr(civic, "Elevation")


def test_populated_omits_absent_elements():
    """§11.4 — an element with no source is omitted, not emitted empty."""
    civic = CivicAddress(St_Name="State", A1="ND")
    assert civic.populated() == {"St_Name": "State", "A1": "ND"}
    assert CivicAddress().is_empty is True


def test_rcl_side_selects_the_attribute_set():
    """§11.3 — administrative elements as well as street names."""
    record = _rcl(
        St_Name="State", St_PosTyp="St",
        A2_L="Burleigh", A2_R="Morton",
        MSAGComm_L="BISMARCK", MSAGComm_R="MANDAN",
        PostCode_L="58501", PostCode_R="58554",
    )
    gis = RclGisRecord.from_record(record)

    left = gis.civic_for_side(Side.LEFT)
    right = gis.civic_for_side(Side.RIGHT)

    assert (left.A2, left.MSAGComm, left.Post_Code) == (
        "Burleigh", "BISMARCK", "58501")
    assert (right.A2, right.MSAGComm, right.Post_Code) == (
        "Morton", "MANDAN", "58554")
    assert left.St_Name == right.St_Name == "State"


def test_rcl_side_leaves_the_house_number_unset():
    """An RCL asserts a range. Turning a position into a number is §11.2's
    inversion, not a field to copy."""
    gis = RclGisRecord.from_record(
        _rcl(FromAddr_L=100, ToAddr_L=188, Parity_L="E", St_Name="State"))
    assert gis.civic_for_side(Side.LEFT).Add_Number is None


# ---------------------------------------------------------------------------
# Record identity and Candidate
# ---------------------------------------------------------------------------

def test_missing_nguid_makes_a_record_ineligible_for_tie_breaking():
    """R3 — not substituted with the GeoPackage FID, which is not stable across
    reloads and would silently defeat the guarantee §10.4 exists to provide."""
    gis = SsapGisRecord.from_record(
        SSAPRecord(fid=7, NGUID=None, geometry_wkt="POINT (0 0)"))

    assert gis.is_tie_breakable is False
    assert gis.has_flag(DataQualityFlag.NGUID_MISSING)
    assert gis.fid == 7
    assert gis.nguid is None


def test_candidate_exposes_the_quality_fields():
    gis = SsapGisRecord.from_record(
        _ssap(geometry_wkt="POINT (-100.78 46.81)", St_Name="16th"))
    candidate = Candidate(
        record=gis,
        quality=MatchQuality(
            match_score=90.0, location_type=LocationType.ADDRESS_POINT),
        position=gis.position,
    )

    assert candidate.match_score == 90.0
    assert candidate.location_type is LocationType.ADDRESS_POINT
    assert candidate.confidence == pytest.approx(72.0)
    assert candidate.nguid == "{ABC}"
    assert candidate.crs == CRS_2D


def test_a_street_segment_answer_has_no_position_but_still_reports_a_crs():
    """§7.4 geometry-as-answer: rung 3 returns the segment's own line, because
    there is no basis to collapse a street-level match to one position.

    The CRS is CRS_2D, not None (decision 85, resolving Q22). This property
    abstained until decision 85 found that the question dissolves: RoadCenterLine
    is not a declared 3D-capable feature class (§10.5), so the provisioned
    layer's MultiLineString Z is an export artifact and its Z is never consulted
    at any rung. Having no position is not the same as having no CRS."""
    gis = RclGisRecord.from_record(
        _rcl(geometry_wkt="LINESTRING (-101.7 46.8, -101.6 46.9)"))
    candidate = Candidate(
        record=gis,
        quality=MatchQuality(
            match_score=100.0, location_type=LocationType.STREET_SEGMENT),
        answer_geometry=gis.geometry,
    )

    assert candidate.position is None
    assert candidate.crs == CRS_2D
    assert candidate.answer_geometry is gis.geometry


def test_position_dimensionality_drives_the_crs():
    assert Position(longitude=1.0, latitude=2.0).crs == CRS_2D
    assert Position(longitude=1.0, latitude=2.0, altitude=511.6).crs == CRS_3D
    assert not math.isnan(Position(longitude=1.0, latitude=2.0).longitude)
