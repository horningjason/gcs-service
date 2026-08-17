"""§9 admission and §10 nearest-feature search (src/reverse/).

The lexicographic ordering is the thing worth defending here. §10.3 argues at
length that containment, tier and distance must not be blended, and the two
failure modes are opposite: a blended score lets a nearer low-tier candidate
outrank a contained high-tier one, and a naive layer preference lets a distant
address point outrank the centerline the caller is standing on. Both are
tested directly.

Scorers are injected, as on the forward side — §10.6 withholds the component
weights and the extent-damping formula as proprietary tuning (Appendix C item
(d)).
"""

from __future__ import annotations

import math
import os

import pytest

from src.engine.models import LocationType
from src.reverse import origin as shapes
from src.reverse import search
from src.reverse.search import Hit
from src.gis.records import RCLRecord, SSAPRecord

SEGMENT = "LINESTRING (-100.800 46.810, -100.780 46.810)"


def flat(origin, hit):
    """A scorer that says nothing, so ordering is visibly not its doing."""
    return 50.0, {}


def _ssap(fid=1, lon=-100.79, lat=46.81, alt=None, **kwargs):
    wkt = f"POINT Z ({lon} {lat} {alt})" if alt is not None else f"POINT ({lon} {lat})"
    kwargs.setdefault("NGUID", f"{{S-{fid}}}")
    kwargs.setdefault("geometry_wkt", wkt)
    return SSAPRecord(fid=fid, **kwargs)


def _rcl(fid=1, **kwargs):
    kwargs.setdefault("NGUID", f"{{R-{fid}}}")
    kwargs.setdefault("geometry_wkt", SEGMENT)
    return RCLRecord(fid=fid, **kwargs)


def _hit(contained, tier, distance, nguid="{X}", banded=False):
    class _Stub:
        def __init__(self):
            self.nguid = nguid
            self.is_tie_breakable = nguid is not None
    return Hit(record=_Stub(), distance_m=distance, contained=contained,
               tier=tier, vertically_banded=banded)


# ---------------------------------------------------------------------------
# §9 — eight shapes, one origin
# ---------------------------------------------------------------------------

def test_a_point_supplies_itself():
    got = shapes.Point(-100.79, 46.81).origin()
    assert (got.longitude, got.latitude) == (-100.79, 46.81)
    assert got.extent_m == 0.0


def test_a_circle_yields_its_centre_and_radius():
    got = shapes.Circle(-100.79, 46.81, radius_m=250.0).origin()
    assert (got.longitude, got.latitude) == (-100.79, 46.81)
    assert got.extent_m == 250.0


def test_a_polygon_yields_its_footprint_centroid():
    got = shapes.Polygon((
        (-100.80, 46.80), (-100.78, 46.80), (-100.78, 46.82), (-100.80, 46.82),
    )).origin()
    assert got.longitude == pytest.approx(-100.79)
    assert got.latitude == pytest.approx(46.81)


def test_a_prism_yields_its_footprint_centroid_at_mid_height():
    """§7.5 — the vertical midpoint, not the floor. Naming floor 1 of a
    twenty-storey structure puts a responder up to sixty metres out."""
    got = shapes.Prism(
        vertices=((-100.80, 46.80), (-100.78, 46.80), (-100.78, 46.82), (-100.80, 46.82)),
        base_altitude=500.0, height_m=60.0,
    ).origin()

    assert got.altitude == pytest.approx(530.0)
    assert got.vertical_extent_m == pytest.approx(60.0)


def test_an_arcband_origin_lands_inside_the_band():
    """RFC 5491's ArcBand centre is the arc's apex, which is outside the shape.
    Using it as the origin would put the search origin outside the caller's own
    query, so §7.5's footprint centroid is taken literally."""
    band = shapes.ArcBand(
        longitude=-100.79, latitude=46.81,
        inner_radius_m=100.0, outer_radius_m=300.0,
        start_angle_deg=0.0, opening_angle_deg=90.0,
    )
    got = band.origin()

    assert band.contains(got.longitude, got.latitude) is True
    # And it is not the apex.
    assert (got.longitude, got.latitude) != (-100.79, 46.81)


@pytest.mark.parametrize("shape", [
    shapes.Point(-100.79, 46.81),
    shapes.Circle(-100.79, 46.81, 250.0),
    shapes.Sphere(-100.79, 46.81, 500.0, 250.0),
    shapes.Ellipse(-100.79, 46.81, 300.0, 100.0, 45.0),
    shapes.Ellipsoid(-100.79, 46.81, 500.0, 300.0, 100.0, 20.0, 45.0),
    shapes.ArcBand(-100.79, 46.81, 100.0, 300.0, 0.0, 90.0),
    shapes.Polygon(((-100.80, 46.80), (-100.78, 46.80), (-100.78, 46.82))),
    shapes.Prism(((-100.80, 46.80), (-100.78, 46.80), (-100.78, 46.82)), 500.0, 60.0),
])
def test_all_eight_shapes_reduce_to_one_origin(shape):
    """Accepting only a Point would be a restriction i3 does not impose, and
    nothing downstream of here branches on shape."""
    got = shapes.origin_of(shape)
    assert math.isfinite(got.longitude) and math.isfinite(got.latitude)


def test_a_point_contains_nothing():
    """§10.3 depends on this: it is why the commonest input in the system never
    reaches the containment rule and orders by pure proximity."""
    assert shapes.Point(-100.79, 46.81).contains(-100.79, 46.81) is False


def test_extent_survives_the_reduction_to_an_origin():
    """A query expressing two kilometres of uncertainty must not score as
    though it expressed two metres (§9, §10.6)."""
    vague = shapes.Circle(-100.79, 46.81, 2000.0).origin()
    precise = shapes.Point(-100.79, 46.81).origin()

    assert vague.extent_m == 2000.0 and vague.has_extent
    assert precise.extent_m == 0.0 and not precise.has_extent


def test_containment_uses_the_shape_not_the_radius():
    circle = shapes.Circle(-100.79, 46.81, 100.0)
    assert circle.contains(-100.79, 46.8105) is True   # ~55 m north
    assert circle.contains(-100.79, 46.8120) is False  # ~220 m north


# ---------------------------------------------------------------------------
# §10.3 — lexicographic ordering
# ---------------------------------------------------------------------------

def test_a_contained_higher_tier_beats_a_nearer_uncontained_one():
    """The failure a blended score produces. Among contained candidates a
    higher tier wins regardless of distance, so a contained address point beats
    a nearer road."""
    contained_point = _hit(True, LocationType.ADDRESS_POINT, 180.0, "{A}")
    near_road = _hit(False, LocationType.INTERPOLATED_POINT, 5.0, "{B}")

    assert search.order([near_road, contained_point])[0] is contained_point


def test_tier_does_not_beat_distance_when_nothing_is_contained():
    """The opposite failure. A Point input contains nothing, so the ordering is
    nearest-by-distance regardless of layer: someone 200 m from an address
    point and 5 m from a centerline is on the road."""
    far_point = _hit(False, LocationType.ADDRESS_POINT, 200.0, "{A}")
    near_road = _hit(False, LocationType.INTERPOLATED_POINT, 5.0, "{B}")

    assert search.order([far_point, near_road])[0] is near_road


def test_tier_orders_within_the_contained_group_only():
    contained_road = _hit(True, LocationType.INTERPOLATED_POINT, 5.0, "{A}")
    contained_point = _hit(True, LocationType.ADDRESS_POINT, 190.0, "{B}")
    outside_point = _hit(False, LocationType.ADDRESS_POINT, 1.0, "{C}")

    ordered = search.order([outside_point, contained_road, contained_point])
    assert ordered[0] is contained_point   # contained, higher tier
    assert ordered[1] is contained_road    # contained, lower tier
    assert ordered[2] is outside_point     # uncontained, however near


def test_distance_orders_within_a_tier():
    near = _hit(True, LocationType.ADDRESS_POINT, 10.0, "{A}")
    far = _hit(True, LocationType.ADDRESS_POINT, 90.0, "{B}")

    assert search.order([far, near])[0] is near


def test_ties_break_on_nguid_ascending():
    """§10.4 — arbitrary and deliberately so. An arbitrary rule applied
    identically by every implementation is what makes two GCS instances
    provisioned from the same SI agree."""
    b = _hit(False, LocationType.ADDRESS_POINT, 42.0, "{B}")
    a = _hit(False, LocationType.ADDRESS_POINT, 42.0, "{A}")

    assert [h.nguid for h in search.order([b, a])] == ["{A}", "{B}"]


def test_the_vertical_band_leads_the_ordering():
    """§10.5 — Z-containing candidates band ahead, and horizontal distance
    orders within a band. Never Euclidean."""
    banded_far = _hit(False, LocationType.ADDRESS_POINT, 200.0, "{A}", banded=True)
    unbanded_near = _hit(False, LocationType.ADDRESS_POINT, 5.0, "{B}")

    assert search.order([unbanded_near, banded_far])[0] is banded_far


# ---------------------------------------------------------------------------
# §10.1 / §10.2 — one pass, bounded
# ---------------------------------------------------------------------------

def test_candidates_beyond_the_radius_are_not_returned():
    """§10.2's reason for existing: without a maximum, a point in open water
    reverse-geocodes to whatever unfortunate address is nearest, and returns
    200 while doing it."""
    far = _ssap(1, lon=-101.50, lat=46.81)
    hits = search.search(shapes.Point(-100.79, 46.81).origin(),
                         ssap=[far], rcl=[], radius_m=250.0)
    assert hits == []


def test_an_empty_result_is_how_468_is_reached():
    assert search.search(shapes.Point(0.0, 0.0).origin(),
                         ssap=[], rcl=[], radius_m=250.0) == []


def test_both_layers_are_searched_in_one_pass():
    hits = search.search(
        shapes.Point(-100.790, 46.8102).origin(),
        ssap=[_ssap(1, lon=-100.790, lat=46.8105)],
        rcl=[_rcl(2, FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
        radius_m=250.0,
    )
    assert len(hits) == 2


def test_distance_is_measured_to_the_centerline_as_it_exists():
    """§10.5, decision 42 — no synthetic half-carriageway adjustment. The
    documented bias in favour of address points is the price, and the raw
    distance travelling on the enhanced interface is the disclosure."""
    hits = search.search(
        shapes.Point(-100.790, 46.8110).origin(),
        ssap=[], rcl=[_rcl(1, FromAddr_L=100, ToAddr_L=200, Parity_L="E")],
        radius_m=250.0,
    )
    # ~111 m north of a segment lying along 46.810.
    assert hits[0].distance_m == pytest.approx(111.0, rel=0.05)


def test_an_unlocatable_record_is_not_a_candidate():
    """Decision 55 — no usable geometry means no position, and the attribute
    columns are not read to repair it."""
    hits = search.search(
        shapes.Point(-100.79, 46.81).origin(),
        ssap=[_ssap(1, geometry_wkt=None, Longitude=-100.79, Latitude=46.81)],
        rcl=[], radius_m=250.0,
    )
    assert hits == []


def test_a_multipart_segment_is_not_a_candidate():
    """Decision 53 — no defined traversal order, so §11.2 could not invert it."""
    hits = search.search(
        shapes.Point(-100.79, 46.81).origin(),
        ssap=[],
        rcl=[_rcl(1, geometry_wkt=(
            "MULTILINESTRING ((-100.800 46.810, -100.795 46.810),"
            " (-100.790 46.810, -100.780 46.810))"))],
        radius_m=250.0,
    )
    assert hits == []


# ---------------------------------------------------------------------------
# §10.6 — the score decorates, it never re-ranks
# ---------------------------------------------------------------------------

def test_the_scorer_does_not_disturb_the_ordering():
    """§10.6 argues this at length: extent damps the score and must not weaken
    containment in the ordering. The two stay separable only because the
    ordering is lexicographic and the score is advisory."""
    hits = [
        _hit(True, LocationType.ADDRESS_POINT, 180.0, "{A}"),
        _hit(False, LocationType.INTERPOLATED_POINT, 5.0, "{B}"),
    ]
    ordered = search.order(hits)

    def perverse(origin, hit):
        # Score inverted against the ordering on purpose.
        return (10.0 if hit.contained else 99.0), {}

    scored = search.to_candidates(
        shapes.Point(-100.79, 46.81).origin(), ordered, score=perverse)

    assert [c.record.nguid for c in scored] == ["{A}", "{B}"]
    assert scored[0].match_score == 10.0 and scored[1].match_score == 99.0


def test_the_score_breakdown_travels():
    hits = search.search(
        shapes.Circle(-100.790, 46.8102, 250.0).origin(),
        ssap=[_ssap(1, lon=-100.790, lat=46.8105)], rcl=[], radius_m=250.0)

    scored = search.to_candidates(
        shapes.Circle(-100.790, 46.8102, 250.0).origin(), hits,
        score=lambda o, h: (80.0, {"distance": 90.0, "containment": 100.0}),
    )
    assert scored[0].quality.field_scores == {"distance": 90.0, "containment": 100.0}
    assert scored[0].distance_m == pytest.approx(hits[0].distance_m)


def test_confidence_still_derives_from_the_tier_ceiling():
    """§10.6 — the three-field model carries over unchanged in shape; only the
    matchScore slot is refilled."""
    hits = search.search(
        shapes.Point(-100.790, 46.8102).origin(),
        ssap=[_ssap(1, lon=-100.790, lat=46.8105)], rcl=[], radius_m=250.0)
    scored = search.to_candidates(
        shapes.Point(-100.790, 46.8102).origin(), hits, score=lambda o, h: (90.0, {}))

    assert scored[0].location_type is LocationType.ADDRESS_POINT
    assert scored[0].confidence == pytest.approx(72.0)


def test_a_null_nguid_record_is_flagged_ineligible_for_tie_breaking():
    """R3 — reported via the discrepancy path, never given a local surrogate."""
    hits = search.search(
        shapes.Point(-100.790, 46.8102).origin(),
        ssap=[_ssap(1, lon=-100.790, lat=46.8105, NGUID=None)],
        rcl=[], radius_m=250.0)

    assert hits[0].is_tie_breakable is False


# ---------------------------------------------------------------------------
# Decision 99 — filing DataQualityFlag conditions against the SI
# ---------------------------------------------------------------------------
# ssap_hits()/rcl_hits() are where a GisRecord's flags are turned into a
# filed report — never GisRecord.from_record() itself (see
# tests/conformance/test_models.py's
# test_detection_does_not_file_a_discrepancy_report). fire_gis_dr is patched
# out here: what these tests own is that the right problem token fires for
# the right condition, not src/discrepancy/discrepancy_report.py's own
# submission behaviour, which tests/conformance/test_discrepancy_report.py
# covers directly.

def _patched_fire(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "fire_gis_dr",
                         lambda *a, **kw: calls.append((a, kw)))
    return calls


def test_ngid_missing_ssap_hit_files_an_omitted_field_report(monkeypatch):
    """The same R3 condition as test_a_null_nguid_record_is_flagged_
    ineligible_for_tie_breaking above, now asserting the filing side
    decision 99 adds rather than just the local tie-break consequence."""
    calls = _patched_fire(monkeypatch)

    search.ssap_hits(
        shapes.Point(-100.790, 46.8102).origin(),
        [_ssap(1, lon=-100.790, lat=46.8105, NGUID=None)],
        radius_m=250.0)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (search.GISProblem.OmittedField, search.ProblemSeverity.Minor)
    assert kwargs["detail"] == "NGUID"
    assert kwargs["layer_ids"] == os.environ.get(
        "GCS_SSAP_LAYER", "SiteStructureAddressPoint")


def test_no_geometry_ssap_hit_files_a_bad_geometry_report(monkeypatch):
    calls = _patched_fire(monkeypatch)

    search.ssap_hits(
        shapes.Point(-100.790, 46.8102).origin(),
        [_ssap(1, lon=-100.790, lat=46.8105, geometry_wkt=None)],
        radius_m=250.0)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (search.GISProblem.BadGeometry, search.ProblemSeverity.Moderate)
    assert kwargs["detail"] == "no usable geometry"


def test_a_clean_ssap_hit_files_no_discrepancy_report(monkeypatch):
    """Negative control — a record with no data quality issue files nothing."""
    calls = _patched_fire(monkeypatch)

    search.ssap_hits(
        shapes.Point(-100.790, 46.8102).origin(),
        [_ssap(1, lon=-100.790, lat=46.8105)],
        radius_m=250.0)

    assert calls == []


def test_ngid_missing_rcl_hit_files_an_omitted_field_report(monkeypatch):
    calls = _patched_fire(monkeypatch)

    search.rcl_hits(
        shapes.Point(-100.790, 46.8102).origin(),
        [_rcl(1, NGUID=None)],
        radius_m=250.0)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (search.GISProblem.OmittedField, search.ProblemSeverity.Minor)
    assert kwargs["layer_ids"] == os.environ.get("GCS_RCL_LAYER", "RoadCenterLine")


def test_multipart_rcl_hit_files_a_bad_geometry_report(monkeypatch):
    """Decision 53 — same condition test_multipart_geometry_is_carried_not_
    discarded (test_models.py) exercises at the engine-model layer, now
    asserted at the search call site that turns the flag into a report."""
    calls = _patched_fire(monkeypatch)

    search.rcl_hits(
        shapes.Point(-100.790, 46.8102).origin(),
        [_rcl(1, geometry_wkt=(
            "MULTILINESTRING ((-100.80 46.81, -100.79 46.81),"
            " (-100.78 46.81, -100.77 46.81))"))],
        radius_m=250.0)

    problems = [args[0] for args, kwargs in calls]
    assert search.GISProblem.BadGeometry in problems
    details = [kwargs["detail"] for args, kwargs in calls
               if args[0] is search.GISProblem.BadGeometry]
    assert any("multi-part" in d for d in details)
