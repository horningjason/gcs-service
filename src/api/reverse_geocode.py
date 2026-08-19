"""POST /ReverseGeocode — the strict i3 inverse conversion (spec §9-§12).

Contract, per references/i3-geocode-conversion.yaml (normative over the §4.5
text per i3 §2.8):

    request   PIDF-LO carrying a geodetic representation, as a string
    200       CivicAddress { pidfLoAddress: string }, as real XML — see
              src/api/geocode.py's docstring for decision 116, applied
              identically here: <CivicAddress><pidfLoAddress><![CDATA[...]]>
              </pidfLoAddress></CivicAddress>
    307       referral, URI in the Location header
    454       schema validation failure / residual internal error
    468       valid request, no candidate within GCS_REVERSE_SEARCH_RADIUS_M
    469       not emitted (spec §2.1)

Note the YAML omits 454 from this operation entirely while listing it for
/Geocode, leaving a schema-invalid reverse request with no defined error code
at all. Spec §4.1 / decision 36 declines to follow that asymmetry and returns
454 here too, following the YAML's evident intent over its inconsistency. The
asymmetry itself is a §16 row.

The four stages:

    Stage 0  Request admission — all eight RFC 5491 §5 shapes accepted; one
             search origin derived from any of them by the §7.5 centroid
             convention (footprint centroid for X/Y, vertical midpoint for Z).
             Restricting to Point would add a restriction i3 does not impose
             (§9, decision 37)
    Stage 1  Nearest-feature search — ONE pass out to
             GCS_REVERSE_SEARCH_RADIUS_M, candidates ordered lexicographically
             by containment, then precision tier, then true geodesic distance
             (§10, decisions 39-42)
    Stage 2  Civic derivation — read off the SSAP record, or synthesise a house
             number by inverting §7.2's interpolation along the same
             margin-shortened path, clamped to the segment range and forced to
             the side's parity (§11, decision 44)
    Stage 3  Response assembly — one civic address, nothing else (§12.1)

The i3 response carries no rank, score, distance, containment flag, Placement
Method, and no indication that a house number was interpolated rather than
read. RFC 5139 cannot mark HNO approximate even in principle, so that last one
is deeper than i3's silence — it is a limitation of the civic schema itself
(§11.2, §16).
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
    success_xml_response,
)
from src.api.wire import strict_xml
from src.api.wire.gml_xml import GmlParseError
from src.app import lifecycle
from src.engine.scoring_registry import ScorerUnavailable
from src.logging.log_events import generate_query_id
from src.logging.logger import emit_log_event, make_query_event, make_response_event

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ReverseGeocode")
async def reverse_geocode(request: Request) -> Response:
    raw_body = await request.body()

    # i3 §4.5's payload-logging MUST is unconditional, so the query event
    # fires here — before Stage 0 runs — rather than only once admission
    # succeeds: a malformed or unadmittable body is still "the input object"
    # received, and is the request most worth a forensic record of. See
    # src/logging/log_events.py's module docstring (spec decision 104).
    # query_id doubles as response_id below, correlating the pair.
    query_id = generate_query_id()
    emit_log_event(make_query_event(
        query_id=query_id,
        direction="incoming",
        operation="ReverseGeocode",
        query_adapter=raw_body.decode("utf-8", errors="replace"),
    ))

    def _respond(response: Response) -> Response:
        emit_log_event(make_response_event(
            response_id=query_id,
            direction="outgoing",
            response_status=response.status_code,
            response_adapter=response.body.decode("utf-8", errors="replace") or None,
        ))
        return response

    # Stage 0 — §9, which mirrors §4 with the geodetic profile. All eight
    # RFC 5491 §5 shapes are accepted; narrowing to Point would add a
    # restriction i3 does not impose (decision 37).
    try:
        admitted = admit(
            raw_body,
            request.headers.get("content-type"),
            Profile.GEODETIC,
            lifecycle._schema,
        )
    except AdmissionError as exc:
        return _respond(failure_response(exc))

    # Stages 1 and 2 — one search pass out to GCS_REVERSE_SEARCH_RADIUS_M,
    # then civic derivation from the ordered hits.
    try:
        converted = conversion.reverse_geocode(admitted)
    except GmlParseError as exc:
        # Well-formed XML that is not a readable location. Same class of failure
        # as a schema violation, so the same code and a reason (§4.1).
        return _respond(error_response(f"Geodetic location could not be read: {exc}."))
    except ScorerUnavailable as exc:
        return _respond(error_response(str(exc)))

    if not converted.found:
        # §12.3 — nothing within the radius. The radius is mandatory for a
        # reason worth restating: without one, a point in open water reverse
        # geocodes to whatever unfortunate address is nearest and returns 200.
        return _respond(no_result_response(
            "No feature fell within GCS_REVERSE_SEARCH_RADIUS_M of the origin."
        ))

    # Stage 3 — §12.1. Rank 1 of the same ordered list the enhanced resource
    # returns whole, which is what makes the two a controlled comparison (§2.2).
    return _respond(success_xml_response(
        strict_xml.civic_address_xml(
            conversion.reverse_document(converted.answers[0], admitted)
        )
    ))
