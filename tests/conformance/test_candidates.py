"""§6 candidate identification (src/geocode/candidates.py).

The scorer is injected throughout. §6.5 settles the shape of the scoring
function and deliberately withholds the formula as proprietary tuning
(Appendix C item (d)), so these tests supply trivial scorers of their own —
constant, or keyed to one field — and exercise what §6 actually specifies:
search order, the candidate set, the floor, ambiguity, and the paths to zero
candidates.
"""

from __future__ import annotations

import datetime
import os

import pytest

from src.engine.models import CivicAddress, LocationType
from src.geocode import candidates
from src.geocode.candidates import AmbiguousResult
from src.gis.records import RCLRecord, SSAPRecord

SEGMENT = "LINESTRING (-100.800 46.810, -100.780 46.810)"


def perfect(query, record):
    """Everything matches, at the ceiling."""
    return 100.0, {}


def by_street(query, record):
    """Exact street name scores 100, anything else 40 — enough to separate a
    match from a non-match without standing in for §6.5."""
    same = (query.St_Name or "").upper() == (record.St_Name or "").upper()
    return (100.0 if same else 40.0), {"St_Name": 100.0 if same else 40.0}


def _ssap(fid=1, **kwargs):
    kwargs.setdefault("NGUID", f"{{SSAP-{fid}}}")
    kwargs.setdefault("geometry_wkt", "POINT (-100.78 46.81)")
    return SSAPRecord(fid=fid, **kwargs)


def _rcl(fid=1, **kwargs):
    kwargs.setdefault("NGUID", f"{{RCL-{fid}}}")
    kwargs.setdefault("geometry_wkt", SEGMENT)
    return RCLRecord(fid=fid, **kwargs)


def _identify(query, ssap=(), rcl=(), score=perfect, min_match_score=60.0):
    return candidates.identify(
        query,
        ssap=list(ssap),
        rcl=list(rcl),
        score=score,
        min_match_score=min_match_score,
        offset_m=10.0,
        endpoint_margin_m=15.0,
    )


# ---------------------------------------------------------------------------
# §3.3 / §6.1 — the ladder
# ---------------------------------------------------------------------------

def test_ssap_is_searched_before_rcl():
    """i3 §4.5's own ordering: site/structure address points or road
    centerlines. A rung-1 match ends the search."""
    found = _identify(
        CivicAddress(Add_Number=101, St_Name="16th"),
        ssap=[_ssap(1, Add_Number=101, St_Name="16th")],
        rcl=[_rcl(2, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
    )

    assert len(found) == 1
    assert found[0].location_type is LocationType.ADDRESS_POINT


def test_rcl_answers_when_no_address_point_matches():
    found = _identify(
        CivicAddress(Add_Number=150, St_Name="16th"),
        ssap=[],
        rcl=[_rcl(2, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
    )

    assert len(found) == 1
    assert found[0].location_type is LocationType.INTERPOLATED_POINT


def test_rungs_are_not_blended():
    """Rung 3 is a different kind of answer, not a worse rung-2. A query the
    segment can carry produces rung 2 only; the whole-segment answer is what
    you get when rung 2 does not exist."""
    found = _identify(
        CivicAddress(Add_Number=150, St_Name="16th"),
        rcl=[
            _rcl(1, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E"),
            _rcl(2, St_Name="16th"),  # no range — rung 3 material
        ],
    )

    assert {c.location_type for c in found} == {LocationType.INTERPOLATED_POINT}


def test_a_coincidental_house_number_match_does_not_shadow_a_perfect_road_match():
    """Decision 70. Decision 69's gate checks identity on one field, so with a
    low floor, every address point in the deployment sharing the query's house
    number survives to rung 1 — none of them on the right street. A road
    segment matching the query exactly, range and parity included, must win on
    confidence rather than being shadowed by rung 1 merely existing."""
    found = _identify(
        CivicAddress(Add_Number=2800, St_Name="Del Rio"),
        ssap=[
            _ssap(1, Add_Number=2800, St_Name="Domino"),
            _ssap(2, Add_Number=2800, St_Name="Bernell"),
        ],
        rcl=[_rcl(3, St_Name="Del Rio", FromAddr_L=2700, ToAddr_L=2898, Parity_L="E")],
        score=by_street,
        min_match_score=10.0,
    )

    assert {c.location_type for c in found} == {LocationType.INTERPOLATED_POINT}
    assert found[0].record.source.St_Name == "Del Rio"


def test_a_genuine_address_point_still_beats_its_own_streets_interpolation():
    """The other side of decision 70: an exact address point (confidence 80)
    outranks a perfect interpolation on the same street (ceiling 75), so
    well-provisioned addresses are unaffected by the comparative ladder."""
    found = _identify(
        CivicAddress(Add_Number=2801, St_Name="Del Rio"),
        ssap=[_ssap(1, Add_Number=2801, St_Name="Del Rio")],
        rcl=[_rcl(2, St_Name="Del Rio", FromAddr_L=2701, ToAddr_L=2899, Parity_L="O")],
        score=by_street,
        min_match_score=10.0,
    )

    assert {c.location_type for c in found} == {LocationType.ADDRESS_POINT}


def test_a_rung_confidence_tie_goes_to_the_more_precise_rung():
    def by_layer(query, record):
        # SSAP 75 * 0.8 = 60.0 confidence; RCL 80 * 0.75 = 60.0 confidence.
        return (75.0 if isinstance(record, SSAPRecord) else 80.0), {}

    found = _identify(
        CivicAddress(Add_Number=150, St_Name="16th"),
        ssap=[_ssap(1, Add_Number=150, St_Name="16th")],
        rcl=[_rcl(2, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
        score=by_layer,
        min_match_score=10.0,
    )

    assert {c.location_type for c in found} == {LocationType.ADDRESS_POINT}


# ---------------------------------------------------------------------------
# §5 / decision 14 — no Gate 1
# ---------------------------------------------------------------------------

def test_a_query_with_no_house_number_is_accepted_at_rung_3():
    """i3 §4.5 imposes no structural precondition on Geocode. A street-level
    query is answered with the segment, not refused."""
    found = _identify(
        CivicAddress(St_Name="16th"),
        rcl=[_rcl(1, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
    )

    assert len(found) == 1
    assert found[0].location_type is LocationType.STREET_SEGMENT
    assert found[0].position is None


def test_an_unassertable_house_number_degrades_to_rung_3():
    """§5's more dangerous case: an HNO is supplied, no segment asserts it, and
    the street still matches. Permitted, and the tier carries the degradation."""
    found = _identify(
        CivicAddress(Add_Number=9999, St_Name="16th"),
        rcl=[_rcl(1, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
    )

    assert found[0].location_type is LocationType.STREET_SEGMENT
    assert found[0].confidence == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# §6.2 candidate set — decision 61, there is no filter
# ---------------------------------------------------------------------------

def test_every_temporally_valid_record_reaches_the_scorer():
    """Decision 61 — the scorer sees the whole layer. Nothing is withheld from
    it on the basis of a civic element, so the set of records scored is exactly
    the set of records provisioned."""
    seen = []

    def recording(query, record):
        seen.append(record.fid)
        return 100.0, {}

    _identify(
        CivicAddress(A1="ND", A2="Burleigh", St_Name="16th"),
        ssap=[
            _ssap(1, A1="ND", A2="Burleigh", St_Name="16th"),
            _ssap(2, A1="ND", A2="Morton", St_Name="16th"),
            _ssap(3, A1="MN", A2="Clay", St_Name="Nowhere"),
        ],
        score=recording,
    )

    assert sorted(seen) == [1, 2, 3]


def test_a_mismatched_county_is_scored_and_can_be_returned():
    """The reversal decision 61 introduces. A record in the wrong county used
    to be excluded before scoring; it is now scored like any other and is
    returned when it scores well enough. What a filter excludes it excludes
    permanently, and a caller's typo or a record's own data defect should
    produce a low score, not a 468."""
    found = _identify(
        CivicAddress(A2="Burleigh", St_Name="16th"),
        ssap=[_ssap(1, A2="Morton", St_Name="16th")],
        score=lambda q, r: (82.0, {}),
        min_match_score=60.0,
    )

    assert [c.record.fid for c in found] == [1]
    assert found[0].match_score == 82.0


def test_a_mismatched_state_or_city_is_scored_the_same_way():
    """No civic element is privileged. A1, A3 and MSAGComm narrow nothing,
    exactly as A2 does not."""
    for element in ("A1", "A3", "MSAGComm", "Post_Code", "Country"):
        found = _identify(
            CivicAddress(St_Name="16th", **{element: "QUERY"}),
            ssap=[_ssap(1, St_Name="16th", **{element: "RECORD"})],
            score=lambda q, r: (75.0, {}),
        )
        assert [c.record.fid for c in found] == [1], element


def test_a_mismatched_administrative_element_costs_score_not_candidacy():
    """The distinction decision 61 rests on: the wrong county is a worse
    candidate, not an absent one. It ranks below the right county rather than
    vanishing, so a caller who misspelled a county still gets an answer."""
    def by_county(query, record):
        same = (query.A2 or "").upper() == (record.A2 or "").upper()
        return (100.0 if same else 65.0), {"A2": 100.0 if same else 65.0}

    found = _identify(
        CivicAddress(A2="Burleigh", St_Name="16th"),
        ssap=[
            _ssap(1, A2="Morton", St_Name="16th",
                  geometry_wkt="POINT (-100.780 46.810)"),
            _ssap(2, A2="Burleigh", St_Name="16th",
                  geometry_wkt="POINT (-100.781 46.810)"),
        ],
        score=by_county,
    )

    assert [c.record.fid for c in found] == [2, 1]


def test_the_street_name_is_left_to_the_scorer():
    """Unchanged by decision 61, and now the rule everywhere rather than the
    exception: an exact comparison on the street would make fuzzy matching
    unreachable — "Mayne St" would never reach §6.5 to be recognised as
    "Main St"."""
    found = _identify(
        CivicAddress(St_Name="Mayne"),
        ssap=[_ssap(1, St_Name="Main")],
        score=lambda q, r: (72.0, {}),
    )

    assert len(found) == 1
    assert found[0].match_score == 72.0


def test_a_sparse_record_is_scored_like_any_other():
    """STA-006.3 permits sparse attribution and §11.4 returns such records
    rather than rejecting them. A null county is not a reason to withhold a
    record from the scorer."""
    found = _identify(
        CivicAddress(A2="Burleigh", St_Name="16th"),
        ssap=[_ssap(1, A2=None, St_Name="16th")],
    )
    assert len(found) == 1


def test_rcl_records_are_not_narrowed_either():
    """Rungs 2 and 3 carry the same rule as rung 1 — decision 61 is about the
    searched layer, whichever layer that is."""
    found = _identify(
        CivicAddress(Add_Number=150, A2="Burleigh", St_Name="16th"),
        rcl=[_rcl(1, A2_L="Morton", A2_R="Morton", St_Name="16th",
                  FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
        score=lambda q, r: (70.0, {}),
    )

    assert len(found) == 1
    assert found[0].location_type is LocationType.INTERPOLATED_POINT


# ---------------------------------------------------------------------------
# §6.2 / §6.5 — decision 69, the SSAP house-number gate (amends 61, 66)
# ---------------------------------------------------------------------------

def test_a_house_number_mismatch_excludes_the_ssap_record_before_scoring():
    """The one named exception to decision 61's no-filter rule. A record whose
    Add_Number differs from the query's — even by one — is never scored, so it
    cannot be returned even if every other field would clear the floor easily."""
    found = _identify(
        CivicAddress(Add_Number=415, St_Name="16th"),
        ssap=[_ssap(1, Add_Number=416, St_Name="16th")],
        score=perfect,  # would score 100 if it ever reached the scorer
    )

    assert found == []


def test_a_house_number_match_is_scored_and_returned_normally():
    """The gate only excludes mismatches; an exact match proceeds through
    scoring exactly as before decision 69."""
    found = _identify(
        CivicAddress(Add_Number=415, St_Name="16th"),
        ssap=[_ssap(1, Add_Number=415, St_Name="16th")],
        score=perfect,
    )

    assert [c.record.fid for c in found] == [1]


def test_a_query_with_no_house_number_gates_nothing():
    """The gate only fires when the query supplies Add_Number. A street-only
    query still reaches every temporally-valid SSAP record, exactly as decision
    61 describes — this is not a reversion to Gate 1 (§5, decision 14)."""
    seen = []

    def recording(query, record):
        seen.append(record.fid)
        return 100.0, {}

    found = _identify(
        CivicAddress(St_Name="16th"),
        ssap=[
            _ssap(1, Add_Number=415, St_Name="16th"),
            _ssap(2, Add_Number=999, St_Name="16th"),
        ],
        score=recording,
    )

    assert sorted(seen) == [1, 2]
    assert sorted(c.record.fid for c in found) == [1, 2]


def test_rcl_candidates_have_no_house_number_gate():
    """Decision 69 is scoped to SSAP. RCL scoring never had an Add_Number term
    and range/parity containment (§7.2) is untouched: a segment whose asserted
    range does not carry the query's number degrades to rung 3 exactly as
    before, rather than being excluded outright the way an SSAP mismatch now
    is."""
    found = _identify(
        CivicAddress(Add_Number=9999, St_Name="16th"),
        rcl=[_rcl(1, St_Name="16th", FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
        score=lambda q, r: (70.0, {}),
    )

    assert len(found) == 1
    assert found[0].location_type is LocationType.STREET_SEGMENT


# ---------------------------------------------------------------------------
# §6 / §6.5 — decision 75, the SSAP unit gate (amends 61, mirrors 69)
# ---------------------------------------------------------------------------

def test_a_unit_mismatch_excludes_the_ssap_record_before_scoring():
    """A record whose UnitValue differs from the query's — both populated —
    is never scored, the same shape as decision 69's house-number gate."""
    found = _identify(
        CivicAddress(Add_Number=107, St_Name="Bowen", UnitValue="219"),
        ssap=[_ssap(1, Add_Number=107, St_Name="Bowen", UnitValue="622")],
        score=perfect,  # would score 100 if it ever reached the scorer
    )

    assert found == []


def test_a_unit_match_is_scored_and_returned_normally():
    found = _identify(
        CivicAddress(Add_Number=107, St_Name="Bowen", UnitValue="219"),
        ssap=[_ssap(1, Add_Number=107, St_Name="Bowen", UnitValue="219")],
        score=perfect,
    )

    assert [c.record.fid for c in found] == [1]


def test_a_query_supplied_unit_does_not_exclude_a_record_with_no_unit_at_all():
    """The one place this gate is NOT a plain mirror of decision 69's: absence
    is not disagreement (decision 61's sparseness posture). Most SSAP records
    have no unit populated and are ordinary single-unit addresses, not
    non-matches for a query that happens to name one — excluding them would
    turn "I don't know" into "no", which the data does not support."""
    found = _identify(
        CivicAddress(Add_Number=107, St_Name="Bowen", UnitValue="219"),
        ssap=[_ssap(1, Add_Number=107, St_Name="Bowen")],  # no UnitValue
        score=perfect,
    )

    assert [c.record.fid for c in found] == [1]


def test_a_query_with_no_unit_gates_nothing():
    """The gate only fires when the query supplies UnitValue. Candidates with
    varying units, or none at all, are all scored exactly as before decision
    75 when the query itself names no unit."""
    seen = []

    def recording(query, record):
        seen.append(record.fid)
        return 100.0, {}

    found = _identify(
        CivicAddress(Add_Number=107, St_Name="Bowen"),
        ssap=[
            _ssap(1, Add_Number=107, St_Name="Bowen", UnitValue="219"),
            _ssap(2, Add_Number=107, St_Name="Bowen", UnitValue="622"),
            _ssap(3, Add_Number=107, St_Name="Bowen"),
        ],
        score=recording,
    )

    assert sorted(seen) == [1, 2, 3]
    assert sorted(c.record.fid for c in found) == [1, 2, 3]


def test_unit_matching_is_trim_and_casefold_normalized():
    """"APT 3" vs "Apt 3" — decision 75 normalizes by trim + casefold before
    comparing, the same as a caller would expect from any other identity
    check in this file."""
    found = _identify(
        CivicAddress(Add_Number=107, St_Name="Bowen", UnitValue="  APT 3  "),
        ssap=[_ssap(1, Add_Number=107, St_Name="Bowen", UnitValue="Apt 3")],
        score=perfect,
    )

    assert [c.record.fid for c in found] == [1]


def test_unit_pretyp_plays_no_part_in_the_gate():
    """Only UnitValue is compared. A record and query that agree on UnitValue
    but differ on UnitPreTyp ("Apt" vs "Unit") still qualify — decision 75 is
    explicit that UnitPreTyp is not part of this gate."""
    found = _identify(
        CivicAddress(Add_Number=107, St_Name="Bowen", UnitPreTyp="Apt", UnitValue="219"),
        ssap=[_ssap(1, Add_Number=107, St_Name="Bowen", UnitPreTyp="Unit", UnitValue="219")],
        score=perfect,
    )

    assert [c.record.fid for c in found] == [1]


def test_the_unit_gate_does_not_enter_the_weighted_average():
    """UnitValue takes no part in matchScore, the same treatment as
    Add_Number under decision 69 — every candidate reaching the scorer
    already matches on unit (or the record has none), so including it in the
    breakdown would only ever contribute a constant, never discriminate."""
    from src.engine import scoring
    from src.gis import field_stats

    field_stats.recompute([], [])
    query = CivicAddress(Add_Number=107, St_Name="Bowen", UnitValue="219")
    record = _ssap(1, Add_Number=107, St_Name="Bowen", UnitValue="219")

    _, breakdown = scoring.score_ssap(query, record)

    assert "UnitValue" not in breakdown
    assert "Unit" not in breakdown


# ---------------------------------------------------------------------------
# The floor and §6.4's zero-candidate paths
# ---------------------------------------------------------------------------

def test_candidates_below_the_floor_are_excluded():
    """GCS_MIN_MATCH_SCORE excludes sub-threshold candidates entirely — a
    candidate below the floor is a non-match, not a fuzzy match (§7.4)."""
    found = _identify(
        CivicAddress(St_Name="16th"),
        ssap=[_ssap(1, St_Name="Nowhere")],
        score=by_street,
        min_match_score=60.0,
    )
    assert found == []


def test_the_floor_applies_after_scoring_not_before():
    """The second carve-out decision 61 leaves standing. GCS_MIN_MATCH_SCORE
    discards nothing unseen: every record is scored first, and the floor then
    acts on the score. The record below is dropped by the floor, not withheld
    from the scorer."""
    seen = []

    def recording(query, record):
        seen.append(record.fid)
        return 20.0, {}

    found = _identify(
        CivicAddress(A2="Burleigh", St_Name="16th"),
        ssap=[_ssap(1, A2="Morton", St_Name="Nowhere")],
        score=recording,
        min_match_score=60.0,
    )

    assert seen == [1]          # scored despite matching nothing
    assert found == []          # and discarded on its score alone


@pytest.mark.parametrize("ssap,rcl,score", [
    ([], [], perfect),                                    # nothing provisioned
    ([_ssap(1, St_Name="Nowhere")], [], by_street),       # below the floor
    ([_ssap(1, geometry_wkt=None)], [], perfect),         # unlocatable
])
def test_every_path_to_zero_candidates_is_indistinguishable(ssap, rcl, score):
    """§6.4 — all of them map to 468, and none is distinguished, because the
    interface has no field to carry the difference."""
    assert _identify(CivicAddress(A2="Burleigh", St_Name="16th"),
                     ssap=ssap, rcl=rcl, score=score) == []


def test_an_unlocatable_record_is_not_returned_as_a_match():
    """Decision 55 — no usable geometry means no position, and the attribute
    columns are not read to repair it."""
    found = _identify(
        CivicAddress(St_Name="16th"),
        ssap=[_ssap(1, St_Name="16th", geometry_wkt=None,
                    Longitude=-100.78, Latitude=46.81)],
    )
    assert found == []


# ---------------------------------------------------------------------------
# §3.4 temporal filtering
# ---------------------------------------------------------------------------

def test_records_without_dates_are_always_active():
    """The norm in the provisioned data, where Effective and Expire are null
    throughout."""
    assert candidates.is_active(_ssap(1), datetime.datetime.now(datetime.timezone.utc))


def test_an_expired_record_is_not_active():
    at = datetime.datetime(2026, 7, 31, tzinfo=datetime.timezone.utc)
    assert not candidates.is_active(_ssap(1, Expire="2020-01-01T00:00:00+00:00"), at)
    assert not candidates.is_active(_ssap(1, Effective="2030-01-01T00:00:00+00:00"), at)


def test_an_unparseable_date_does_not_remove_an_address_from_service():
    at = datetime.datetime(2026, 7, 31, tzinfo=datetime.timezone.utc)
    assert candidates.is_active(_ssap(1, Expire="not a date"), at)


def test_a_temporally_invalid_record_is_excluded_before_scoring():
    """The first carve-out decision 61 leaves standing. §3.4 is a correctness
    test, not a narrowing one: a record outside its Effective/Expire window is
    wrong rather than merely unlikely, so it is excluded before scoring and a
    perfect scorer cannot rescue it."""
    seen = []

    def recording(query, record):
        seen.append(record.fid)
        return 100.0, {}

    found = candidates.identify(
        CivicAddress(St_Name="16th"),
        ssap=[
            _ssap(1, St_Name="16th", Expire="2020-01-01T00:00:00+00:00"),
            _ssap(2, St_Name="16th"),
        ],
        rcl=[],
        score=recording,
        min_match_score=60.0,
        offset_m=10.0,
        endpoint_margin_m=15.0,
        at=datetime.datetime(2026, 7, 31, tzinfo=datetime.timezone.utc),
    )

    assert seen == [2]                          # the expired record never scored
    assert [c.record.fid for c in found] == [2]


# ---------------------------------------------------------------------------
# §6.3 ambiguity
# ---------------------------------------------------------------------------

def _two_points(lon_a, lat_a, lon_b, lat_b, **kw):
    return _identify(
        CivicAddress(St_Name="16th"),
        ssap=[
            _ssap(1, St_Name="16th", geometry_wkt=f"POINT ({lon_a} {lat_a})"),
            _ssap(2, St_Name="16th", geometry_wkt=f"POINT ({lon_b} {lat_b})"),
        ],
        **kw,
    )


def test_close_candidates_merge_to_their_average():
    """The case the merge logic exists for: a generic query resolving to
    distinct structures on one parcel — a farmhouse and a machine shed."""
    found = _two_points(-100.7800, 46.8100, -100.7802, 46.8100)
    merged = candidates.resolve_ambiguity(found, tolerance_m=150.0)

    assert merged.is_merge is True
    assert merged.position.longitude == pytest.approx(-100.7801)
    assert 0 < merged.horizontal_uncertainty_m < 150


def test_candidates_beyond_tolerance_raise():
    """Two "State Street" matches forty miles apart are not a location.
    Merging them yields a position in a field with a 32 km uncertainty."""
    found = _two_points(-100.78, 46.81, -101.50, 46.81)

    with pytest.raises(AmbiguousResult) as caught:
        candidates.resolve_ambiguity(found, tolerance_m=150.0)
    assert caught.value.spread_m > 150.0
    assert caught.value.count == 2


def test_the_tolerance_is_the_only_thing_separating_the_two_outcomes():
    """Decision 54: the value is deployment-specific with no specification
    default, and it is what decides between an answer and a 468."""
    found = _two_points(-100.7800, 46.8100, -100.7820, 46.8100)

    assert candidates.resolve_ambiguity(found, tolerance_m=500.0).is_merge
    with pytest.raises(AmbiguousResult):
        candidates.resolve_ambiguity(found, tolerance_m=10.0)


def test_vertical_disagreement_merges_unconditionally():
    """§6.3's original rule, unchanged by the Session 2 rework: candidates that
    agree horizontally and differ vertically merge however far apart they are,
    and the uncertainty spans the extent. The extent is the answer."""
    found = _identify(
        CivicAddress(St_Name="16th"),
        ssap=[
            _ssap(1, St_Name="16th", geometry_wkt="POINT Z (-100.78 46.81 500)"),
            _ssap(2, St_Name="16th", geometry_wkt="POINT Z (-100.78 46.81 560)"),
        ],
    )
    merged = candidates.resolve_ambiguity(found, tolerance_m=1.0)

    assert merged.vertical_extent_m == pytest.approx(60.0)
    # §3.7.3 — the midpoint bounds the worst case at half the extent, where
    # naming the lowest would put a responder the full 60 m out.
    assert merged.position.altitude == pytest.approx(530.0)


def test_a_single_candidate_is_not_a_merge():
    found = _identify(
        CivicAddress(St_Name="16th"), ssap=[_ssap(1, St_Name="16th")])
    merged = candidates.resolve_ambiguity(found, tolerance_m=150.0)

    assert merged.is_merge is False
    assert merged.horizontal_uncertainty_m == pytest.approx(0.0)


def test_a_lone_candidate_never_triggers_ambiguity():
    """However tight the tolerance. One candidate cannot disagree with itself,
    and a tolerance of zero must not turn every single match into a 468."""
    found = _identify(
        CivicAddress(St_Name="16th"), ssap=[_ssap(1, St_Name="16th")])
    assert candidates.resolve_ambiguity(found, tolerance_m=0.0).is_merge is False


# ---------------------------------------------------------------------------
# §7.4 ranking
# ---------------------------------------------------------------------------

def test_ranking_is_by_blended_confidence():
    found = _identify(
        CivicAddress(St_Name="16th"),
        ssap=[
            _ssap(1, St_Name="16th", geometry_wkt="POINT (-100.780 46.810)"),
            _ssap(2, St_Name="16th", geometry_wkt="POINT (-100.781 46.810)"),
        ],
        score=lambda q, r: ((90.0 if r.fid == 2 else 70.0), {}),
    )

    assert [c.record.fid for c in found] == [2, 1]
    assert found[0].confidence > found[1].confidence


def test_ranking_is_deterministic_across_calls():
    """Repeated identical queries must agree with each other, or §14.1's round
    trip is unstable for reasons that have nothing to do with the data."""
    def run():
        return [c.record.fid for c in _identify(
            CivicAddress(St_Name="16th"),
            ssap=[_ssap(i, St_Name="16th") for i in (3, 1, 2)],
        )]

    assert run() == run()


# ---------------------------------------------------------------------------
# Decision 99 — filing DataQualityFlag conditions against the SI
# ---------------------------------------------------------------------------
# ssap_candidates()/rcl_candidates() are where a GisRecord's flags are turned
# into a filed report — never GisRecord.from_record() itself, which only
# records what it observed (see tests/conformance/test_models.py's
# test_detection_does_not_file_a_discrepancy_report). fire_gis_dr is patched
# out here rather than exercised for real: what these tests own is that the
# right problem token fires for the right condition, not
# src/discrepancy/discrepancy_report.py's own submission behaviour, which
# tests/conformance/test_discrepancy_report.py covers directly.

def _patched_fire(monkeypatch):
    calls = []
    monkeypatch.setattr(candidates, "fire_gis_dr",
                         lambda *a, **kw: calls.append((a, kw)))
    return calls


def test_ngid_missing_ssap_record_files_an_omitted_field_report(monkeypatch):
    """R3 — a null NGUID is filed as OmittedField against the SI's SSAP
    layer, not silently substituted with a local surrogate."""
    calls = _patched_fire(monkeypatch)

    candidates.ssap_candidates(
        CivicAddress(Add_Number=101, St_Name="16th"),
        [_ssap(1, Add_Number=101, St_Name="16th", NGUID=None)],
        score=perfect, min_match_score=60.0,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (candidates.GISProblem.OmittedField, candidates.ProblemSeverity.Minor)
    assert kwargs["detail"] == "NGUID"
    assert kwargs["layer_ids"] == os.environ.get(
        "GCS_SSAP_LAYER", "SiteStructureAddressPoint")


def test_no_geometry_ssap_record_files_a_bad_geometry_report(monkeypatch):
    """Decision 55 — a shapeless SSAP record is filed as BadGeometry, on top
    of being dropped as an unlocatable candidate."""
    calls = _patched_fire(monkeypatch)

    candidates.ssap_candidates(
        CivicAddress(Add_Number=101, St_Name="16th"),
        [_ssap(1, Add_Number=101, St_Name="16th", geometry_wkt=None)],
        score=perfect, min_match_score=60.0,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (candidates.GISProblem.BadGeometry, candidates.ProblemSeverity.Moderate)
    assert kwargs["detail"] == "no usable geometry"


def test_a_clean_ssap_record_files_no_discrepancy_report(monkeypatch):
    """Negative control — a record with no data quality issue files nothing."""
    calls = _patched_fire(monkeypatch)

    candidates.ssap_candidates(
        CivicAddress(Add_Number=101, St_Name="16th"),
        [_ssap(1, Add_Number=101, St_Name="16th")],
        score=perfect, min_match_score=60.0,
    )

    assert calls == []


def test_ngid_missing_rcl_record_files_an_omitted_field_report(monkeypatch):
    calls = _patched_fire(monkeypatch)

    candidates.rcl_candidates(
        CivicAddress(St_Name="16th"),
        [_rcl(1, St_Name="16th", NGUID=None)],
        score=perfect, min_match_score=60.0, offset_m=10.0, endpoint_margin_m=15.0,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (candidates.GISProblem.OmittedField, candidates.ProblemSeverity.Minor)
    assert kwargs["detail"] == "NGUID"
    assert kwargs["layer_ids"] == os.environ.get("GCS_RCL_LAYER", "RoadCenterLine")


def test_multipart_rcl_record_files_a_bad_geometry_report(monkeypatch):
    """Decision 53 — a multi-part centerline segment is filed as BadGeometry:
    §7.2's walk, §7.3's left/right sense, and §11.2's inversion all assume one
    continuous path."""
    calls = _patched_fire(monkeypatch)

    candidates.rcl_candidates(
        CivicAddress(St_Name="16th"),
        [_rcl(1, St_Name="16th", geometry_wkt=(
            "MULTILINESTRING ((-100.80 46.81, -100.79 46.81),"
            " (-100.78 46.81, -100.77 46.81))"))],
        score=perfect, min_match_score=60.0, offset_m=10.0, endpoint_margin_m=15.0,
    )

    problems = [args[0] for args, kwargs in calls]
    assert candidates.GISProblem.BadGeometry in problems
    details = [kwargs["detail"] for args, kwargs in calls
               if args[0] is candidates.GISProblem.BadGeometry]
    assert any("multi-part" in d for d in details)
