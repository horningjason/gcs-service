"""§11 civic derivation and §12 response assembly (src/reverse/).

The §14.1 round trip is the load-bearing test in this file. §11.2 says that if
the forward and reverse directions traverse different paths, round-trip
consistency "breaks by construction rather than by data quality" — a defect
that would look like bad GIS data forever. The tests at the bottom assert the
two directions actually meet.
"""

from __future__ import annotations

import pytest

from src.engine.models import CivicAddress, LocationType, RclGisRecord, Side
from src.geocode import candidates as forward_candidates
from src.geocode import position as forward_position
from src.reverse import civic_derivation, response_assembly, search
from src.reverse import origin as shapes
from src.gis.records import RCLRecord, SSAPRecord

SEGMENT = "LINESTRING (-100.800 46.810, -100.780 46.810)"
MARGIN = 15.0
OFFSET = 10.0


def flat(origin, hit):
    return 75.0, {}


def _rcl_record(fid=1, **kwargs):
    kwargs.setdefault("NGUID", f"{{R-{fid}}}")
    kwargs.setdefault("geometry_wkt", SEGMENT)
    return RCLRecord(fid=fid, **kwargs)


def _rcl(fid=1, **kwargs):
    return RclGisRecord.from_record(_rcl_record(fid, **kwargs))


def _ssap_record(fid=1, lon=-100.79, lat=46.81, **kwargs):
    kwargs.setdefault("NGUID", f"{{S-{fid}}}")
    kwargs.setdefault("geometry_wkt", f"POINT ({lon} {lat})")
    return SSAPRecord(fid=fid, **kwargs)


def _derive_at(record, lon, lat, margin=MARGIN):
    hits = search.rcl_hits(shapes.Point(lon, lat).origin(), [record.source], radius_m=500.0)
    return civic_derivation.derive(hits[0], endpoint_margin_m=margin)


# ---------------------------------------------------------------------------
# §11.1 — SSAP is read, not computed
# ---------------------------------------------------------------------------

def test_ssap_civic_is_read_straight_off_the_record():
    """No derivation, inference or synthesis at this rung."""
    hits = search.ssap_hits(
        shapes.Point(-100.79, 46.81).origin(),
        [_ssap_record(1, Add_Number=701, St_Name="16th", St_PosTyp="St",
                      A1="ND", A2="Burleigh", A3="Bismarck", Post_Code="58501")],
        radius_m=250.0,
    )
    derived = civic_derivation.derive(hits[0], endpoint_margin_m=MARGIN)

    assert derived.civic.Add_Number == 701
    assert derived.civic.St_Name == "16th"
    assert derived.civic.A3 == "Bismarck"
    assert derived.house_number_synthesised is False
    assert derived.tier is LocationType.ADDRESS_POINT


def test_administrative_elements_come_from_the_record_not_a_polygon():
    """§11.3, decision 45 — the boundary layers are not consulted. A forward
    geocode matched the query against the record's own fields, so reversing
    must hand those same fields back."""
    hits = search.ssap_hits(
        shapes.Point(-100.79, 46.81).origin(),
        [_ssap_record(1, A2="Burleigh", A3="Bismarck", St_Name="16th")],
        radius_m=250.0,
    )
    derived = civic_derivation.derive(hits[0], endpoint_margin_m=MARGIN)

    assert (derived.civic.A2, derived.civic.A3) == ("Burleigh", "Bismarck")


def test_a_sparse_record_is_returned_not_skipped():
    """§11.4, decision 46 — the alternative would have the GCS invent a
    completeness standard i3 never gave it."""
    hits = search.ssap_hits(
        shapes.Point(-100.79, 46.81).origin(),
        [_ssap_record(1, St_Name="16th")],  # no municipality, no number
        radius_m=250.0,
    )
    derived = civic_derivation.derive(hits[0], endpoint_margin_m=MARGIN)

    assert derived.civic.St_Name == "16th"
    assert derived.civic.A3 is None


def test_an_element_with_no_source_is_omitted_not_emitted_empty():
    """§11.4 — RFC 5139 gives an empty element no defined meaning, so emitting
    one asserts nothing while inviting a consumer to read it as an assertion."""
    hits = search.ssap_hits(
        shapes.Point(-100.79, 46.81).origin(),
        [_ssap_record(1, St_Name="16th")], radius_m=250.0)
    derived = civic_derivation.derive(hits[0], endpoint_margin_m=MARGIN)

    assert "A3" not in derived.civic.populated()
    assert "" not in derived.civic.populated().values()


# ---------------------------------------------------------------------------
# §11.2 — the house number is synthesised
# ---------------------------------------------------------------------------

def test_the_house_number_is_synthesised_from_the_projection():
    """Mid-segment on a 100-200 even range gives 150."""
    derived = _derive_at(_rcl(1, FromAddr_L=100, ToAddr_L=200, Parity_L="E"),
                         -100.790, 46.8105)

    assert derived.civic.Add_Number == 150
    assert derived.house_number_synthesised is True
    assert derived.tier is LocationType.INTERPOLATED_POINT


def test_the_synthesised_number_is_forced_to_the_sides_parity():
    """§11.2 — a projection at 47.3% of a 100-200 range yields 147.3, which
    must be rounded to the parity of the side: 147 or 149, never 148."""
    even = _derive_at(_rcl(1, FromAddr_L=100, ToAddr_L=200, Parity_L="E"),
                      -100.7906, 46.8105)
    assert even.civic.Add_Number % 2 == 0

    odd = _derive_at(_rcl(2, FromAddr_R=101, ToAddr_R=201, Parity_R="O"),
                     -100.7906, 46.8095)
    assert odd.civic.Add_Number % 2 == 1


@pytest.mark.parametrize("lon", [-100.8020, -100.7780])
def test_the_synthesised_number_is_clamped_to_the_asserted_range(lon):
    """The guardrail: it can never fall outside what the data claims, however
    far past the segment the origin projected."""
    derived = _derive_at(_rcl(1, FromAddr_L=100, ToAddr_L=200, Parity_L="E"),
                         lon, 46.8105)

    assert 100 <= derived.civic.Add_Number <= 200


def test_clamping_survives_the_parity_forcing():
    """Parity is applied first and the clamp second, because forcing parity can
    push a value one step past an endpoint and the clamp must hold."""
    derived = _derive_at(_rcl(1, FromAddr_L=100, ToAddr_L=101, Parity_L="O"),
                         -100.8020, 46.8105)

    assert 100 <= derived.civic.Add_Number <= 101


def test_the_side_of_projection_selects_the_attribute_set():
    """§11.3 — administrative elements as well as street names."""
    record = _rcl(
        1,
        FromAddr_L=100, ToAddr_L=200, Parity_L="E",
        FromAddr_R=101, ToAddr_R=201, Parity_R="O",
        A2_L="Burleigh", A2_R="Morton",
        MSAGComm_L="BISMARCK", MSAGComm_R="MANDAN",
        St_Name="State",
    )
    north = _derive_at(record, -100.790, 46.8105)   # left of a west-to-east line
    south = _derive_at(record, -100.790, 46.8095)

    assert north.side is Side.LEFT
    assert (north.civic.A2, north.civic.MSAGComm) == ("Burleigh", "BISMARCK")
    assert south.side is Side.RIGHT
    assert (south.civic.A2, south.civic.MSAGComm) == ("Morton", "MANDAN")


def test_a_side_asserting_no_range_yields_a_street_level_address():
    """The reverse-side analogue of rung 3 — tiered STREET_SEGMENT so the
    confidence ceiling says so, rather than the address quietly omitting a
    number it might have had."""
    derived = _derive_at(_rcl(1, St_Name="State"), -100.790, 46.8105)

    assert derived.civic.Add_Number is None
    assert derived.civic.St_Name == "State"
    assert derived.tier is LocationType.STREET_SEGMENT
    assert derived.house_number_synthesised is False


def test_a_zero_length_range_reverses_to_its_single_number():
    """§7.2's noted asymmetry: the direction that breaks forward is the
    trustworthy one in reverse. Any fraction maps back to the one asserted
    number — no rounding, no parity forcing, no synthesis."""
    record = _rcl(1, FromAddr_L=101, ToAddr_L=101, Parity_L="O")

    for lon in (-100.7950, -100.7900, -100.7850):
        assert _derive_at(record, lon, 46.8105).civic.Add_Number == 101


# ---------------------------------------------------------------------------
# §12 — response assembly
# ---------------------------------------------------------------------------

def _hits_at(lon, lat, ssap=(), rcl=(), radius=250.0, shape=None):
    origin = (shape or shapes.Point(lon, lat)).origin()
    return origin, search.search(origin, ssap=list(ssap), rcl=list(rcl), radius_m=radius)


def test_the_strict_interface_returns_one_address():
    origin, hits = _hits_at(
        -100.79, 46.81, ssap=[_ssap_record(1, Add_Number=701, St_Name="16th")])
    answer = response_assembly.strict_answer(
        origin, hits, score=flat, endpoint_margin_m=MARGIN)

    assert answer.civic.Add_Number == 701


def test_nothing_within_the_radius_is_the_468_path():
    origin, hits = _hits_at(-100.79, 46.81, ssap=[], rcl=[])
    assert response_assembly.strict_answer(
        origin, hits, score=flat, endpoint_margin_m=MARGIN) is None


def test_the_enhanced_interface_returns_the_ordered_list():
    origin, hits = _hits_at(
        -100.7900, 46.8102,
        ssap=[_ssap_record(1, lon=-100.7900, lat=46.8105, St_Name="16th"),
              _ssap_record(2, lon=-100.7900, lat=46.8120, St_Name="16th")],
    )
    listed = response_assembly.answers(
        origin, hits, score=flat, endpoint_margin_m=MARGIN)

    assert len(listed) == 2
    assert listed[0].distance_m < listed[1].distance_m


def test_the_enhanced_answer_carries_what_the_strict_one_discards():
    """§12.1's deficiency is deliberate: rank, score, distance, containment,
    Placement Method and the interpolated-number flag all exist here and none
    of them reaches the i3 interface."""
    origin, hits = _hits_at(
        -100.7900, 46.8102,
        ssap=[_ssap_record(1, lon=-100.7900, lat=46.8105, St_Name="16th",
                           Placement="Parcel")],
        shape=shapes.Circle(-100.7900, 46.8102, 250.0),
    )
    listed = response_assembly.answers(
        origin, hits, score=flat, endpoint_margin_m=MARGIN)

    assert listed[0].distance_m > 0
    assert listed[0].contained is True
    assert listed[0].placement == "Parcel"
    assert listed[0].confidence == pytest.approx(60.0)


def test_the_interpolated_flag_marks_a_computed_number():
    origin, hits = _hits_at(
        -100.790, 46.8105,
        rcl=[_rcl_record(1, FromAddr_L=100, ToAddr_L=200, Parity_L="E")])
    listed = response_assembly.answers(
        origin, hits, score=flat, endpoint_margin_m=MARGIN)

    assert listed[0].house_number_synthesised is True
    assert listed[0].location_type is LocationType.INTERPOLATED_POINT


@pytest.mark.parametrize("tier,token", [
    (LocationType.ADDRESS_POINT, "Address"),
    (LocationType.INTERPOLATED_POINT, "RoadCenterline"),
    (LocationType.STREET_SEGMENT, "RoadCenterline"),
])
def test_the_i3_match_type_token_is_coarser_than_location_type(tier, token):
    """§12.2 — RoadCenterline covers both a street-level match and an
    interpolated house number without distinguishing them, which is why both
    fields travel."""
    from src.engine.models import MatchQuality

    answer = response_assembly.ReverseAnswer(
        civic=CivicAddress(St_Name="16th"),
        quality=MatchQuality(match_score=80.0, location_type=tier),
        distance_m=5.0,
    )
    assert answer.match_type == token


# ---------------------------------------------------------------------------
# §14.1 — the round trip
# ---------------------------------------------------------------------------

def test_an_ssap_address_round_trips_exactly():
    """§14.1 at rung 1. Geocode the address forward, reverse the coordinate it
    produced, and the original address comes back — because §11.1 reads the
    same record's fields the forward match scored against, and §11.3 declines
    to consult a different source for the administrative elements.
    """
    record = _ssap_record(
        1, lon=-100.7900, lat=46.8100,
        Add_Number=701, St_Name="16th", St_PosTyp="St", St_PreDir="N",
        A1="ND", A2="Burleigh", A3="Bismarck", Post_Code="58501",
    )
    query = CivicAddress(Add_Number=701, St_Name="16th", A3="Bismarck")

    forward = forward_candidates.identify(
        query, ssap=[record], rcl=[],
        score=lambda q, r: (100.0, {}), min_match_score=60.0,
        offset_m=OFFSET, endpoint_margin_m=MARGIN,
    )
    assert len(forward) == 1
    derived_position = forward[0].position

    origin, hits = _hits_at(
        derived_position.longitude, derived_position.latitude, ssap=[record])
    back = response_assembly.strict_answer(
        origin, hits, score=flat, endpoint_margin_m=MARGIN)

    assert back.civic.Add_Number == 701
    assert back.civic.St_Name == "16th"
    assert back.civic.St_PreDir == "N"
    assert back.civic.A1 == "ND"
    assert back.civic.A2 == "Burleigh"
    assert back.civic.A3 == "Bismarck"
    assert back.civic.Post_Code == "58501"


def test_the_round_trip_returns_every_field_the_record_held():
    """Not merely the queried elements — §11.1 reports the whole record, so the
    reversed address is at least as complete as the one that geocoded."""
    record = _ssap_record(
        1, Add_Number=701, St_Name="16th", A2="Burleigh", Unit="2B", Floor="2")

    forward = forward_candidates.identify(
        CivicAddress(Add_Number=701, St_Name="16th"), ssap=[record], rcl=[],
        score=lambda q, r: (100.0, {}), min_match_score=60.0,
        offset_m=OFFSET, endpoint_margin_m=MARGIN)

    origin, hits = _hits_at(
        forward[0].position.longitude, forward[0].position.latitude, ssap=[record])
    back = response_assembly.strict_answer(
        origin, hits, score=flat, endpoint_margin_m=MARGIN)

    assert back.civic.populated() == CivicAddress(
        Add_Number=701, St_Name="16th", A2="Burleigh", Unit="2B", Floor="2"
    ).populated()


def test_both_directions_walk_the_same_margin_shortened_path():
    """§11.2's guardrail, tested directly rather than inferred from a round
    trip. The forward walk places a number at an along-track distance; the
    reverse walk must read the same distance back to the same number.
    """
    record = _rcl(1, FromAddr_L=100, ToAddr_L=200, Parity_L="E")

    for house_number in (100, 120, 150, 180, 200):
        placed = forward_position.interpolate(
            record, house_number, offset_m=OFFSET, endpoint_margin_m=MARGIN)

        # Reverse from the point the forward direction produced. The setback
        # has moved it off the centerline; projection puts it back on.
        back = _derive_at(
            record, placed.position.longitude, placed.position.latitude)

        assert back.civic.Add_Number == house_number


def test_a_short_segment_round_trips_through_the_midpoint_rule():
    """Decisions 48 and 56 make the forward direction return the midpoint. The
    inverse must return the asserted number rather than reading a fraction off
    a frame that never applied."""
    record = _rcl(1, geometry_wkt="LINESTRING (-100.7900 46.8100, -100.79975 46.8100)",
                  FromAddr_L=100, ToAddr_L=200, Parity_L="E")
    placed = forward_position.interpolate(
        record, 150, offset_m=OFFSET, endpoint_margin_m=400.0)

    assert placed.margin_applied is False
    back = _derive_at(record, placed.position.longitude, placed.position.latitude,
                      margin=400.0)
    assert back.civic.Add_Number == 100  # the range's low, the frame being inert
