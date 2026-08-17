"""§10 — nearest-feature search.

The whole chapter is a recommended best practice. i3 §4.5 refers to "the
'nearest' point algorithm employed" as though it were a defined thing; it is
not defined in i3, in STA-006.3, or in any referenced RFC.

ONE PASS (§10.1, decision 39)

A single proximity search from the §9 origin out to GCS_REVERSE_SEARCH_RADIUS_M
produces one candidate set, which is then ordered. There is no separate
containment pass and no separate 3D pass: both are terms in the ordering rather
than gates in front of it, because a two-pass structure lets the second pass
readmit what the first rejected — the same reasoning decision 28 applied to
scoring.

ORDERING IS LEXICOGRAPHIC, NEVER BLENDED (§10.3, decision 41)

    containment  →  precision tier  →  distance  →  NGUID

Nothing is combined into a single number, so distance is a tiebreaker within a
tier and never a competitor to it. This is the same discipline the three-field
quality model exists to enforce: mixing axes produces an ordering nobody can
account for.

Tier precedence is scoped to CONTAINED candidates. A Point input has no area
and contains nothing, so the commonest input in the system never reaches the
containment rule and orders by pure proximity — which is correct: a coordinate
200 m from an address point and 5 m from a centerline is on the road, and the
honest answer is the segment's interpolated address, not the distant structure.
Layer precedence is a consequence of containment rather than an independent
rule. Containment is what licenses preferring precision; absent it, proximity
is all that is known.

DISTANCE IS MEASURED TO GEOMETRY AS IT EXISTS (§10.5, decision 42)

No synthetic adjustment is applied to any layer. Distance to a centerline is
perpendicular distance to the centerline, and a road is not its centerline — so
someone at the curb of a twelve-metre road is six metres from the centerline
and zero metres from the road, and the comparison favours address points by
roughly half a carriageway width in exactly the marginal cases where distance
decides. Subtracting a nominal half-width was rejected: it would require
inventing a road width STA-006.3 does not model. The bias is disclosed instead
— raw distances travel on the enhanced interface so a caller can see how close
the call was.

VERTICAL PARTICIPATION IS LEXICOGRAPHIC TOO (§10.5)

Candidates whose vertical extent contains the input's Z band ahead of those
whose extent does not; horizontal distance orders within a band. Never
Euclidean: sqrt(h² + (k·v)²) was rejected for want of a defensible k, because
three metres up is a different dwelling while three metres sideways is nothing.

The band is scoped to classes that carry a vertical extent, and decision 60
records that no provisioned class does — so it is inert today, by design rather
than by oversight, and retained as structure for the volumetric classes §7.4
anticipates.

WHERE SCORING COMES FROM

Injected, exactly as §6.5's is on the forward side. §10.6 settles the shape of
the spatial-fit score; the components are now written (decisions 66 and 83,
implemented in src/engine/scoring.py's make_reverse_scorer and registered at
startup). This module orders candidates; it does not score them, and it never
lets a score disturb the ordering.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Protocol, Sequence

from src.discrepancy.discrepancy_report import GISProblem, ProblemSeverity, fire_gis_dr
from src.engine import geometry
from src.engine.models import (
    Candidate,
    DataQualityFlag,
    LocationType,
    MatchQuality,
    RclGisRecord,
    SsapGisRecord,
)
from src.gis.records import RCLRecord, SSAPRecord
from src.reverse.origin import SearchOrigin


class SpatialScorer(Protocol):
    """§10.6's spatial-fit score, filling the matchScore slot.

    Same field, same 0-100 range, and the same per-component breakdown shape
    the forward side uses — only the components differ, because a reverse
    request has no query address to decompose into street, HNO and community.
    """

    def __call__(self, origin: SearchOrigin, hit: "Hit") -> tuple[float, Mapping[str, float]]:
        ...


@dataclass(frozen=True, slots=True)
class Hit:
    """One feature within the radius, with everything the ordering needs.

    Kept separate from Candidate because these are the SPATIAL facts — they
    order the list — while Candidate carries the quality model that describes
    it. §10.6 is explicit that extent damps the score and must not disturb the
    ordering, and keeping the two in different objects is how that stays true.
    """

    record: SsapGisRecord | RclGisRecord
    distance_m: float
    contained: bool
    tier: LocationType

    #: True where the candidate's vertical extent contains the input's Z.
    #: Bands ahead of False in the ordering (§10.5).
    vertically_banded: bool = False

    #: Where the origin projected onto a centerline. None for a point feature.
    #: §11.2 inverts from this rather than reprojecting.
    projection: Optional[geometry.Projection] = None

    @property
    def nguid(self) -> Optional[str]:
        return self.record.nguid

    @property
    def is_tie_breakable(self) -> bool:
        """R3 — a null NGUID makes a record ineligible for §10.4's
        deterministic ordering. Reported via the discrepancy path, never
        replaced with a local surrogate."""
        return self.record.is_tie_breakable


def ordering_key(hit: Hit) -> tuple:
    """§10.3 / §10.4's lexicographic sequence, as a sort key.

    Containment first — but tier is consulted ONLY for contained candidates,
    so an uncontained set (every Point input) collapses to pure distance. That
    scoping is the whole of §10.3's "tier, and what governs when containment
    cannot fire", and writing it as a constant for uncontained hits is what
    keeps a nearer centerline ahead of a distant address point.
    """
    return (
        not hit.contained,                       # contained first
        not hit.vertically_banded,               # Z-containing band first
        -hit.tier.precision if hit.contained else 0,   # tier, contained only
        hit.distance_m,
        hit.nguid or "",                         # §10.4, ascending
    )


def order(hits: Iterable[Hit]) -> list[Hit]:
    return sorted(hits, key=ordering_key)


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def _vertically_bands(origin: SearchOrigin, altitude: Optional[float]) -> bool:
    """Whether a candidate's vertical extent contains the input's Z (§10.5).

    A candidate has to HAVE a vertical extent for this to fire, and decision 60
    records that no provisioned class does: SSAP carries a point Z, which is a
    slot rather than a range, and no volumetric feature class exists (§7.4 as
    corrected in Session 4). So this returns True only on exact equality, which
    is not a case the provisioned data produces, and the ordering degrades to
    pure horizontal distance in every real case — the normal path §3.7.2
    predicts.

    That is an inert branch rather than a defect, and it is kept because the
    volumetric classes §7.4 anticipates would exercise it unchanged. Widening
    it to fire on near-misses would need a vertical tolerance, which is exactly
    the constant §10.5 declined when it rejected sqrt(h² + (k·v)²): no
    defensible default can be supplied from data that barely exists.
    """
    if origin.altitude is None or altitude is None:
        return False
    return altitude == origin.altitude


def ssap_hits(
    origin: SearchOrigin,
    records: Iterable[SSAPRecord],
    *,
    radius_m: float,
) -> list[Hit]:
    """Address points within the radius."""
    ssap_layer = os.environ.get("GCS_SSAP_LAYER", "SiteStructureAddressPoint")
    out: list[Hit] = []
    for record in records:
        gis = SsapGisRecord.from_record(record)
        if gis.has_flag(DataQualityFlag.NGUID_MISSING):
            fire_gis_dr(GISProblem.OmittedField, ProblemSeverity.Minor,
                        detail="NGUID", layer_ids=ssap_layer)
        if gis.has_flag(DataQualityFlag.NO_GEOMETRY):
            fire_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate,
                        detail="no usable geometry", layer_ids=ssap_layer)
        if not gis.is_located or gis.position is None:
            continue
        distance = geometry.distance_m(
            origin.longitude, origin.latitude,
            gis.position.longitude, gis.position.latitude,
        )
        if distance > radius_m:
            continue
        contained = (
            origin.shape is not None
            and origin.shape.contains(
                gis.position.longitude, gis.position.latitude, gis.position.altitude
            )
        )
        out.append(
            Hit(
                record=gis,
                distance_m=distance,
                contained=contained,
                tier=LocationType.ADDRESS_POINT,
                vertically_banded=_vertically_bands(origin, gis.position.altitude),
            )
        )
    return out


def rcl_hits(
    origin: SearchOrigin,
    records: Iterable[RCLRecord],
    *,
    radius_m: float,
) -> list[Hit]:
    """Centerlines within the radius, measured perpendicular to the geometry.

    Every centerline tiers uniformly as INTERPOLATED_POINT here, whether or not
    the projected side turns out to assert an address range (decision 59). The
    search does not resolve side or ranges in order to tier: a centerline's true
    tier is not knowable without projecting the origin, selecting the side and
    reading the ranges, which is §11's work, and pulling that forward would
    collapse §11.2's front half into §10 and contradict §10.1's one pass.

    The sanctioned consequence is that the tier ordered on and the tier reported
    can differ — see response_assembly, which corrects downward once §11.2 knows.
    Within a contained group that means a rangeless segment may have outranked
    an interpolable one. The exposure is bounded: tier participates only among
    contained candidates, so no Point input is affected, and a Point input is
    the common case.
    """
    rcl_layer = os.environ.get("GCS_RCL_LAYER", "RoadCenterLine")
    out: list[Hit] = []
    for record in records:
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
        if not gis.is_located or gis.is_multipart:
            continue
        try:
            vertices = geometry.vertices_of(gis.geometry)
        except ValueError:
            continue

        projection = geometry.project_onto_path(vertices, origin.longitude, origin.latitude)
        if projection.offset_m > radius_m:
            continue
        contained = (
            origin.shape is not None
            and origin.shape.contains(projection.longitude, projection.latitude, None)
        )
        out.append(
            Hit(
                record=gis,
                distance_m=projection.offset_m,
                contained=contained,
                tier=LocationType.INTERPOLATED_POINT,
                projection=projection,
            )
        )
    return out


def search(
    origin: SearchOrigin,
    *,
    ssap: Sequence[SSAPRecord],
    rcl: Sequence[RCLRecord],
    radius_m: float,
) -> list[Hit]:
    """One pass over both layers, ordered by §10.3.

    Empty where nothing falls within GCS_REVERSE_SEARCH_RADIUS_M, which is
    §12.3's 468. The radius is mandatory for a reason worth restating: without
    one, a point in open water reverse-geocodes to whatever unfortunate address
    is nearest and returns 200.
    """
    return order(
        ssap_hits(origin, ssap, radius_m=radius_m)
        + rcl_hits(origin, rcl, radius_m=radius_m)
    )


def to_candidates(
    origin: SearchOrigin,
    hits: Sequence[Hit],
    *,
    score: SpatialScorer,
) -> list[Candidate]:
    """Attach §10.6's quality model, preserving §10.3's order exactly.

    The list is NOT re-sorted by score. §10.6 argues the point at length:
    extent damps the score and must not weaken containment in the ordering, and
    the two stay separable only because the ordering is lexicographic and the
    score is advisory. A sort here would silently undo that.
    """
    out: list[Candidate] = []
    for hit in hits:
        value, breakdown = score(origin, hit)
        position = getattr(hit.record, "position", None)
        out.append(
            Candidate(
                record=hit.record,
                quality=MatchQuality(
                    match_score=value,
                    location_type=hit.tier,
                    field_scores=dict(breakdown),
                ),
                position=position,
                distance_m=hit.distance_m,
            )
        )
    return out
