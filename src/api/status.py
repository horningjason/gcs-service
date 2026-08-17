"""i3 §4.5 status code selection (spec §8.4, §12.3).

The set is CLOSED to five codes (§2.1, §1.2.1, decision 2). Nothing in this
service mints a sixth:

    200  a single result was derived
    307  conversion failed AND GCS_REFERRAL_URI is configured — the URI travels
         in the Location header, per the normative YAML, which defines no
         gcsReferralUri body property at all (§3.6.2, decision 34)
    454  schema validation failure and residual internal errors, on BOTH
         operations, with a human-readable body reason as this implementation's
         convention (§4.1, decision 36). The YAML omits 454 from
         /ReverseGeocode; that asymmetry is declined and recorded as a §16 row.
    468  the request was valid but no result is derivable
    469  never emitted — the condition is undefined for a request carrying no
         service identifier (§2.1)

Every response the four resources emit is built by one of the four functions
below, so the closed set is enforced in one place rather than asserted in four.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi.responses import JSONResponse, Response

from src import runtime_state
from src.api.admission import AdmissionError

log = logging.getLogger(__name__)

#: i3 §4.5's complete status set (§1.2.1, §2.1, decision 2). Nothing in this
#: service emits a code outside it; a test asserts the four resources never do.
STATUS_SET: frozenset[int] = frozenset({200, 307, 454, 468, 469})


def success_response(body: dict[str, Any]) -> Response:
    """200 — a single result was derived (§8.4, §12.3).

    application/json for the wrapper object, carrying the PIDF-LO XML document
    as a string value. The normative YAML declares application/xml around a
    JSON-shaped object, which is incoherent as written; this is the only reading
    under which its declared schemas are implementable (§3.9.1, §16).
    """
    return JSONResponse(status_code=200, content=body)


def no_result_response(reason: str) -> Response:
    """468, or 307 where a referral is configured.

    The request was valid and a search was performed; nothing was derivable.
    Every §6.4 path to zero candidates arrives here and none is distinguished,
    because the interface has no field to carry the difference (§3.6.2, §8.4).
    """
    if runtime_state._referral_uri:
        return Response(
            status_code=307,
            headers={"Location": runtime_state._referral_uri},
        )
    # §4.5 defines no body for 468 and none is invented (§1.2.1).
    log.info("468 No Address Found: %s", reason)
    return Response(status_code=468)


def error_response(reason: str) -> Response:
    """454 — schema validation failure or a residual internal error (§4.1).

    Never converted to a referral, for the same reason a malformed request is
    not: handing it to a peer GCS would only relocate the failure.
    """
    return JSONResponse(status_code=454, content={"reason": reason})


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
