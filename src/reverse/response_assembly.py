"""§12 — assembling the reverse answer.

One civic address on the strict interface, the ordered candidate list on the
enhanced one. The asymmetry between them is the whole of §12.1: the strict
CivicAddress object carries a single pidfLoAddress and nothing else — no rank,
no score, no distance, no containment flag, no Placement Method, and no
indication that a house number was interpolated rather than read. Everything
§10 and §11 computed is discarded at that boundary. That is the deficiency,
carried faithfully.

Status codes follow §12.3, mirroring §8.4 with the reverse-side triggers. This
module distinguishes only the two outcomes it can see — an answer, or nothing
within GCS_REVERSE_SEARCH_RADIUS_M, which is 468. Referral (307) and schema
failure (454) are decided above it.

As on the forward side, this stops short of the wire. Turning a CivicAddress
into a PIDF-LO document belongs to src/api/wire/civic_xml.py; §11.4's
omit-rather-than-emit-empty rule serialises from CivicAddress.populated().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from src.engine.models import (
    Candidate,
    CivicAddress,
    LocationType,
    MatchQuality,
    Position,
)
from src.reverse import civic_derivation
from src.reverse.origin import SearchOrigin
from src.reverse.search import Hit, SpatialScorer, to_candidates


@dataclass(frozen=True, slots=True)
class ReverseAnswer:
    """One derived civic address with everything the enhanced interface needs.

    The strict interface reads `civic` and drops the rest.
    """

    civic: CivicAddress
    quality: MatchQuality

    #: §10.5's raw geodesic distance from the origin, in metres. Travels on the
    #: enhanced interface so a caller can see how close the call was — the
    #: disclosure that pays for §10.5's uncorrected centerline bias.
    distance_m: float

    #: §10.3's containment flag. Invisible on the i3 interface, as everything
    #: else is.
    contained: bool = False

    #: True where §11.2 computed the house number rather than reading it.
    house_number_synthesised: bool = False

    #: STA-006.3 §6.1 Placement Method, where the matched record carries one.
    #: §10.5 argues for surfacing it rather than adjusting the ordering by it:
    #: a Parcel centroid, a Structure point and a PropertyAccess driveway are
    #: not interchangeable measurements, and the caller should weigh that.
    placement: Optional[str] = None

    #: Where the matched feature is — the address point itself, or the point the
    #: origin projected onto for a centerline. Carried for §12.2, which returns
    #: the full matched record "civic and geodetic together" rather than a bare
    #: address; the strict interface drops it with everything else (§12.1).
    position: Optional[Position] = None

    @property
    def location_type(self) -> LocationType:
        return self.quality.location_type

    @property
    def confidence(self) -> float:
        return self.quality.confidence

    @property
    def match_type(self) -> str:
        """The i3 §10.31 registry token (§12.2).

        Only two of the seven are usable: Address for every point-tier match,
        RoadCenterline for every road-tier one. Hybrid is not emitted since one
        candidate matches exactly one feature, and CoverageRegion is
        LoST-specific and out of scope per §3.1.

        The registry is materially coarser than locationType — RoadCenterline
        covers both a street-level match and a house number interpolated from a
        range without distinguishing them, and no token exists for an interior
        or volumetric match at all. Both fields travel: the token for consumers
        that speak i3 vocabulary, locationType for those that need the
        distinction i3 cannot express (§16).
        """
        if self.quality.location_type in (
            LocationType.ADDRESS_POINT,
            LocationType.FOOTPRINT_2D,
            LocationType.SPACE_3D,
        ):
            return "Address"
        return "RoadCenterline"


def _answer_from(candidate: Candidate, hit: Hit, *, endpoint_margin_m: float) -> Optional[ReverseAnswer]:
    derived = civic_derivation.derive(hit, endpoint_margin_m=endpoint_margin_m)
    if derived is None:
        return None

    # Decision 59: the search tiered every centerline INTERPOLATED_POINT for
    # ordering, because the true tier is not knowable until §11.2 has projected
    # and read the ranges. Where the projected side asserts none, the answer is
    # STREET_SEGMENT and the tier is corrected downward here — the reported tier
    # is §11.2's, and it is permitted to differ from the one the candidate was
    # ordered on rather than left claiming a precision the answer lacks.
    quality = candidate.quality
    if derived.tier is not quality.location_type:
        quality = MatchQuality(
            match_score=quality.match_score,
            location_type=derived.tier,
            field_scores=quality.field_scores,
        )

    return ReverseAnswer(
        civic=derived.civic,
        quality=quality,
        distance_m=hit.distance_m,
        contained=hit.contained,
        house_number_synthesised=derived.house_number_synthesised,
        placement=getattr(hit.record, "placement", None),
        position=_matched_position(hit),
    )


def _matched_position(hit: Hit) -> Optional[Position]:
    """Where the match is, for §12.2's geodetic half.

    An address point supplies its own position. A centerline supplies the point
    the origin projected onto — which is the location the derived house number
    describes, and the only position the reverse direction ever computed for it.
    No setback is applied: §7.3's offset exists to keep a FORWARD answer off the
    carriageway, whereas here the projection is a statement about where on the
    segment the query fell, and moving it would misreport that.
    """
    position = getattr(hit.record, "position", None)
    if position is not None:
        return position
    if hit.projection is not None:
        return Position(
            longitude=hit.projection.longitude,
            latitude=hit.projection.latitude,
        )
    return None


def answers(
    origin: SearchOrigin,
    hits: Sequence[Hit],
    *,
    score: SpatialScorer,
    endpoint_margin_m: float,
) -> list[ReverseAnswer]:
    """The ordered candidate list for the enhanced interface (§12.2).

    §10.3's order is preserved exactly — the scorer decorates, it does not
    re-rank. A hit whose civic address cannot be derived at all is dropped
    rather than returned empty, which is distinct from §11.4's sparse-record
    case: a sparse record still has fields to report, whereas this one produced
    nothing to report.
    """
    candidates = to_candidates(origin, hits, score=score)
    out: list[ReverseAnswer] = []
    for candidate, hit in zip(candidates, hits):
        answer = _answer_from(candidate, hit, endpoint_margin_m=endpoint_margin_m)
        if answer is not None:
            out.append(answer)
    return out


def strict_answer(
    origin: SearchOrigin,
    hits: Sequence[Hit],
    *,
    score: SpatialScorer,
    endpoint_margin_m: float,
) -> Optional[ReverseAnswer]:
    """The single civic address the i3 interface returns (§12.1).

    Rank 1 of the same ordered list, which is what makes the two interfaces a
    controlled comparison (§2.2). None where nothing fell within the radius —
    §12.3's 468, which is also what an empty hit list means by any other route.

    There is no averaging here and no counterpart to §6.3's merge: §10.4 is
    explicit that unlike the Geocode side there is no averaging a set of civic
    addresses, so one candidate must be elected rather than synthesised.
    """
    listed = answers(origin, hits, score=score, endpoint_margin_m=endpoint_margin_m)
    return listed[0] if listed else None
