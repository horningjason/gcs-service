"""POST /GeocodeEnhanced and POST /ReverseGeocodeEnhanced — the i3-improved
interface (spec §3.9.2, §8.2, §12.2; decision 35).

Non-i3 sibling resources on the SAME web service as the strict paths,
discovered through the /Versions vendor parameter. The strict paths remain
byte-for-byte conformant to the normative YAML, untouched. Because the enhanced
schema is purely additive alongside the published v1 YAML, the NENA-facing
extension proposal can be expressed as a literal diff against it.

One engine feeds both interfaces (§2.3, decision 8). The engine always produces
a ranked scored candidate list; the strict interface takes rank 1 and drops
what §4.5 has no field for, and these resources return the list. Rank 1 is
provably the same answer on both — GCS_MIN_MATCH_SCORE floors admission in
engine/ upstream of both response assemblies, so neither interface sees a
candidate the other does not.

Each candidate carries:
  - the full matched PIDF-LO record, civic AND geodetic, not a bare geometry,
    so a client that queried "101 Main St" and matched "101 Mayne St" can see
    the substitution by diffing the record against its query (§8.2, decision 11)
  - the three-field quality model (§7.4, decision 31):
      matchScore     per-field similarity with breakdown (forward), or
                     spatial-fit with its own component breakdown (reverse,
                     §10.6) — same field, same range, same shape
      locationType   ordered precision tier keyed to matched geometry class:
                     SPACE_3D > FOOTPRINT_2D > ADDRESS_POINT >
                     INTERPOLATED_POINT > STREET_SEGMENT
      confidence     matchScore scaled to the tier ceiling
                     (100/90/80/75/50), derived and never stored independently
  - the i3 §10.31 match type token — only Address and RoadCenterline are
    usable; the registry is materially coarser than locationType (§12.2, §16)
  - STA-006.3 Placement Method where present (§3.2, §10.5)
  - reverse only: the containment flag and the raw geodesic distance from the
    origin, so a caller can see how close the call was (§10.5)
  - the count of locations the request carried, where more than one was present
    and only the elected one converted — the discard i3 mandates but gives no
    way to signal (§4.2, decision 50, §16)

Embedded PIDF-LO records stay RFC 4119 / RFC 5491 conformant regardless of this
envelope: PIDF-LO conformance travels with the format, not the interface
(§1.2.1, decision 13).

  - the address number elements admission could not use, where a supplied
    complete address number would not reduce to a non-negative integer. The
    request is answered without it rather than rejected, and reporting the drop
    here is what lets a caller handed a street-level answer see why (decision 63)

THE CANDIDATE SCHEMA IS NORMATIVE (decision 92, closing Appendix C item (c))

`references/i3-geocode-conversion-enhanced.yaml` is the additive diff intended
for the NENA proposal, reconciled field-for-field against
src/api/wire/response_json.py. The YAML is the normative spelling; the code is
expected to match it rather than the reverse.

THE STATUS SET IS THE SAME CLOSED SET

These resources are non-i3, but they are not licensed to mint codes. §1.2.1
scopes decision 2's closed set to the service, not to the strict paths, so an
enhanced request that derives nothing returns 468 exactly as its strict sibling
does — with a candidate list being the only thing that differs on success.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response

from src.api import conversion
from src.api.admission import AdmissionError, Profile, admit
from src.api.status import (
    error_response,
    failure_response,
    no_result_response,
    success_response,
)
from src.api.wire import response_json
from src.api.wire.gml_xml import GmlParseError
from src.app import lifecycle
from src.engine.scoring_registry import ScorerUnavailable

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/GeocodeEnhanced")
async def geocode_enhanced(request: Request) -> Response:
    # One engine, one admission path (§2.3). The enhanced resources run the
    # same Stage 0 as the strict ones — admission is where the two interfaces
    # are identical by construction, not merely by intent.
    try:
        admitted = admit(
            await request.body(),
            request.headers.get("content-type"),
            Profile.CIVIC,
            lifecycle._schema,
        )
    except AdmissionError as exc:
        return failure_response(exc)

    try:
        converted = conversion.geocode(admitted)
    except ScorerUnavailable as exc:
        return error_response(str(exc))

    if not converted.found:
        return no_result_response("No candidate was derivable for the query address.")

    # No merge and no averaging here, unlike the strict path: the honest answer
    # to an underspecified query is a real candidate list, not a synthetic
    # blended point (decision 27). §6.3's ambiguity test therefore never fires
    # on this interface and cannot turn a real candidate list into a 468.
    candidates = [
        response_json.forward_candidate(
            answer, conversion.forward_record_document(candidate, answer, admitted)
        )
        for candidate, answer in conversion.enhanced_forward_answers(converted)
    ]
    return success_response(
        response_json.enhanced_response(
            candidates,
            location_count=admitted.location_count,
            dropped=converted.dropped,
        )
    )


@router.post("/ReverseGeocodeEnhanced")
async def reverse_geocode_enhanced(request: Request) -> Response:
    try:
        admitted = admit(
            await request.body(),
            request.headers.get("content-type"),
            Profile.GEODETIC,
            lifecycle._schema,
        )
    except AdmissionError as exc:
        return failure_response(exc)

    try:
        converted = conversion.reverse_geocode(admitted)
    except GmlParseError as exc:
        return error_response(f"Geodetic location could not be read: {exc}.")
    except ScorerUnavailable as exc:
        return error_response(str(exc))

    if not converted.found:
        return no_result_response(
            "No feature fell within GCS_REVERSE_SEARCH_RADIUS_M of the origin."
        )

    # §10.3's order is preserved exactly — the scorer decorates, it does not
    # re-rank, and nothing here re-sorts by score either.
    candidates = [
        response_json.reverse_candidate(
            answer, conversion.reverse_record_document(answer, admitted)
        )
        for answer in converted.answers
    ]
    return success_response(
        response_json.enhanced_response(
            candidates, location_count=admitted.location_count
        )
    )
