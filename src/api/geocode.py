"""POST /Geocode — the strict i3 forward conversion (spec §4-§8).

Contract, per references/i3-geocode-conversion.yaml (normative over the §4.5
text per i3 §2.8):

    request   PIDF-LO carrying a civic address, as a string
    200       GeodeticData { pidfLoGeo: string }, as real XML — the YAML's
              declared application/xml content type and its string-typed
              property both hold under OpenAPI's default XML serialization
              (decision 116): <GeodeticData><pidfLoGeo><![CDATA[...]]>
              </pidfLoGeo></GeodeticData>
    307       referral, URI in the Location header (no body field exists)
    454       schema validation failure / residual internal error
    468       valid request, no result derivable
    469       not emitted (spec §2.1 — the condition is undefined for a
              request carrying no service identifier)

The four stages:

    Stage 0  Request admission — content type, schema validation against
             schemas/gcs-pidflo.xsd, RFC 5491 Rule #8 first-location election
             (§4.1, §4.2, decision 50)
    Stage 1  Candidate identification — SSAP then RCL, one scoring function,
             §6.3 ambiguity handling (§6)
    Stage 2  Position derivation from the rank-1 candidate (§7)
    Stage 3  Response assembly — rank 1 only; everything else the engine
             computed is discarded at this boundary, which is the deficiency
             carried faithfully (§8.1, decision 9, decision 10)

NOT emitted on this interface: score, rank, match type, Placement Method,
containment, or any indication that the match was fuzzy. A fuzzy match returns
200 and a coordinate byte-for-byte indistinguishable from an exact match. That
is what §4.5 permits it to return, and carrying it faithfully is what makes the
two interfaces a controlled comparison (§2.2).
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
from src.app import lifecycle
from src.engine.scoring_registry import ScorerUnavailable
from src.logging.log_events import generate_query_id
from src.logging.logger import emit_log_event, make_query_event, make_response_event

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/Geocode")
async def geocode(request: Request) -> Response:
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
        operation="Geocode",
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

    # Stage 0 — §4.1 body/Content-Type/schema, §4.2 first-location election.
    try:
        admitted = admit(
            raw_body,
            request.headers.get("content-type"),
            Profile.CIVIC,
            lifecycle._schema,
        )
    except AdmissionError as exc:
        return _respond(failure_response(exc))

    # Stages 1 and 2 — the ladder, then position derivation from rank 1.
    try:
        converted = conversion.geocode(admitted)
        answer = conversion.strict_forward_answer(converted)
    except conversion.AmbiguousResult as exc:
        # §6.3 — candidates that disagree horizontally beyond tolerance are not
        # a location. Merging two "State Street" matches forty miles apart
        # yields a position in a field that a consumer ignoring uncertainty
        # will treat as an answer, so 468 is returned instead (§8.4).
        return _respond(no_result_response(str(exc)))
    except ScorerUnavailable as exc:
        return _respond(error_response(str(exc)))

    if answer is None:
        # §6.4 enumerates several distinct paths here — nothing provisioned,
        # nothing above GCS_MIN_MATCH_SCORE, every survivor unlocatable — and
        # all of them map to the same code with no way for a consumer to tell
        # them apart. They are not distinguished (§3.6.2, §8.4).
        return _respond(no_result_response("No candidate was derivable for the query address."))

    # Stage 3 — §8.1. Everything the engine computed except the geodetic
    # representation is dropped right here.
    return _respond(success_xml_response(
        strict_xml.geodetic_data_xml(conversion.forward_document(answer, admitted))
    ))
