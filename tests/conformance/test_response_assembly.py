"""§8 forward response assembly (src/geocode/response_assembly.py).

Two things are being pinned here. First, geometry-as-answer: the shape returned
is the matched feature's own, and rung 3 returns a line rather than a point
dressed up with a synthesised uncertainty. Second, the split between the
interfaces — what §8.1 discards is deliberate, and a test that did not check
the discard would let someone "fix" it.
"""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point

from src.engine.models import (
    CRS_2D,
    CRS_3D,
    Candidate,
    CivicAddress,
    LocationType,
    MatchQuality,
    Position,
    RclGisRecord,
    SsapGisRecord,
)
from src.geocode import candidates, response_assembly
from src.geocode.candidates import AmbiguousResult
from src.gis.records import RCLRecord, SSAPRecord

SEGMENT = "LINESTRING (-100.800 46.810, -100.780 46.810)"


def _point_candidate(lon, lat, alt=None, score=90.0, fid=1,
                     tier=LocationType.ADDRESS_POINT):
    wkt = f"POINT Z ({lon} {lat} {alt})" if alt else f"POINT ({lon} {lat})"
    gis = SsapGisRecord.from_record(
        SSAPRecord(fid=fid, NGUID=f"{{P-{fid}}}", geometry_wkt=wkt))
    return Candidate(
        record=gis,
        quality=MatchQuality(match_score=score, location_type=tier),
        position=gis.position,
        answer_geometry=gis.geometry,
    )


def _segment_candidate(score=100.0, fid=9, wkt=SEGMENT, **rcl_kwargs):
    gis = RclGisRecord.from_record(
        RCLRecord(fid=fid, NGUID=f"{{L-{fid}}}", geometry_wkt=wkt, **rcl_kwargs))
    return Candidate(
        record=gis,
        quality=MatchQuality(
            match_score=score, location_type=LocationType.STREET_SEGMENT),
        position=None,
        answer_geometry=gis.geometry,
    )


# ---------------------------------------------------------------------------
# §7.4 geometry-as-answer
# ---------------------------------------------------------------------------

def test_a_point_rung_returns_a_point():
    answer = response_assembly.strict_answer(
        [_point_candidate(-100.78, 46.81)], tolerance_m=150.0)

    assert isinstance(answer.geometry, Point)
    assert answer.geometry.x == pytest.approx(-100.78)
    assert answer.is_line_answer is False


def test_rung_3_returns_the_segments_actual_line():
    """Decision 30 — no basis to collapse a street-level match to one position,
    and the line is itself the honest uncertainty signal."""
    answer = response_assembly.strict_answer(
        [_segment_candidate()], tolerance_m=150.0)

    assert isinstance(answer.geometry, LineString)
    assert answer.position is None
    assert answer.is_line_answer is True


def test_no_synthesised_uncertainty_shape_is_invented():
    """§7.4 declines to synthesise a Circle or Ellipse around a matched
    geometry. A single match carries no uncertainty radius at all."""
    answer = response_assembly.strict_answer(
        [_point_candidate(-100.78, 46.81)], tolerance_m=150.0)

    assert answer.horizontal_uncertainty_m is None
    assert answer.vertical_extent_m is None
    assert answer.merged_count == 1


def test_a_2d_position_produces_a_2d_point():
    """The shape agrees with the CRS rather than carrying a zero the CRS then
    contradicts."""
    answer = response_assembly.strict_answer(
        [_point_candidate(-100.78, 46.81)], tolerance_m=150.0)

    assert answer.geometry.has_z is False
    assert answer.crs == CRS_2D


def test_a_3d_position_produces_a_3d_point():
    answer = response_assembly.strict_answer(
        [_point_candidate(-100.78, 46.81, alt=512.4)], tolerance_m=150.0)

    assert answer.geometry.has_z is True
    assert answer.geometry.z == pytest.approx(512.4)
    assert answer.crs == CRS_3D


def test_a_line_answer_reports_2d_rather_than_abstaining():
    """Decision 85 (resolves Q22) — this answer used to report None, declining
    to choose between 4326 and 4979 for a line. It now reports CRS_2D: the
    RoadCenterLine layer's per-vertex Z is a GeoPackage export artifact rather
    than declared attribution (§10.5), so it is never consulted and a rung-3
    answer is 2D on the same basis rung 2 already is. Still inherited from
    Candidate.crs, not re-decided here."""
    answer = response_assembly.strict_answer(
        [_segment_candidate()], tolerance_m=150.0)

    assert answer.crs == CRS_2D


# ---------------------------------------------------------------------------
# §8.1 — the strict interface and what it discards
# ---------------------------------------------------------------------------

def test_the_strict_interface_returns_rank_1():
    best = _point_candidate(-100.780, 46.810, score=95.0, fid=1)
    other = _point_candidate(-100.7801, 46.810, score=70.0, fid=2)

    answer = response_assembly.strict_answer([best, other], tolerance_m=150.0)
    assert answer.quality.match_score == 95.0


def test_a_fuzzy_match_is_indistinguishable_from_an_exact_one():
    """§8.1's deficiency, carried faithfully. The answer object exposes the
    geometry and nothing that would let a consumer of the strict interface tell
    a 100 from a 62 — that lives on the quality field the wire layer drops.
    """
    exact = response_assembly.strict_answer(
        [_point_candidate(-100.78, 46.81, score=100.0)], tolerance_m=150.0)
    fuzzy = response_assembly.strict_answer(
        [_point_candidate(-100.78, 46.81, score=62.0)], tolerance_m=150.0)

    assert exact.geometry.equals(fuzzy.geometry)
    assert exact.crs == fuzzy.crs


def test_no_candidates_produces_no_answer():
    """§6.4 — the 468 path, by whichever route it was reached."""
    assert response_assembly.strict_answer([], tolerance_m=150.0) is None


def test_ambiguity_beyond_tolerance_propagates():
    """§6.3 into §8.4's 468. Assembly does not swallow it and return the first
    candidate, which would answer a question the service cannot answer."""
    with pytest.raises(AmbiguousResult):
        response_assembly.strict_answer(
            [_point_candidate(-100.78, 46.81, fid=1),
             _point_candidate(-101.50, 46.81, fid=2)],
            tolerance_m=150.0,
        )


# ---------------------------------------------------------------------------
# §6.3 merge on the strict interface (decision 27)
# ---------------------------------------------------------------------------

def test_the_strict_interface_averages_a_merge():
    """pidfLoGeo carries one geodetic location, so picking one structure
    arbitrarily would assert more than the data supports."""
    answer = response_assembly.strict_answer(
        [_point_candidate(-100.7800, 46.8100, fid=1),
         _point_candidate(-100.7802, 46.8100, fid=2)],
        tolerance_m=150.0,
    )

    assert answer.merged_count == 2
    assert answer.geometry.x == pytest.approx(-100.7801)
    assert answer.horizontal_uncertainty_m > 0


def test_the_merged_uncertainty_is_sized_to_the_extent():
    """§3.7.3 — the uncertainty spans the candidates, so a consumer that reads
    it knows how much ground the answer covers."""
    answer = response_assembly.strict_answer(
        [_point_candidate(-100.7800, 46.8100, fid=1),
         _point_candidate(-100.7810, 46.8100, fid=2)],
        tolerance_m=500.0,
    )
    separation = 76.0  # roughly, at this latitude

    assert answer.horizontal_uncertainty_m == pytest.approx(separation / 2, rel=0.2)


# ---------------------------------------------------------------------------
# §8.2 — the enhanced interface
# ---------------------------------------------------------------------------

def test_the_enhanced_interface_returns_every_candidate_unmerged():
    """Decision 27 — the honest answer to an underspecified query is a real
    candidate list, not a synthetic blended point."""
    listed = response_assembly.enhanced_answers(
        [_point_candidate(-100.7800, 46.8100, score=95.0, fid=1),
         _point_candidate(-100.7802, 46.8100, score=90.0, fid=2)])

    assert len(listed) == 2
    assert [a.quality.match_score for a in listed] == [95.0, 90.0]
    assert all(a.merged_count == 1 for a in listed)


def test_rank_1_is_the_same_candidate_on_both_interfaces():
    """The controlled comparison §2.2 exists for. GCS_MIN_MATCH_SCORE floors
    admission upstream in §6, so neither interface sees a candidate the other
    does not, and the candidate at rank 1 is the same one on both."""
    only = [_point_candidate(-100.7800, 46.8100, score=95.0, fid=1)]

    strict = response_assembly.strict_answer(only, tolerance_m=150.0)
    enhanced = response_assembly.enhanced_answers(only)

    assert strict.quality == enhanced[0].quality
    assert strict.geometry.equals(enhanced[0].geometry)


def test_a_merge_makes_the_two_interfaces_return_different_geometry():
    """Rank 1 is the same candidate on both, but the returned coordinate is
    not the same thing. Decision 27: constrained to a single pidfLoGeo, the
    strict interface averages the qualifying candidates, while the enhanced
    interface returns each on its own merits. Both report the same rank-1
    quality; only the strict side blends the position.

    Both candidates score 95.0 (tied) deliberately: decision 118 restricts
    §6.3's merge to the top-scoring tier, so a differently-scored pair would
    exercise that narrowing instead of the geometry-divergence behaviour this
    test is actually about. See test_a_trailing_candidate_does_not_join_a_
    merge_it_would_have_widened_beyond_tolerance below for the tie-filtering
    behaviour itself.
    """
    pair = [_point_candidate(-100.7800, 46.8100, score=95.0, fid=1),
            _point_candidate(-100.7802, 46.8100, score=95.0, fid=2)]

    strict = response_assembly.strict_answer(pair, tolerance_m=150.0)
    enhanced = response_assembly.enhanced_answers(pair)

    assert strict.quality.match_score == enhanced[0].quality.match_score == 95.0
    assert strict.merged_count == 2
    assert not strict.geometry.equals(enhanced[0].geometry)
    assert strict.geometry.x == pytest.approx(-100.7801)


# ---------------------------------------------------------------------------
# §6.3's merge/ambiguity test runs on the top-scoring tier only (decision 118)
# ---------------------------------------------------------------------------

def test_a_trailing_candidate_does_not_join_a_merge_it_would_have_widened_beyond_tolerance():
    """The real-data finding that motivated decision 118: two genuinely
    co-located candidates (score 100, a few metres apart) used to fail §6.3's
    spread test because a third candidate that only cleared
    GCS_MIN_MATCH_SCORE — not a real contender, 55 km away, trailing well
    below the leader — was still let into the same spread computation. It no
    longer is. Without the trailing candidate the two leaders merge cleanly;
    with it included the same merge would raise AmbiguousResult, which this
    test also confirms directly against resolve_ambiguity to show the
    narrowing is what changed the outcome, not the tolerance or the geometry.
    """
    leaders = [_point_candidate(-100.7800, 46.8100, score=100.0, fid=1),
               _point_candidate(-100.7802, 46.8100, score=100.0, fid=2)]
    trailing = _point_candidate(-101.5000, 46.8100, score=70.0, fid=3)

    answer = response_assembly.strict_answer(leaders + [trailing], tolerance_m=150.0)

    assert answer.merged_count == 2
    assert answer.quality.match_score == 100.0

    with pytest.raises(AmbiguousResult):
        candidates.resolve_ambiguity(leaders + [trailing], tolerance_m=150.0)


def test_scores_within_float_noise_of_each_other_still_count_as_tied():
    """_TOP_SCORE_TIE_EPSILON exists because _weighted_average() (src/engine/
    scoring.py) documents float summation landing an all-1.0 match a few ulps
    off 100.0 depending on term order — two candidates that are the same
    match by any real-world reading should not be split apart by that noise.
    """
    nearly_tied = [_point_candidate(-100.7800, 46.8100, score=100.0, fid=1),
                   _point_candidate(-100.7802, 46.8100, score=100.0 - 1e-9, fid=2)]

    answer = response_assembly.strict_answer(nearly_tied, tolerance_m=150.0)

    assert answer.merged_count == 2


def test_the_enhanced_list_keeps_line_answers_as_lines():
    listed = response_assembly.enhanced_answers([_segment_candidate()])

    assert isinstance(listed[0].geometry, LineString)
    # CRS_2D since decision 85; this asserted None while Q22 was open.
    assert listed[0].crs == CRS_2D


# ---------------------------------------------------------------------------
# Decision 121 / Appendix C.2 item 9's remainder — rung-3 ambiguity
# (FWD-DROPPED-HNO-STRICT-001), corrected to narrow on the SAME key
# _rank_segments ranks by (matchScore, then range_gap where a house number is
# available) rather than matchScore alone, so decision 120's already-settled
# picks (FWD-GAP-HNO-001) are not silently reopened by this decision's spread
# test — see the module docstring's "RUNG 3's TIER NARROWS ON THE SAME KEY IT
# RANKS BY" section.
# ---------------------------------------------------------------------------

FAR_SEGMENT = "LINESTRING (-101.800 46.810, -101.780 46.810)"


def test_a_lone_segment_candidate_returns_the_line_unchanged():
    """Nothing to be ambiguous about — the len<2 short-circuit in
    resolve_segment_ambiguity, exercised through strict_answer."""
    answer = response_assembly.strict_answer(
        [_segment_candidate()], tolerance_m=150.0)

    assert isinstance(answer.geometry, LineString)
    assert answer.position is None


def test_tied_segments_within_tolerance_return_the_leader():
    near = _segment_candidate(fid=1, wkt=SEGMENT)
    also_near = _segment_candidate(fid=2, wkt="LINESTRING (-100.8005 46.810, -100.7805 46.810)")

    answer = response_assembly.strict_answer(
        [near, also_near], tolerance_m=1000.0)

    assert isinstance(answer.geometry, LineString)
    assert answer.position is None


def test_tied_segments_beyond_tolerance_raise_with_no_house_number():
    """FWD-DROPPED-HNO-STRICT-001's own shape: no house number in the query
    at all, so there is no range_gap to narrow by — two same-named,
    identically-scored segments whose own geometries disagree by tens of
    kilometres reach the spread test as a full tie, exactly as
    resolve_segment_ambiguity expects. Assembly must not swallow that and
    hand back whichever sorted first by NGUID."""
    near = _segment_candidate(fid=1, wkt=SEGMENT)
    far = _segment_candidate(fid=2, wkt=FAR_SEGMENT)

    with pytest.raises(AmbiguousResult):
        response_assembly.strict_answer(
            [near, far], tolerance_m=150.0, house_number=None)


def test_a_house_number_that_range_gap_already_resolves_does_not_raise():
    """FWD-GAP-HNO-001's shape, and the regression this decision must not
    reopen: an HNO supplied (1911), one segment's own range sits close to it
    (gap 2) and a second, kilometres away, sits farther (gap 6) — both tied
    on matchScore alone, which is why a matchScore-only tier would wrongly
    treat this set as ambiguous. range_gap narrows the tier to the single
    near segment before the spread test ever runs, so this returns 200 with
    the near segment's line, not AmbiguousResult."""
    near = _segment_candidate(
        fid=1, wkt=SEGMENT, FromAddr_L=1901, ToAddr_L=1909, Parity_L="O")
    far = _segment_candidate(
        fid=2, wkt=FAR_SEGMENT, FromAddr_L=1917, ToAddr_L=1999, Parity_L="O")

    answer = response_assembly.strict_answer(
        [near, far], tolerance_m=150.0, house_number=1911)

    assert isinstance(answer.geometry, LineString)
    assert answer.geometry.equals(near.answer_geometry)


def test_a_house_number_tied_on_range_gap_still_raises():
    """The boundary case neither 'HNO present' nor 'HNO absent' alone would
    catch: two segments several kilometres apart whose own ranges BOTH
    contain the queried house number (range_gap == 0 for each), so range_gap
    narrows nothing — the tier stays at both, and the spread test still
    fires. A house number does not by itself prove a single, trustworthy
    segment when more than one segment's range legitimately claims it."""
    near = _segment_candidate(
        fid=1, wkt=SEGMENT, FromAddr_L=100, ToAddr_L=200, Parity_L="E")
    far = _segment_candidate(
        fid=2, wkt=FAR_SEGMENT, FromAddr_L=100, ToAddr_L=200, Parity_L="E")

    with pytest.raises(AmbiguousResult):
        response_assembly.strict_answer(
            [near, far], tolerance_m=150.0, house_number=150)


def test_a_trailing_lower_scored_segment_does_not_join_the_spread_test():
    """The rung-3 counterpart of decision 118's top-tier narrowing: a segment
    that only cleared GCS_MIN_MATCH_SCORE upstream and trails the leaders by
    a wide margin is not a real contender for the single answer, and must not
    be allowed to veto a genuine, tightly-clustered rung-3 result."""
    near = _segment_candidate(fid=1, wkt=SEGMENT, score=100.0)
    also_near = _segment_candidate(
        fid=2, wkt="LINESTRING (-100.8005 46.810, -100.7805 46.810)", score=100.0)
    trailing = _segment_candidate(fid=3, wkt=FAR_SEGMENT, score=65.0)

    answer = response_assembly.strict_answer(
        [near, also_near, trailing], tolerance_m=150.0)

    assert isinstance(answer.geometry, LineString)


def test_the_enhanced_interface_is_unaffected_by_the_rung_3_spread_test():
    """enhanced_answers() never calls resolve_segment_ambiguity or
    strict_answer at all, so the same widely-spread tied set that 468s on the
    strict interface still lists in full here — the test that guards against
    the spread check leaking into the wrong interface."""
    near = _segment_candidate(fid=1, wkt=SEGMENT)
    far = _segment_candidate(fid=2, wkt=FAR_SEGMENT)

    listed = response_assembly.enhanced_answers([near, far])

    assert len(listed) == 2
    assert all(isinstance(a.geometry, LineString) for a in listed)


def test_confidence_travels_with_every_answer():
    """§7.4 — the derived dial, computed from the two primaries."""
    listed = response_assembly.enhanced_answers(
        [_point_candidate(-100.78, 46.81, score=90.0)])

    assert listed[0].confidence == pytest.approx(72.0)
    assert listed[0].location_type is LocationType.ADDRESS_POINT
