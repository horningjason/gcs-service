"""i3 §4.5 status code selection (spec §8.4, §12.3).

The set is CLOSED to five codes (§2.1, §1.2.1, decision 2). Nothing in this
service mints a sixth:

    200  a single result was derived — real XML on the strict interface as
         of decision 116 (`success_xml_response()`, `src/api/wire/
         strict_xml.py`), still JSON on the enhanced interface
         (`success_response()`), since only the strict resources are bound
         to the normative YAML's declared schema
    307  conversion failed AND GCS_REFERRAL_URI is configured — the URI travels
         in the Location header, per the normative YAML, which defines no
         gcsReferralUri body property at all (§3.6.2, decision 34)
    454  schema validation failure and residual internal errors, on BOTH
         operations, with a human-readable body reason as this implementation's
         convention (§4.1, decision 36). The YAML omits 454 from
         /ReverseGeocode; that asymmetry is declined and recorded as a §16 row.
         Still JSON on both interfaces — decision 116 is scoped to the 200
         body the YAML actually declares a schema for; 454 has none.
    468  the request was valid but no result is derivable, with a fixed,
         non-distinguishing body reason (decision 114) — see
         no_result_response()'s own docstring for why it does not vary. Still
         JSON, for the same reason 454 is.
    469  never emitted — the condition is undefined for a request carrying no
         service identifier (§2.1)

Every response the four resources emit is built by one of the functions
below, so the closed set is enforced in one place rather than asserted in
four.

The JSON paths go through `_PrettyJSONResponse` rather than Starlette's bare
`JSONResponse` (decision 115) — indented, not the compact single-line
default. The strict-200 XML path is indented for the same reason, in
`src/api/wire/pidf_xml.py::to_string()` and `strict_xml.py` themselves.
Neither is a wire-format departure: i3 gives no opinion on incidental
whitespace, only on fields and status codes (§1.2.1), so a JSON or XML
parser sees exactly the same document either way. It exists so a response
is readable straight out of curl, not only after a client decodes and
re-formats it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi.responses import JSONResponse, Response

from src import runtime_state
from src.api.admission import AdmissionError

log = logging.getLogger(__name__)

#: i3 §4.5's complete status set (§1.2.1, §2.1, decision 2). Nothing in this
#: service emits a code outside it; a test asserts the four resources never do.
STATUS_SET: frozenset[int] = frozenset({200, 307, 454, 468, 469})


class _PrettyJSONResponse(JSONResponse):
    """JSONResponse, indented (decision 115).

    Starlette's own `render()` hard-codes `indent=None` and comma/colon
    separators with no space — the most compact valid encoding, chosen for
    a general-purpose framework default rather than for this service. i3
    §4.5 has no opinion on wrapper whitespace (§1.2.1's "wire vocabulary"
    concern is fields and status codes, not incidental JSON/XML formatting),
    so indenting is not a departure from anything normative — it changes
    nothing a JSON parser or an XML parser sees as meaningful, only what a
    person reading raw curl output sees.
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def success_response(body: dict[str, Any]) -> Response:
    """200 — a single result was derived (§8.4, §12.3), enhanced interface.

    application/json, unaffected by decision 116: the enhanced schema is
    GCS's own additive definition (§2.2), not bound to the normative YAML's
    declared content type.
    """
    return _PrettyJSONResponse(status_code=200, content=body)


def success_xml_response(xml_body: str) -> Response:
    """200 — a single result was derived (§8.4, §12.3), strict interface.

    application/xml, per decision 116: the normative YAML's declared
    `application/xml` content type and its `{pidfLoGeo|pidfLoAddress}:
    string` schema both hold under OpenAPI's own default XML serialization
    (`src/api/wire/strict_xml.py` builds the body). Superseded the Session 3
    reading that emitted `application/json` instead on the theory that the
    two declarations were irreconcilable.
    """
    return Response(status_code=200, content=xml_body, media_type="application/xml")


#: The fixed, invariant 468 body reason (decision 114). Deliberately the same
#: string on every call regardless of which §6.4 path triggered it — see
#: no_result_response()'s docstring for why.
_NO_RESULT_REASON = "No result was derivable for the query."


def no_result_response(reason: str) -> Response:
    """468, or 307 where a referral is configured.

    The request was valid and a search was performed; nothing was derivable.
    Every §6.4 path to zero candidates arrives here and none is distinguished
    — that is a stated invariant there ("no coverage test distinguishes
    them"), not an oversight.

    `reason` is still accepted and still logged (server-side diagnostic
    value is unaffected), but as of decision 114 the WIRE body is no longer
    empty either: it carries a fixed, invariant reason string identical on
    every 468 regardless of which §6.4 path produced it. That was a
    deliberate choice between two ways of resolving the asymmetry with 454
    (which has carried a reason since decision 36) — putting the caller-
    supplied `reason` argument on the wire verbatim was considered and
    rejected, because at least one call site (the §6.3 AmbiguousResult path,
    src/api/geocode.py) passes a reason with real distinguishing detail
    (candidate count and span in metres), and exposing that would silently
    reopen the "paths are not distinguished" decision under cover of a
    consistency fix. A fixed string closes the shape gap with 454 (every
    non-2xx response now carries a `reason` field) without smuggling in that
    larger, unreviewed change.
    """
    if runtime_state._referral_uri:
        return Response(
            status_code=307,
            headers={"Location": runtime_state._referral_uri},
        )
    log.info("468 No Address Found: %s", reason)
    return _PrettyJSONResponse(status_code=468, content={"reason": _NO_RESULT_REASON})


def error_response(reason: str) -> Response:
    """454 — schema validation failure or a residual internal error (§4.1).

    Never converted to a referral, for the same reason a malformed request is
    not: handing it to a peer GCS would only relocate the failure.
    """
    return _PrettyJSONResponse(status_code=454, content={"reason": reason})


def failure_response(exc: AdmissionError) -> Response:
    """Turn an AdmissionError into the wire response i3 §4.5 calls for.

    A 468 becomes a 307 where a referral is configured. §3.6.2 is explicit that
    the referral is emitted on EVERY conversion failure — including for
    addresses that exist nowhere, sending the client onward for a lost cause.
    That is what §4.5 literally specifies and is part of why the §16 gap row is
    justified rather than pedantic.

    A 454 is never converted to a referral: it says the request was malformed,
    and handing a malformed request to a peer GCS would only relocate the
    failure.
    """
    if exc.status == 454:
        # §4.1: "with a human-readable reason in the response body as this
        # implementation's convention". §4.5 defines no body for 454, so this
        # is convention rather than contract — it adds no field to an
        # i3-defined response object, because 454 has none.
        return error_response(exc.reason)

    return no_result_response(exc.reason)
