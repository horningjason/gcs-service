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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from shapely.geometry import Point

from src.engine.models import CRS_2D, Candidate, LocationType, MatchQuality, Position
from src.geocode.candidates import MergedPosition, resolve_ambiguity


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


def strict_answer(
    candidates: Sequence[Candidate],
    *,
    tolerance_m: float,
) -> Optional[ForwardAnswer]:
    """The single answer the i3 interface returns (§8.1).

    Rank 1, except where §6.3's merge applies: a generic query resolving to
    several distinct structures on one parcel returns their average with
    uncertainty sized to their extent, because pidfLoGeo carries one geodetic
    location and picking one structure arbitrarily would assert more than the
    data supports (decision 27).

    Raises AmbiguousResult where the candidates disagree horizontally beyond
    tolerance; the caller maps that to 468. Returns None where there are no
    candidates at all, which is the same 468 by a different §6.4 path.

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
        return answer_for(candidates[0])

    merged: MergedPosition = resolve_ambiguity(positioned, tolerance_m=tolerance_m)
    best = positioned[0]

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
