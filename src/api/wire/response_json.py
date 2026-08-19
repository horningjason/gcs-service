"""§3.9.2 — the enhanced candidate schema.

The strict interface's 200 wrapper (`GeodeticData`/`CivicAddress`) used to be
built here as a JSON object, on the reasoning that the normative YAML's
declared `application/xml` content type couldn't hold its own declared
object-with-a-string-property schema. That reasoning is superseded (decision
116, Session 14): OpenAPI 3.0's own default XML serialization — an object's
properties become child elements named after the property, with no `xml:`
annotation required — makes `application/xml` and the declared schema hold
together after all. `src/api/wire/strict_xml.py` builds that response now;
this module is enhanced-only.

THE ENHANCED SCHEMA IS RECONCILED AND NORMATIVE (decision 92)

`references/i3-geocode-conversion-enhanced.yaml` exists, was reconciled
against this module in Session 9, and is the normative spelling of the
enhanced wire format — this module is expected to match it, not the other
way round. Decision 92 records the reconciliation and every naming
divergence it resolved. Appendix C item (c) is closed. The enhanced
interface is GCS's own additive, non-normative schema (§2.2), so decision
116 does not touch it: `candidates[]` stays JSON, unaffected.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from src.api.wire.civic_xml import DroppedElement
from src.engine.models import LocationType

# ---------------------------------------------------------------------------
# The enhanced schema (§3.9.2, §8.2, §12.2)
# ---------------------------------------------------------------------------

def match_type(location_type: LocationType) -> str:
    """The i3 §10.31 registry token for a tier (§12.2).

    Only two of the seven tokens are usable. Address covers every point-tier
    match, RoadCenterline every road-tier one. Hybrid is not emitted because one
    candidate matches exactly one feature, and CoverageRegion is LoST-specific
    and out of scope (§3.1).

    The registry is materially coarser than locationType — RoadCenterline covers
    both a street-level match and a house number interpolated from a range,
    without distinguishing them, and no token exists for an interior or
    volumetric match at all. Both fields travel: the token for consumers that
    speak i3 vocabulary, locationType for those that need the distinction i3
    cannot express (§16).
    """
    if location_type in (
        LocationType.ADDRESS_POINT,
        LocationType.FOOTPRINT_2D,
        LocationType.SPACE_3D,
    ):
        return "Address"
    return "RoadCenterline"


def _quality_fields(
    *,
    match_score: float,
    location_type: LocationType,
    confidence: float,
    field_scores: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """§7.4's three-field model, in one shape for both directions.

    matchScore and locationType are orthogonal and both travel so a consumer can
    re-rank on either: matchScore answers "did we find the right record",
    locationType answers "how precisely does that record locate anything".
    confidence is derived from the two and never stored independently.
    """
    out: dict[str, Any] = {
        "matchScore": round(match_score, 3),
        "locationType": location_type.value,
        "confidence": round(confidence, 3),
        "matchType": match_type(location_type),
    }
    if field_scores:
        out["matchScoreBreakdown"] = {
            name: round(value, 3) for name, value in field_scores.items()
        }
    return out


def forward_candidate(answer, pidf_lo: str) -> dict[str, Any]:
    """One /GeocodeEnhanced candidate (§8.2).

    `pidfLo` is the full matched record — civic and geodetic together, not a
    bare geometry — so a client that queried "101 Main St" and matched
    "101 Mayne St" can see the substitution by diffing the record against its
    query (decision 11).
    """
    entry: dict[str, Any] = {"pidfLo": pidf_lo}
    entry.update(
        _quality_fields(
            match_score=answer.quality.match_score,
            location_type=answer.location_type,
            confidence=answer.confidence,
            field_scores=dict(answer.quality.field_scores),
        )
    )
    if answer.horizontal_uncertainty_m is not None:
        entry["horizontalUncertaintyMeters"] = round(
            answer.horizontal_uncertainty_m, 3
        )
    if answer.vertical_extent_m is not None:
        entry["verticalExtentMeters"] = round(answer.vertical_extent_m, 3)
    if answer.merged_count > 1:
        entry["mergedFrom"] = answer.merged_count
    return entry


def reverse_candidate(answer, pidf_lo: str) -> dict[str, Any]:
    """One /ReverseGeocodeEnhanced candidate (§12.2).

    Carries the containment flag and the raw geodesic distance the strict
    interface cannot: that disclosure is what pays for §10.5's uncorrected
    centerline bias, since a caller who can see the distance can see how close
    the call was. `houseNumberSynthesised` is the other thing i3 cannot say —
    RFC 5139 gives HNO no way to mark itself approximate even in principle
    (§11.2, §16).
    """
    entry: dict[str, Any] = {"pidfLo": pidf_lo}
    entry.update(
        _quality_fields(
            match_score=answer.quality.match_score,
            location_type=answer.location_type,
            confidence=answer.confidence,
            field_scores=dict(answer.quality.field_scores),
        )
    )
    entry["distanceMeters"] = round(answer.distance_m, 3)
    entry["contained"] = answer.contained
    entry["houseNumberSynthesised"] = answer.house_number_synthesised
    if answer.placement is not None:
        entry["placementMethod"] = answer.placement
    return entry


def enhanced_response(
    candidates: Sequence[dict[str, Any]],
    *,
    location_count: int = 1,
    dropped: Iterable[DroppedElement] = (),
) -> dict[str, Any]:
    """The enhanced envelope around a ranked candidate list.

    `locationCount` appears only where the request carried more than one
    location. i3 §4.5 mandates converting the first and gives no way to signal
    that the others were discarded, so this is the only interface in the service
    where that discard is visible at all (§4.2, decision 50, §16).

    `droppedElements` reports what admission could not use — today, an address
    number that would not reduce to a non-negative integer (decision 63). A
    caller handed a street-level answer can see that the house number was the
    reason, rather than inferring it from a lower score.
    """
    body: dict[str, Any] = {"candidates": list(candidates)}
    if location_count > 1:
        body["locationCount"] = location_count
    entries = [
        {"element": item.element, "value": item.value, "reason": item.reason}
        for item in dropped
    ]
    if entries:
        body["droppedElements"] = entries
    return body
