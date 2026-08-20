"""Stages 1-3 for all four resources — engine in, PIDF-LO out.

This module is the join. Admission (§4, §9) produced an AdmittedRequest; the
engine (§6-§7, §10-§11) works in the element model; the wire layer speaks
PIDF-LO. Everything here is plumbing between those three, and none of it decides
anything the specification has not already decided.

ONE ENGINE, TWO INTERFACES (§2.3, decision 8)

The strict and enhanced resources run the SAME conversion and diverge only at
serialisation. `geocode()` and `reverse_geocode()` are called identically by
both; the strict handler then takes rank 1 and drops what §4.5 has no field for,
while the enhanced handler serialises the list. Rank 1 is provably the same
answer on both, because GCS_MIN_MATCH_SCORE floored admission upstream in §6 and
the §10.3 ordering is fixed before either sees it.

WHAT TRAVELS ON BOTH INTERFACES

The RFC 7459 confidence element. §7.4 makes it the one piece of the three-field
quality model that fits an element i3 and the IETF already define, so carrying it
is passing through standard vocabulary rather than minting any — which is the
test §1.2.1 sets. §8.1 and §12.1 separately describe the strict interfaces as
carrying no quality signal at all; the two readings are reconciled in favour of
§7.4 here, and the tension is recorded in spec Appendix C.4 rather than settled
silently.

WHAT DOES NOT

Score, rank, match type, Placement Method, containment, distance, and any
indication that a house number was interpolated rather than read. Those have no
i3-defined element and no §4.5 field, and inventing one would breach §1.2.1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from lxml import etree

from src.api.admission import AdmittedRequest
from src.api.wire import civic_xml, gml_xml, pidf_xml
from src.api.wire.civic_xml import DroppedElement, ParsedCivic
from src.engine.models import Candidate, CivicAddress, Position, SsapGisRecord
from src.engine.scoring_registry import forward_scorer, reverse_scorer
from src.geocode import candidates as candidate_identification
from src.geocode import response_assembly as forward_assembly
from src.geocode.candidates import AmbiguousResult
from src.geocode.response_assembly import ForwardAnswer
from src.gis import provisioning
from src.reverse import origin as origin_shapes
from src.reverse import response_assembly as reverse_assembly
from src.reverse import search as reverse_search
from src.reverse.response_assembly import ReverseAnswer

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Forward — §6, §7, §8
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ForwardConversion:
    """What Stage 1 produced, plus what admission could not use."""

    candidates: list[Candidate]
    query: CivicAddress
    dropped: tuple[DroppedElement, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.candidates)


def geocode(admitted: AdmittedRequest) -> ForwardConversion:
    """Run §6's ladder against the elected civic address.

    Raises ScorerUnavailable where §6.5's function has not been injected, and
    AmbiguousResult is left for the caller to catch — §6.3's beyond-tolerance
    case is a 468, and deciding that is status selection's job, not this
    module's.
    """
    from src import runtime_state

    parsed: ParsedCivic = civic_xml.parse(admitted.chunk)
    if parsed.dropped:
        for item in parsed.dropped:
            log.info("Dropped %s=%r: %s", item.element, item.value, item.reason)

    found = candidate_identification.identify(
        parsed.civic,
        ssap=provisioning.ssap_records(),
        rcl=provisioning.rcl_records(),
        score=forward_scorer(),
        min_match_score=runtime_state._min_match_score,
        offset_m=runtime_state._rcl_offset_m,
        endpoint_margin_m=runtime_state._rcl_endpoint_margin_m,
        at=runtime_state.now(),
    )
    return ForwardConversion(
        candidates=found, query=parsed.civic, dropped=parsed.dropped
    )


def strict_forward_answer(conversion: ForwardConversion) -> Optional[ForwardAnswer]:
    """Rank 1, or §6.3's merge. Raises AmbiguousResult beyond tolerance.

    `house_number` is threaded through from the elected query (decision 121)
    so a rung-3 ambiguity check can narrow by `range_gap` the same way
    `_rank_segments` already ranks by it — see
    `response_assembly.strict_answer`'s own docstring for why matchScore
    alone is not a fine enough tier there. `conversion.query.Add_Number` is
    already `None` for exactly the cases where there is nothing to narrow by
    (decision 63's drop, or no HNO in the request at all), so no separate
    "was there a house number" test is needed here.
    """
    from src import runtime_state

    return forward_assembly.strict_answer(
        conversion.candidates,
        tolerance_m=runtime_state._ambiguity_tolerance_m,
        house_number=conversion.query.Add_Number,
    )


def forward_document(answer: ForwardAnswer, admitted: AdmittedRequest) -> str:
    """§8.1 — the geodetic representation, and nothing else.

    The matched civic address is NOT echoed. i3 §4.5 says Geocode "returns a
    PIDF-LO containing a geodetic representation for the same location"; each
    direction returns the converted form only. RFC 5491 describes what a PIDF-LO
    MAY contain and has no opinion on what a Geocode response SHOULD contain,
    and "the format permits it" is not "the standard asks for it" (§1.2.1).
    """
    geometry = gml_xml.answer_geometry_element(
        position=answer.position,
        line_geometry=answer.geometry if answer.is_line_answer else None,
        srs_name=answer.crs,
        horizontal_uncertainty_m=answer.horizontal_uncertainty_m,
    )
    return pidf_xml.document(
        [geometry, gml_xml.build_confidence(answer.confidence)],
        entity=admitted.entity,
        usage_rules=admitted.usage_rules,
    )


def forward_record_document(
    candidate: Candidate, answer: ForwardAnswer, admitted: AdmittedRequest
) -> str:
    """§8.2 — the full matched record, civic AND geodetic.

    This is what makes the enhanced interface answer the question §8.1 cannot: a
    client that queried "101 Main St" and matched "101 Mayne St" sees the
    substitution by diffing this record against its query (decision 11).
    """
    payload: list[etree._Element] = [civic_xml.build(_record_civic(candidate))]
    payload.append(
        gml_xml.answer_geometry_element(
            position=answer.position,
            line_geometry=answer.geometry if answer.is_line_answer else None,
            srs_name=answer.crs,
            horizontal_uncertainty_m=answer.horizontal_uncertainty_m,
        )
    )
    payload.append(gml_xml.build_confidence(answer.confidence))
    return pidf_xml.document(
        payload, entity=admitted.entity, usage_rules=admitted.usage_rules
    )


def _record_civic(candidate: Candidate) -> CivicAddress:
    """The civic address of the record a forward candidate matched.

    An address point holds one outright. A centerline holds two attribute sets
    and §11.3 makes the side the selector, so a rung-2 candidate reports the
    side its interpolation landed on. A rung-3 candidate chose no position and
    therefore no side, and reports only the unsided street elements.
    """
    record = candidate.record
    if isinstance(record, SsapGisRecord):
        return record.civic()
    if candidate.side is not None:
        return record.civic_for_side(candidate.side)
    return record.civic_shared()


# ---------------------------------------------------------------------------
# Reverse — §9, §10, §11, §12
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ReverseConversion:
    answers: list[ReverseAnswer]
    origin: origin_shapes.SearchOrigin

    @property
    def found(self) -> bool:
        return bool(self.answers)

    @property
    def answer(self) -> Optional[ReverseAnswer]:
        """Rank 1 (§12.1) — the single election point for the strict route.

        `self.answers` already carries decision 122's narrowing (reverse_
        assembly.answers), so this is plain index 0, not a second election.
        """
        return self.answers[0] if self.answers else None


def reverse_geocode(admitted: AdmittedRequest) -> ReverseConversion:
    """Parse the input shape, search once, derive civic addresses.

    Raises GmlParseError where the elected chunk is not a readable RFC 5491
    shape, and ScorerUnavailable where §10.6's function is not injected.
    """
    from src import runtime_state

    shape = gml_xml.parse_shape(admitted.chunk)
    origin = origin_shapes.origin_of(shape)

    hits = reverse_search.search(
        origin,
        ssap=provisioning.ssap_records(),
        rcl=provisioning.rcl_records(),
        radius_m=runtime_state._reverse_search_radius_m,
    )
    answers = reverse_assembly.answers(
        origin,
        hits,
        score=reverse_scorer(),
        endpoint_margin_m=runtime_state._rcl_endpoint_margin_m,
    )
    return ReverseConversion(answers=answers, origin=origin)


def reverse_document(answer: ReverseAnswer, admitted: AdmittedRequest) -> str:
    """§12.1 — one civic address, nothing else.

    No rank, no score, no distance, no containment flag, no Placement Method,
    and no indication that the house number was synthesised rather than read.
    Everything §10 and §11 computed is discarded here. RFC 5139 cannot mark HNO
    approximate even in principle, so a synthesised number and a validated one
    serialise identically — a limitation of the civic schema itself rather than
    of i3's silence, and a §16 row (§11.2).
    """
    return pidf_xml.document(
        [
            civic_xml.build(answer.civic),
            gml_xml.build_confidence(answer.confidence),
        ],
        entity=admitted.entity,
        usage_rules=admitted.usage_rules,
    )


def reverse_record_document(answer: ReverseAnswer, admitted: AdmittedRequest) -> str:
    """§12.2 — the full matched record, civic and geodetic together."""
    payload: list[etree._Element] = [civic_xml.build(answer.civic)]
    if answer.position is not None:
        payload.append(gml_xml.build_point(answer.position))
    payload.append(gml_xml.build_confidence(answer.confidence))
    return pidf_xml.document(
        payload, entity=admitted.entity, usage_rules=admitted.usage_rules
    )


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

def enhanced_forward_answers(
    conversion: ForwardConversion,
) -> Sequence[tuple[Candidate, ForwardAnswer]]:
    """Every candidate paired with its answer, in §7.4's ranked order.

    No merge and no averaging: the honest answer to an underspecified query is a
    real candidate list, not a synthetic blended point (decision 27).
    """
    return [
        (candidate, forward_assembly.answer_for(candidate))
        for candidate in conversion.candidates
    ]


__all__ = [
    "AmbiguousResult",
    "ForwardConversion",
    "ReverseConversion",
    "enhanced_forward_answers",
    "forward_document",
    "forward_record_document",
    "geocode",
    "reverse_document",
    "reverse_geocode",
    "reverse_record_document",
    "strict_forward_answer",
    "Position",
]
