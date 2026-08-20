"""§8 — assembling the forward answer from identified candidates.

GEOMETRY IS THE ANSWER (§7.4, decision 30)

The matched feature's actual geometry is returned, rather than a synthesised
uncertainty shape around a point:

    rung 1  the address point                    Point
    rung 2  the interpolated, offset position    Point
    rung 3  the segment's own line               LineString

Rung 3 is the load-bearing case. There is no basis to collapse a street-level
match to one position, so the line itself is returned — it is the honest
representation of what is known, and it is its own uncertainty signal. No
Circle, no Ellipse, nothing invented to make the answer look like the other two.

WHERE THIS MODULE STOPS

It produces the structured answer, not the wire bytes. PIDF-LO construction —
the RFC 3863 envelope, the entity echo or HELD-style unlinked pseudonym, the
GML subset, coordinate ordering, the RFC 7459 confidence element (§8.3,
decisions 12 and 33) — belongs to src/api/wire/. Keeping the split means
§8.1's deliberate impoverishment of the strict interface happens once, here,
where it can be seen and tested, rather than being spread through a
serialiser.

THE TWO INTERFACES DIVERGE HERE AND ONLY HERE (§2.2, §2.3, decision 8)

One engine produced the ranked list. `strict_answer` takes rank 1 — or §6.3's
merge — and discards everything §4.5 has no field for: score, rank, match type,
Placement Method, and any indication the match was fuzzy. `enhanced_answers`
returns the list intact. Rank 1 is provably the same on both, because
GCS_MIN_MATCH_SCORE floored admission upstream in §6, so neither interface sees
a candidate the other does not.

§6.3's MERGE/AMBIGUITY TEST RUNS ON THE TOP-SCORING TIER, NOT ON EVERY
ADMITTED CANDIDATE (decision 118)

`GCS_MIN_MATCH_SCORE` answers one question — is this candidate plausible
enough to admit at all — and `strict_answer` used to also treat "admitted" as
"in contention for the single answer," running §6.3's spread test across
every candidate that cleared the floor regardless of how far it trailed the
leader. On real data that let a candidate matching only on house number and
street name (e.g. `St_Type`/`Community` both zeroed) survive alongside two
genuinely co-located, fully-matching candidates a few metres apart, and
having all three compete for §6.3's merge blew the horizontal spread past
`GCS_AMBIGUITY_TOLERANCE_M` for a query that was not actually ambiguous at
all — the two real candidates would have merged cleanly on their own.

`strict_answer` now narrows to the TOP-SCORING TIER — candidates within
`_TOP_SCORE_TIE_EPSILON` of the best `matchScore` in the (already same-rung)
set — before running `resolve_ambiguity`. Only that tier competes for the
single answer; everyone else that cleared the floor still appears on
`GeocodeEnhanced` unchanged, since `enhanced_answers` never calls this
function at all. The epsilon is a float-noise guard, not a deployment
tuning knob — see its own docstring for why it is not an environment
variable.

RUNG 3's TIER NARROWS ON THE SAME KEY IT RANKS BY, NOT MATCHSCORE ALONE
(decision 121, Appendix C.2 item 9's remaining half)

Rung 3's matchScore carries no house-number term (§6 — interpolation already
failed for every segment candidate, by definition), so every segment sharing
a street name ties on matchScore whether or not the query supplied a house
number at all. Narrowing the rung-3 tier by matchScore alone — the same
recipe the positioned branch above uses — therefore cannot tell
`FWD-GAP-HNO-001` (an HNO supplied, `candidates.range_gap` already narrowing
`_rank_segments`'s own ordering down to one real segment, decision 120) apart
from `FWD-DROPPED-HNO-STRICT-001` (no HNO, nothing narrows the ordering at
all, decision 121): both are members of the same wide matchScore tie, and a
matchScore-only tier would run `resolve_segment_ambiguity` on the *whole*
tie in both cases, reverting decision 120's already-settled pick. The
rung-3 branch of `strict_answer` therefore narrows twice: first by
matchScore (as above), then — only where the query supplied a house number —
by `range_gap` within that same tier, the identical key `_rank_segments`
itself sorts by. Where `range_gap` already distinguishes a unique leader (the
ordinary case once a real house number is involved), the ambiguity check
never fires and decision 120's pick stands untouched; where it does not — no
house number at all, or a genuine tie in `range_gap` itself (an HNO sitting
exactly on the boundary between two ranges kilometres apart) — the wider tier
survives to the spread test, exactly as intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from shapely.geometry import Point

from src.engine.models import CRS_2D, Candidate, LocationType, MatchQuality, Position
from src.geocode.candidates import (
    MergedPosition,
    range_gap,
    resolve_ambiguity,
    resolve_segment_ambiguity,
)


@dataclass(frozen=True, slots=True)
class ForwardAnswer:
    """One derived answer, ready for serialisation.

    `geometry` is what §7.4 returns: a Point at the two point rungs, the
    segment's LineString at STREET_SEGMENT.
    """

    geometry: object
    quality: MatchQuality
    position: Optional[Position] = None

    #: §6.3's extent where candidates merged, in metres. None for a single
    #: match — §7.4 does not synthesise an uncertainty around one matched
    #: geometry, and the geometry is the uncertainty statement.
    horizontal_uncertainty_m: Optional[float] = None
    vertical_extent_m: Optional[float] = None

    #: How many candidates the returned position averages. One for an
    #: unmerged answer.
    merged_count: int = 1

    @property
    def location_type(self) -> LocationType:
        return self.quality.location_type

    @property
    def confidence(self) -> float:
        return self.quality.confidence

    @property
    def crs(self) -> str:
        """The CRS of the answer, positional or line.

        A positional answer follows decision 55: EPSG:4979 where the geometry's
        Z was admitted, EPSG:4326 where it was not. A rung-3 line answer is
        EPSG:4326 (decision 85, resolving Appendix C.4 Q22) — the RoadCenterLine
        layer's per-vertex Z is a GeoPackage export artifact rather than
        declared attribution (§10.5), so it is never consulted and every
        RCL-derived answer is 2D regardless of rung. As before, this follows
        Candidate.crs rather than re-deciding anything here.
        """
        return CRS_2D if self.position is None else self.position.crs

    @property
    def is_line_answer(self) -> bool:
        return self.position is None


def _point_of(position: Position) -> Point:
    """A Point in the geometry's own dimensionality.

    Two-dimensional where no Z was admitted, so the answer's shape agrees with
    the CRS it reports rather than carrying a zero the CRS then contradicts.
    Coordinate ORDER here is (x, y) because that is what shapely means; RFC
    5491 / GML serialise lat lon, which is the wire layer's transform (§7.1).
    """
    if position.altitude is None:
        return Point(position.longitude, position.latitude)
    return Point(position.longitude, position.latitude, position.altitude)


def answer_for(candidate: Candidate) -> ForwardAnswer:
    """The answer a single candidate produces, by its tier."""
    if candidate.position is not None:
        return ForwardAnswer(
            geometry=_point_of(candidate.position),
            quality=candidate.quality,
            position=candidate.position,
        )

    # Rung 3 — the segment itself. Nothing is derived from it, on purpose.
    return ForwardAnswer(
        geometry=candidate.answer_geometry,
        quality=candidate.quality,
        position=None,
    )


#: Decision 118. Two candidates count as tied for the top matchScore if they
#: differ by less than this. NOT a deployment tuning knob — no .env binding,
#: deliberately — this exists to absorb floating-point noise, not to encode
#: an editorial judgment about "close enough." `src/engine/scoring.py`'s
#: `_weighted_average()` already documents the mechanism this guards against:
#: float summation across several weighted terms is not associative, so an
#: all-1.0 match can land a few ulps off 100.0 depending on term order (found
#: on real data, a rung-2 interpolation case — see that function's docstring).
#: 1e-6 is many orders of magnitude past that noise floor and many orders of
#: magnitude short of any editorially meaningful score difference, so it
#: only ever catches candidates that are genuinely the same match by any
#: real-world reading, never two candidates a human would call "close."
_TOP_SCORE_TIE_EPSILON = 1e-6


def strict_answer(
    candidates: Sequence[Candidate],
    *,
    tolerance_m: float,
    house_number: Optional[int] = None,
) -> Optional[ForwardAnswer]:
    """The single answer the i3 interface returns (§8.1).

    Rank 1, except where §6.3's merge applies: a generic query resolving to
    several distinct structures on one parcel returns their average with
    uncertainty sized to their extent, because pidfLoGeo carries one geodetic
    location and picking one structure arbitrarily would assert more than the
    data supports (decision 27).

    §6.3's spread test runs only within the TOP-SCORING TIER of `candidates`
    — those within `_TOP_SCORE_TIE_EPSILON` of the best matchScore — not
    across every candidate that merely cleared GCS_MIN_MATCH_SCORE upstream
    (decision 118). A candidate that is merely admissible but trails the
    leader never gets to veto a real, tightly-clustered merge among the
    genuine top matches; it still appears on GeocodeEnhanced, which calls
    neither this function nor `resolve_ambiguity` and is therefore
    unaffected by this narrowing.

    Raises AmbiguousResult where the top-tier candidates disagree
    horizontally beyond tolerance; the caller maps that to 468. The same is
    now true at rung 3 (Appendix C.2 item 9's remaining half, decision 121):
    `resolve_segment_ambiguity` applies the same top-tier-then-spread test to
    segment geometries instead of positions, rather than silently handing
    back one of an arbitrarily tied set. `house_number` — the query's
    Add_Number, threaded through by the only caller that has it
    (src/api/conversion.py) — narrows the rung-3 tier a second time, by
    `range_gap`, before the spread test runs; see the module docstring's
    "RUNG 3's TIER NARROWS ON THE SAME KEY IT RANKS BY" section for why
    matchScore alone is not enough to keep decision 120's already-settled
    picks (`FWD-GAP-HNO-001`) from being reopened by decision 121's spread
    test. `house_number` plays no part on the positioned branch — rungs 1
    and 2 already resolved house-number identity or containment before a
    candidate could reach here (decisions 69 and §7.2's range/parity test),
    so there is nothing left for it to narrow there. Returns None where
    there are no candidates at all, which is the same 468 by a different
    §6.4 path.

    What this drops is the point of §8.1 and not an oversight: a fuzzy match
    returns 200 and a coordinate byte-for-byte indistinguishable from an exact
    match. §4.5 gives the interface no field to say otherwise, and inventing
    one would breach §1.2.1. The deficiency is carried faithfully and recorded
    in §16.
    """
    if not candidates:
        return None

    positioned = [c for c in candidates if c.position is not None]
    if not positioned:
        # Rung 3 — a line answer. §6.3's geometric merge has no positions to
        # average, and averaging segment geometries is not a thing §7.4 does.
        # Same top-tier narrowing as the positioned branch below (decision
        # 118) first; candidates is already ranked by _rank_segments, so
        # candidates[0] is the leader by construction.
        top_score = candidates[0].quality.match_score
        contending = [
            c for c in candidates
            if top_score - c.quality.match_score <= _TOP_SCORE_TIE_EPSILON
        ]
        # Decision 121 — narrow a second time by range_gap, the SAME key
        # _rank_segments itself sorts by, but only where there is a house
        # number to measure a gap against. Skipping this when house_number
        # is None is not an oversight: with no house number, range_gap has
        # nothing to compute either (candidates.range_gap requires one), and
        # this is exactly FWD-DROPPED-HNO-STRICT-001's shape, where the
        # matchScore tier IS the whole ambiguity — nothing else distinguishes
        # these candidates, so nothing else should narrow them further.
        if house_number is not None and len(contending) > 1:
            gaps = [range_gap(c.record, house_number) for c in contending]
            min_gap = min(gaps)
            contending = [
                c for c, gap in zip(contending, gaps)
                if gap - min_gap <= _TOP_SCORE_TIE_EPSILON
            ]
        return answer_for(
            resolve_segment_ambiguity(contending, tolerance_m=tolerance_m)
        )

    # positioned is already ranked (best first, see src/geocode/candidates.py
    # _rank()), so positioned[0] is the leader by construction.
    top_score = positioned[0].quality.match_score
    contending = [
        c for c in positioned
        if top_score - c.quality.match_score <= _TOP_SCORE_TIE_EPSILON
    ]

    merged: MergedPosition = resolve_ambiguity(contending, tolerance_m=tolerance_m)
    best = contending[0]

    if not merged.is_merge:
        return answer_for(best)

    return ForwardAnswer(
        geometry=_point_of(merged.position),
        quality=best.quality,
        position=merged.position,
        horizontal_uncertainty_m=merged.horizontal_uncertainty_m,
        vertical_extent_m=merged.vertical_extent_m,
        merged_count=len(merged.merged_from),
    )


def enhanced_answers(candidates: Sequence[Candidate]) -> list[ForwardAnswer]:
    """Every candidate, ranked, for the i3-improved interface (§8.2).

    No merge and no averaging: the honest answer to an underspecified query is
    a real candidate list, not a synthetic blended point (decision 27). The
    ranking is already §7.4's blended-confidence order, applied in §6.
    """
    return [answer_for(c) for c in candidates]
