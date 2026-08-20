"""§6 — candidate identification for the forward direction.

The ladder, then the score, then §6.3's ambiguity test.

NO FILTER, WITH TWO NAMED EXCEPTIONS (§6.2, decision 61, amended by 69 and 75)

Every temporally-valid record in the searched layer is scored against the query
on every request. No record is excluded from scoring on the basis of any civic
element — administrative, postal, place-name, street — with two deliberate
exceptions on SSAP (rung 1) candidates: house number identity (decision 69),
and unit identity (decision 75).

A filter exists to reduce scoring cost and pays for that reduction in accuracy.
Anything it excludes is excluded permanently: there is no second pass, so every
filtered element is one where a caller's typo or a record's own data defect
produces a 468 rather than a low score. This service prioritises accuracy over
throughput, which makes that an unfavourable trade at any element list. Scoring
the full layer removes the failure mode rather than managing it — for fields
where "close" is a meaningful idea. House number on an address point is not one
of those fields: 415 and 416 are not a fuzzy version of the same location, they
are two different buildings, and a general-purpose string similarity (edit
distance) scoring them ~67% alike was pulling in wrong-address candidates from
across town, spreading the surviving set past GCS_AMBIGUITY_TOLERANCE_M, and
producing exactly the silent-468 failure mode this section's own rationale
warns against — just triggered by false similarity instead of a missing record.
A hard equality gate on Add_Number, applied only when the query supplies one,
fixes that at the source rather than by tuning weights around it. This is the
same principle decision 31 already established (default ranking by blended
confidence, so a shaky match ranks below a trustworthy one because false
precision sends a dispatcher to the wrong building, §7.4) taken to a hard gate
instead of a soft rank penalty, justified because house number is an identity
field for an address point, not a similarity field.

Road interpolation (RCL, rung 2/3) is unaffected: it was never scored on
Add_Number similarity, and already uses §7.2's range/parity containment, which
is a correctness test on which segment the number falls within, not a fuzzy
comparison — the same kind of exception §3.4's temporal filter already is.

UNIT IDENTITY (decision 75)

UnitValue was investigated separately and found to be carried through the
record model, the GIS loader, and the wire round-trip, yet read nowhere in
score_ssap — a real gap against §3.10's statement that it "remains available
to §6.5 scoring where the record carries them." Tracing the actual response
consequence (rather than assuming its severity) found it bimodal: at a
multi-unit address whose records are spread beyond GCS_AMBIGUITY_TOLERANCE_M,
§6.3 already fails honestly with 468; at a tightly-clustered one (many real
addresses in the provisioned data — apartment/dorm complexes chiefly), every
unit ties at the same matchScore and §6.3's merge silently averages across all
of them, at a `confidence` indistinguishable from an unambiguous single match,
regardless of which unit the query named.

decision 75 closes that with the same shape as decision 69: a hard gate,
applied only when the query supplies a unit value, checked before scoring.
Where it differs is decision 61's sparseness carve-out — a candidate carrying
NO unit at all is not excluded even though the query asked for one, because
absence is not disagreement (most SSAP records in the provisioned data have no
unit populated and are ordinary single-unit addresses, not non-matches). Only
a candidate that DOES carry a unit, and carries a DIFFERENT one, is excluded.
UnitPreTyp ("Apt"/"Unit"/"Suite") plays no part — only UnitValue itself, after
trim + casefold normalization. RCL is unaffected: RCLRecord has no unit
columns at all (STA-006.3 does not provision sub-address attribution on
centerlines), so there is nothing for a rung-2/3 gate to check.

Two exclusions are not part of this rule and remain in force. §3.4's temporal
filter is a correctness test, not a narrowing one — a record outside its
Effective/Expire window is wrong rather than merely unlikely — and is applied
before scoring. GCS_MIN_MATCH_SCORE (§6.4) applies after every record has been
scored, so it discards nothing unseen. This candidate set — everyone who
cleared the floor — is what GeocodeEnhanced returns and what this module
hands onward. What the STRICT interface does with it is narrower still:
decision 118 (src/geocode/response_assembly.py::strict_answer) restricts
§6.3's own ambiguity/merge test to the top-scoring tier of that set, so a
candidate that is merely admissible never gets to blow up a real, tightly
clustered merge among the genuine leaders. That narrowing happens one layer
up from here, not in this module — nothing in candidate identification
itself discards a low-but-admissible scorer.

RUNG 1 IS NOT APPLICABLE WITHOUT A HOUSE NUMBER (§5, §6.1, decision 119)

`ssap_candidates` returns an empty list — without calling the scorer once —
when the query supplies no usable Add_Number. Two ways in: the caller sent no
`ca:HNO` at all, or sent one that decision 63 dropped because it does not
reduce to a non-negative integer.

This reads at first like the filter decision 61 abolished and like the
administrative gate decision 82 declined, and it is neither. Both of those
govern which RECORDS may answer a question the rung is capable of answering.
This governs whether the rung is capable of answering the question at all. An
address point's identity is its house number — that is decision 69's whole
premise, and the reason Add_Number is a gate rather than a scored term — so a
query with no house number has nothing for rung 1 to be an answer to. Every
position rung 1 could return in that case asserts a house number the caller
never supplied and the service has no basis to choose among: given "Interstate
94 Ramp, Bismarck" it replies "13101 Interstate 94," which is a different
address, not a less precise version of the one asked about.

Nor is it Gate 1 (§5, decision 14). Gate 1 would REFUSE the request. Nothing
here refuses anything: the request is admitted, scored, and answered, at rung
3, which is exactly what §5, decision 63 and §15.1 step 4 have said all along.
Before decision 119 they said it and the ladder did not do it — with rung 1
searched unconditionally and decision 69's gate silent for want of a query
house number, every address point on the named street was scored, and a rung-1
best at or above the INTERPOLATED_POINT ceiling then short-circuited the road
scan entirely (see the ladder section below). The street-level answer the spec
promised was reachable only when the SSAP layer happened to hold nothing on
that street.

One consequence, stated rather than hidden: a street carrying address points
but no centerline record now yields 468 for a house-number-free query where it
previously returned a point. That is §6.4's honest failure and is listed there
as a path in its own right. It requires a provisioning defect — RoadCenterLine
is Required for the GCS under STA-006.3 Table 4-1 — and returning a wrong
house number is not the better answer to it.

LAYER ORDER IS A LADDER, AND THE RUNGS COMPETE ON CONFIDENCE (§3.3, §6.1,
decision 70)

SSAP is searched first and RoadCenterLine second, following i3 §4.5's own
ordering ("site/structure address points or road centerlines"). The rungs are
not interchangeable answers of differing quality — rung 3 is a different kind
of answer, a whole segment rather than a position — so the response carries
one rung's candidates and does not blend across rungs.

Which rung's, though, is decided by comparing best candidates on blended
confidence, not by taking the first rung that produced anything. Decision 69's
house-number gate admits every address point in the deployment that happens to
carry the query's house number — it checks identity on ONE field, and with a
low GCS_MIN_MATCH_SCORE those coincidental survivors are a non-empty rung 1
that would otherwise shadow a road segment matching the query exactly, range
and parity included. §7.4's own rationale (decision 31) says which answer
should win: a shaky point match ranks below a perfect street match, because
for 9-1-1 precision that cannot be trusted is a dispatcher sent to the wrong
building. The tier ceilings (ADDRESS_POINT 80, INTERPOLATED_POINT 75,
STREET_SEGMENT 50) already price the precision difference, so a genuine
address-point match (score 100 -> confidence 80) still beats its own street's
interpolation (75) and nothing regresses for well-provisioned addresses.

Rung 1 short-circuits the road scan when its best confidence reaches the
INTERPOLATED_POINT ceiling — no lower rung can beat it, so the common
well-formed case (exact address point on file) never scores the RCL layer.
Ties go to the more precise rung.

WHERE SCORING COMES FROM

It is injected. §6.5 settles the shape of the scoring function and deliberately
withholds the formula from the specification; the formula now exists —
src/engine/scoring.py, closed out by decision 89 — and src/app/lifecycle.py
registers it through src/engine/scoring_registry.py at startup. This module
still takes a `score` callable and has no default, and that is not a
placeholder for a missing decision — it is the decision, kept where the spec
put it. Everything §6 actually specifies (search order, the candidate set, the
floor, ambiguity, the paths to zero candidates) is implemented here and testable
with any scorer, including the deliberately trivial ones the tests inject.

NO GATE 1 (§5, decision 14)

Nothing here requires a house number, a street, or any other element. i3 §4.5
imposes no structural precondition on Geocode and adding one would be a
restriction the standard does not have. A query with no HNO is accepted and
answered at rung 3 — decision 119 above is what makes that true in the ladder
rather than only in the prose, and is an applicability rule for one rung, not
a precondition on the request; a query with an HNO that no segment asserts
falls to rung 3 the same way, which §5 flags as the more dangerous case
precisely because it degrades silently — the honesty burden lands on §7.4's
tier and confidence.
"""

from __future__ import annotations

import datetime
import math
import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Protocol, Sequence

from src.discrepancy.discrepancy_report import GISProblem, ProblemSeverity, fire_gis_dr
from src.engine import geometry
from src.engine.models import (
    Candidate,
    CivicAddress,
    DataQualityFlag,
    LocationType,
    MatchQuality,
    Position,
    RclGisRecord,
    SsapGisRecord,
)
from src.geocode import position as position_derivation
from src.gis.records import RCLRecord, SSAPRecord


class Scorer(Protocol):
    """§6.5's per-field similarity, as this module needs to see it.

    Returns the 0-100 match score and the per-field breakdown the enhanced
    interface surfaces (§7.4, HERE's fieldScore precedent). One function, not
    an exact-then-fuzzy pipeline: an exact match is the ceiling of the same
    scale a fuzzy match scores lower in (decision 28).
    """

    def __call__(
        self, query: CivicAddress, record: SSAPRecord | RCLRecord
    ) -> tuple[float, Mapping[str, float]]:
        ...


class AmbiguousResult(Exception):
    """§6.3 — surviving candidates disagree horizontally beyond tolerance.

    Maps to 468 (§8.4). Two "State Street" matches forty miles apart are not a
    location, and merging them yields a position in a field with a 32 km
    uncertainty that a consumer ignoring uncertainty will treat as an answer.
    """

    def __init__(self, spread_m: float, tolerance_m: float, count: int) -> None:
        super().__init__(
            f"{count} candidates span {spread_m:.1f} m, beyond the configured "
            f"GCS_AMBIGUITY_TOLERANCE_M of {tolerance_m:.1f} m"
        )
        self.spread_m = spread_m
        self.tolerance_m = tolerance_m
        self.count = count


# ---------------------------------------------------------------------------
# §3.4 temporal filtering
# ---------------------------------------------------------------------------

def is_active(record: SSAPRecord | RCLRecord, at: Optional[datetime.datetime]) -> bool:
    """Whether a record is in force at a given instant.

    §3.4 is still undrafted, so this implements only the part that is not in
    doubt: a record with no Effective or Expire is always active, which is
    every record in the provisioned data. Where the dates are present they are
    honoured inclusively at the start and exclusively at the end.

    An unparseable date is treated as absent rather than as a reason to drop
    the record. Dropping it would remove an address from service over a
    formatting defect.
    """
    if at is None:
        return True
    for value, is_start in ((record.Effective, True), (record.Expire, False)):
        if value is None:
            continue
        try:
            moment = datetime.datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        if is_start and at < moment:
            return False
        if not is_start and at >= moment:
            return False
    return True


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

def _quality(score: float, breakdown: Mapping[str, float], tier: LocationType) -> MatchQuality:
    return MatchQuality(match_score=score, location_type=tier, field_scores=dict(breakdown))


def _rank(candidates: list[Candidate]) -> list[Candidate]:
    """§7.4 — default ranking is by blended confidence.

    A shaky point match can therefore rank below a perfect street match: for
    9-1-1, precision that cannot be trusted is a dispatcher sent to the wrong
    building. Both primary axes still travel, so a consumer can re-rank on
    either. NGUID breaks residual ties so repeated calls agree with each other.
    """
    return sorted(
        candidates,
        key=lambda c: (-c.confidence, -c.match_score, c.nguid or ""),
    )


def range_gap(record: RclGisRecord, house_number: int) -> float:
    """Decision 120 — how far `house_number` sits outside a segment's own
    asserted address range(s), 0 where a side's range already contains it.

    Every side present is considered, not only the parity-preferred one
    (`position.select_side`): this runs on rung-3 candidates specifically
    because no side claimed the number (or the segment was otherwise
    unusable for interpolation), so there is no "correct" side left to
    prefer — only a proximity estimate, for which either side's range is
    equally informative. `math.inf` where the record asserts no range at
    all, so it sorts behind every candidate that does.

    Not module-private (no leading underscore) since decision 121:
    `response_assembly.strict_answer` needs this exact function, not a
    reimplementation of it, to narrow the ambiguity-check tier on the same
    key `_rank_segments` below ranks by — see that function's own docstring
    for why matchScore alone is too coarse a tier for the ambiguity check.
    """
    ranges = position_derivation.side_ranges(record)
    if not ranges:
        return math.inf
    return min(max(r.low - house_number, house_number - r.high, 0) for r in ranges)


def _rank_segments(
    candidates: list[Candidate], house_number: Optional[int]
) -> list[Candidate]:
    """§7.4 ranking for rung-3 segments (Appendix C.2 item 9, decision 120).

    Same blended-confidence ordering as `_rank`, with one addition: rung 3's
    matchScore carries no house-number term (interpolation already failed,
    by definition, for every candidate here), so every segment sharing a
    street name ties at identical confidence and matchScore regardless of
    how far its own address range sits from the query's house number.
    `_rank`'s NGUID tiebreak resolved that arbitrarily — alphabetically,
    with no relationship to the corridor — which is how a query for 1911
    could land on a segment numbered in the 3000s while segments bracketing
    the actual gap sat unchosen in the tied set.

    Where the query supplies a house number, ties are now broken by
    `range_gap` before NGUID: the segment whose own range sits closest to
    the query wins, which is a geographically meaningful choice `_rank`'s
    tiebreak could not express. Where it does not
    (`FWD-DROPPED-HNO-STRICT-001`'s shape — no house number to measure a gap
    against at all), this reduces to `_rank` exactly, and the tie is left
    exactly as arbitrary as `_rank`'s NGUID order always was — closing that
    gap is `resolve_segment_ambiguity`'s job (decision 121), not this
    function's; this function only orders candidates; it does not decide
    which of them is trustworthy enough to return.
    """
    if house_number is None:
        return _rank(candidates)
    return sorted(
        candidates,
        key=lambda c: (
            -c.confidence,
            -c.match_score,
            range_gap(c.record, house_number),
            c.nguid or "",
        ),
    )


def _unit_matches(query_value: str, record_value: str) -> bool:
    """Decision 75 — trim + casefold before comparing. UnitPreTyp ("Apt",
    "Unit", "Suite") plays no part in this gate, only UnitValue itself."""
    return query_value.strip().casefold() == record_value.strip().casefold()


def ssap_candidates(
    query: CivicAddress,
    records: Iterable[SSAPRecord],
    *,
    score: Scorer,
    min_match_score: float,
    at: Optional[datetime.datetime] = None,
) -> list[Candidate]:
    """Rung 1 — address points.

    Returns nothing at all when the query supplies no usable Add_Number
    (decision 119). That is an applicability test for the rung, not a filter
    over the candidate set: an address point's identity IS its house number,
    so with no house number in the query there is no question for this rung
    to answer, and every position it could return would assert an element the
    caller never supplied. §5's promise — a street-level query is accepted and
    answered at rung 3 — is delivered here rather than merely asserted. See
    RUNG 1 IS NOT APPLICABLE WITHOUT A HOUSE NUMBER in the module docstring
    for why this is neither Gate 1 (§5, decision 14) nor a reversion of
    decision 61.

    Otherwise every temporally-valid record is scored (decision 61); nothing
    is excluded on a civic element before the scorer sees it — except house
    number and unit, both hard gates rather than scored fields (decisions 69
    and 75).

    A record whose Add_Number does not exactly equal the query's is excluded
    before scoring, not scored low — see decision 69. That gate and decision
    119's applicability test are the two halves of one rule: 69 governs which
    records answer a house-number query, 119 governs whether there is a
    house-number query to answer.

    A record whose UnitValue disagrees with the query's is excluded the same
    way — see decision 75 and _unit_matches below — but ONLY when the record
    actually carries a unit. A record with no unit at all is not excluded even
    though the query asked for one: decision 61's sparseness posture, and the
    reason this gate is not a plain mirror of decision 69's.

    A record that clears the floor but cannot be located (decision 55: no usable
    geometry) is dropped here rather than returned unlocated. It is still
    flagged on the record for whoever consumes data quality; it is simply not an
    answer to a question about where something is.
    """
    # Decision 119 — before anything else, and before the scorer is called
    # even once. Not a `continue` inside the loop: no SSAP record is a
    # candidate for a query with no house number, so there is nothing to
    # iterate.
    if query.Add_Number is None:
        return []

    ssap_layer = os.environ.get("GCS_SSAP_LAYER", "SiteStructureAddressPoint")
    out: list[Candidate] = []
    for record in records:
        if not is_active(record, at):
            continue
        # Decision 69 — identity, not similarity. Unconditional here because
        # decision 119's early return above already guarantees the query has
        # a house number to compare against.
        if record.Add_Number != query.Add_Number:
            continue
        if (
            query.UnitValue is not None
            and record.UnitValue is not None
            and not _unit_matches(query.UnitValue, record.UnitValue)
        ):
            continue
        value, breakdown = score(query, record)
        if value < min_match_score:
            continue
        gis = SsapGisRecord.from_record(record)
        if gis.has_flag(DataQualityFlag.NGUID_MISSING):
            fire_gis_dr(GISProblem.OmittedField, ProblemSeverity.Minor,
                        detail="NGUID", layer_ids=ssap_layer)
        if gis.has_flag(DataQualityFlag.NO_GEOMETRY):
            fire_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate,
                        detail="no usable geometry", layer_ids=ssap_layer)
        if not gis.is_located or gis.position is None:
            continue
        out.append(
            Candidate(
                record=gis,
                quality=_quality(value, breakdown, LocationType.ADDRESS_POINT),
                position=gis.position,
                answer_geometry=gis.geometry,
            )
        )
    return _rank(out)


def rcl_candidates(
    query: CivicAddress,
    records: Iterable[RCLRecord],
    *,
    score: Scorer,
    min_match_score: float,
    offset_m: float,
    endpoint_margin_m: float,
    at: Optional[datetime.datetime] = None,
) -> tuple[list[Candidate], list[Candidate]]:
    """Rungs 2 and 3 — centerlines, interpolated and whole.

    Returns the two rungs separately because they are different kinds of
    answer, not a ranked continuum. A segment that can carry the query's house
    number produces a rung-2 candidate; the same segment produces a rung-3
    candidate when it cannot, or when the query carried no house number at all.
    The rung-3 set is ranked by `_rank_segments`, not `_rank` (decision 120):
    where the query supplies a house number, ties among identically-scored
    segments are broken by proximity of the segment's own range to that
    number rather than by NGUID alone.
    """
    rcl_layer = os.environ.get("GCS_RCL_LAYER", "RoadCenterLine")
    interpolated: list[Candidate] = []
    segments: list[Candidate] = []

    for record in records:
        if not is_active(record, at):
            continue
        value, breakdown = score(query, record)
        if value < min_match_score:
            continue

        gis = RclGisRecord.from_record(record)
        if gis.has_flag(DataQualityFlag.NGUID_MISSING):
            fire_gis_dr(GISProblem.OmittedField, ProblemSeverity.Minor,
                        detail="NGUID", layer_ids=rcl_layer)
        if gis.has_flag(DataQualityFlag.NO_GEOMETRY):
            fire_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate,
                        detail="no usable geometry", layer_ids=rcl_layer)
        if gis.has_flag(DataQualityFlag.MULTIPART_SEGMENT):
            fire_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate,
                        detail="multi-part segment: no defined traversal order",
                        layer_ids=rcl_layer)
        if not gis.is_located:
            continue

        placed = None
        if query.Add_Number is not None:
            placed = position_derivation.interpolate(
                gis,
                int(query.Add_Number),
                offset_m=offset_m,
                endpoint_margin_m=endpoint_margin_m,
            )

        if placed is not None:
            interpolated.append(
                Candidate(
                    record=gis,
                    quality=_quality(value, breakdown, LocationType.INTERPOLATED_POINT),
                    position=placed.position,
                    answer_geometry=None,
                    # §11.3 — the side selects the attribute set, so the side
                    # the interpolation landed on travels with the candidate.
                    side=placed.side.side,
                )
            )
            continue

        line = position_derivation.segment_geometry(gis)
        if line is None:
            continue
        segments.append(
            Candidate(
                record=gis,
                quality=_quality(value, breakdown, LocationType.STREET_SEGMENT),
                position=None,
                answer_geometry=line,
            )
        )

    return _rank(interpolated), _rank_segments(segments, query.Add_Number)


def identify(
    query: CivicAddress,
    *,
    ssap: Sequence[SSAPRecord],
    rcl: Sequence[RCLRecord],
    score: Scorer,
    min_match_score: float,
    offset_m: float,
    endpoint_margin_m: float,
    at: Optional[datetime.datetime] = None,
) -> list[Candidate]:
    """Walk the ladder and return the winning rung's candidates, ranked.

    The winning rung is the one whose best candidate carries the highest
    blended confidence (decision 70) — see LAYER ORDER IS A LADDER above. A
    rung-1 best at or above the INTERPOLATED_POINT ceiling cannot be beaten by
    any road answer, so the RCL layer is not scored at all in that case. Ties
    go to the more precise rung.

    A query with no usable Add_Number produces no rung-1 candidates at all
    (decision 119, in ssap_candidates), so the ladder starts at rung 2 — which
    is itself empty for want of a number to interpolate — and lands on rung 3.
    The short-circuit above is therefore unreachable for such a query, which
    is the point: it was the mechanism by which a rung-1 answer nobody asked
    for suppressed the road scan that held the real one.

    Empty where no rung produced anything. §6.4 enumerates several distinct
    paths to that outcome — the layer held no record in force, none cleared
    GCS_MIN_MATCH_SCORE, every survivor was unlocatable — and all of them map
    to 468 with no way for a consumer to tell them apart (§3.6.2, §8.4). They
    are not distinguished here either, because distinguishing them would
    produce information the interface has no field to carry.
    """
    rung1 = ssap_candidates(
        query, ssap, score=score, min_match_score=min_match_score, at=at
    )
    if rung1 and rung1[0].confidence >= LocationType.INTERPOLATED_POINT.ceiling:
        return rung1

    rung2, rung3 = rcl_candidates(
        query,
        rcl,
        score=score,
        min_match_score=min_match_score,
        offset_m=offset_m,
        endpoint_margin_m=endpoint_margin_m,
        at=at,
    )
    contenders = [rung for rung in (rung1, rung2, rung3) if rung]
    if not contenders:
        return []
    return max(contenders, key=lambda rung: rung[0].confidence)


# ---------------------------------------------------------------------------
# §6.3 ambiguity
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MergedPosition:
    """§6.3's merged answer for the strict interface.

    The average of the qualifying candidates with uncertainty sized to their
    extent, per §3.7.3's minimise-maximum-error principle.

    The uncertainty is carried as a centre and a radius in metres rather than
    as a shape. Decision 57 scopes §7.4's anti-synthesis rule to single
    matches — where inventing an extent would assert precision never measured —
    and excludes the merged case, which has genuinely measured one: the answer
    is a Circle centred on the averaged position with radius equal to the
    greatest geodesic distance from that centroid to any merged candidate.
    Emitting the centre and the radius here and rendering the GeoShape in the
    wire layer keeps the separation the rest of the algorithm maintains between
    position computation and serialisation.
    """

    position: Position
    horizontal_uncertainty_m: float
    vertical_extent_m: Optional[float]
    merged_from: tuple[Candidate, ...]

    @property
    def is_merge(self) -> bool:
        return len(self.merged_from) > 1


def _segment_spread_m(candidates: Sequence[Candidate]) -> float:
    """Greatest pairwise geodesic distance between rung-3 candidates' own
    segment midpoints. 0.0 for fewer than two candidates.

    The rung-3 sibling of what `resolve_ambiguity` measures on positions: a
    segment set has no positions to average (§7.4, decision 30 — the line
    geometry IS the answer), so "how far apart do these candidates disagree"
    has to be measured on the geometries themselves. Midpoint
    (`geometry.midpoint`), not an endpoint or a centroid of every vertex, for
    the same reason decision 48 already picked it for a single segment's own
    answer position: §3.7.3's minimise-maximum-error principle bounds the
    worst case at half a segment's length, where an endpoint could be a full
    segment length off and a plain vertex-average centroid is skewed by
    however densely each segment happens to be digitised, which is a
    cartographic accident, not a signal.
    """
    if len(candidates) < 2:
        return 0.0
    midpoints = [
        geometry.midpoint(geometry.vertices_of(c.answer_geometry))
        for c in candidates
    ]
    return max(
        geometry.distance_m(a[0], a[1], b[0], b[1])
        for i, a in enumerate(midpoints)
        for b in midpoints[i + 1 :]
    )


def resolve_segment_ambiguity(
    candidates: Sequence[Candidate],
    *,
    tolerance_m: float,
) -> Candidate:
    """Appendix C.2 item 9's remaining half (`FWD-DROPPED-HNO-STRICT-001`),
    closed by the decision following 120.

    Decision 120 broke rung-3 ties by proximity of a segment's own address
    range to the query's house number — but only when the query supplies one.
    Without one, `_rank_segments` falls back to `_rank`, and every
    same-named segment ties at identical confidence and matchScore, with
    NGUID breaking the tie alphabetically and no geographic meaning at all.
    On real data (the I-94 corridor fixture this closes) that silently
    returns one of 19 segments spread roughly 7 km, indistinguishable from a
    confident single answer.

    This is that rung's version of what `resolve_ambiguity` already does for
    positioned candidates: measure the spread of the tied leaders and refuse
    to answer, rather than hand back an arbitrary pick, when they actually
    disagree. It cannot merge — there is no average of two line segments
    that means anything (§7.4, decision 30) — so it can only pick the ranked
    leader or raise `AmbiguousResult`, the same exception `resolve_ambiguity`
    raises, reused as-is rather than adding a second status code for what is
    the same failure at a different rung.

    THIS FUNCTION DOES NOT KNOW ABOUT HOUSE NUMBERS, DELIBERATELY. An early
    version of decision 121 narrowed the tier by matchScore alone before
    calling this, and that caught `FWD-DROPPED-HNO-STRICT-001` correctly but
    also caught `FWD-GAP-HNO-001` — decision 120's own fixture, HNO supplied,
    `range_gap` already narrowing it to one real segment (the 1901-1909
    block) — because rung 3's matchScore carries no house-number term, so
    matchScore alone cannot see that decision 120 already resolved that tie.
    The fix is not to make this function HNO-aware; it is for the CALLER
    (`response_assembly.strict_answer`) to narrow `candidates` on the same
    key `_rank_segments` ranks by — matchScore, then `range_gap` where a
    house number is available — before calling this, so what arrives here
    already excludes anyone `_rank_segments` itself distinguished. This
    function only ever answers one question about whatever set it is
    actually handed: do these still-tied leaders sit close enough together
    to be one answer.

    `tolerance_m` is `GCS_AMBIGUITY_TOLERANCE_M`, the same knob
    `resolve_ambiguity` uses, deliberately not a second tuning value: "are
    these tied candidates actually the same answer" is one question asked at
    two rungs, not two questions.

    Returns `candidates[0]` unchanged for fewer than two candidates — nothing
    to be ambiguous about. Otherwise returns `candidates[0]` (already ranked
    by `_rank_segments`, so the leader by construction) when the spread is
    within tolerance, and raises `AmbiguousResult` when it is not.
    """
    if len(candidates) < 2:
        return candidates[0]

    spread_m = _segment_spread_m(candidates)
    if spread_m > tolerance_m:
        raise AmbiguousResult(spread_m, tolerance_m, len(candidates))
    return candidates[0]


def resolve_ambiguity(
    candidates: Sequence[Candidate],
    *,
    tolerance_m: float,
) -> MergedPosition:
    """Apply §6.3 to a set of same-rung candidates.

    The test is geometric, not combinatorial. Candidates that agree
    horizontally and differ vertically merge unconditionally, with the vertical
    uncertainty spanning the extent — the extent is the answer. Candidates that
    differ horizontally beyond GCS_AMBIGUITY_TOLERANCE_M raise, which the
    caller turns into 468.

    Only positioned candidates take part. A rung-3 set has no positions to
    average and never reaches here: the segment geometry is its own answer.

    `tolerance_m` has no specification-level default and is required
    configuration (decision 54) — the value is deployment-specific and comes
    from .env, so this function is handed it rather than reading it.

    This function does not decide WHICH candidates take part — it applies
    §6.3 to whatever set it is handed. `strict_answer`
    (src/geocode/response_assembly.py) is the caller that narrows the set to
    the top-scoring tier before calling this (decision 118); a caller that
    hands this every admitted candidate regardless of score gets the older,
    wider test back, which is why that narrowing lives one layer up rather
    than here.
    """
    positioned = [c for c in candidates if c.position is not None]
    if not positioned:
        raise ValueError("no positioned candidates to resolve")

    points = [(c.position.longitude, c.position.latitude) for c in positioned]
    centre = geometry.mean_position(points)
    spread_m = geometry.max_distance_from_m(centre, points)

    if len(positioned) > 1 and spread_m > tolerance_m:
        raise AmbiguousResult(spread_m, tolerance_m, len(positioned))

    heights = [c.position.altitude for c in positioned if c.position.altitude is not None]
    vertical_extent_m = (max(heights) - min(heights)) if len(heights) > 1 else None

    # §3.7.3 vertically as well as horizontally: the midpoint of the surviving
    # heights bounds the worst case at half the extent, where naming the lowest
    # would put a responder the full extent out.
    altitude: Optional[float] = None
    if heights:
        altitude = (max(heights) + min(heights)) / 2.0 if len(heights) > 1 else heights[0]

    return MergedPosition(
        position=Position(longitude=centre[0], latitude=centre[1], altitude=altitude),
        horizontal_uncertainty_m=spread_m,
        vertical_extent_m=vertical_extent_m,
        merged_from=tuple(positioned),
    )
