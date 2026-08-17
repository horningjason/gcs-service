"""GCS structured log event types — spec decision 104 (resolving Appendix
C.4 Q10 / spec §A.3).

i3 §4.12.3.7 defines no GCS-specific LogEvent type: direct read of the full
registry (44 types) confirmed the LoST and ALI query/response pairs it does
define — LostQueryLogEvent/LostResponseLogEvent, LocationQueryLogEvent/
LocationResponseLogEvent — are scoped to other services' traffic. Decision
104 proposes GcsQueryLogEvent / GcsResponseLogEvent on that same registered
pattern: whole payload carried in the event, a queryId/responseId pair
correlating the two, direction incoming/outgoing, and a status field
preserving cases a single combined event could not represent. These classes
implement that proposal — there is no existing registry entry to subclass.

This shape is NOT a straight port of either reference implementation
(lvf-service/src/logging/log_events.py, mcs-service/src/logging/log_events.py):

  - lvf-service's LostQueryLogEvent splits the payload across two fields —
    query_adapter for a well-formed request, malformed_query for a garbled
    one — because LoST-specific downstream handling wants to know which
    case it was. Decision 104 asks for ONE payload field ("whole payload
    carried in the event"); GcsQueryLogEvent.query_adapter always carries
    the raw request text, well-formed or not. A query event still fires on
    malformed/unadmittable input — see src/api/geocode.py and
    src/api/reverse_geocode.py's emission choice, and their docstrings for
    why.
  - lvf-service's response_status is a LoST status STRING, populated only
    on malformed/error responses — LoST's "status" is not a concept every
    response carries. GCS's two operations are HTTP-status-coded on every
    response, from the closed five-code set src/api/status.py enforces, so
    GcsResponseLogEvent.response_status is the actual HTTP status int and
    is MANDATORY on every response — precisely the thing decision 104
    calls out responseStatus as needing to preserve: a malformed request
    that never became a real query still gets a distinguishable status on
    the response side.

No LogEventPrologue subclass elsewhere in i3-fe-core defines a shared
"correlation id" field to reuse: SubscribeLogEvent uses its own
subscription_id, DiscrepancyReportLogEvent correlates via `contents`'s own
discrepancyReportId, and LostQueryLogEvent/LostResponseLogEvent define their
own query_id/response_id. Each FE's query/response pattern mints its own
pair; query_id/response_id here follows that same precedent, named to match
decision 104's own text ("a globally unique queryId/responseId pair") and
LostQueryLogEvent/LostResponseLogEvent's field names exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from i3_fe_core.logging.logevent import LogEventPrologue


def generate_query_id() -> str:
    """Return a globally unique query ID per NENA-STA-010.3f-2021 §4.12.3.7."""
    return f"urn:emergency:uid:queryid:{uuid.uuid4()}"


@dataclass
class GcsQueryLogEvent(LogEventPrologue):
    """§4.12.3 query-side event for a /Geocode or /ReverseGeocode request.

    Fired once per request, at the top of the handler — before Stage 0 (request
    admission) runs, not after it succeeds. See the call sites for why: a
    malformed or unadmittable body is still "the input object" i3 §4.5
    requires logging, and is the request most worth a forensic record of.
    """

    log_event_type: str = "GcsQueryLogEvent"

    query_id: str = ""              # urn:emergency:uid:queryid:<uuid4>
    direction: str = ""             # always "incoming" — the GCS originates no queries of its own
    operation: str = ""             # "Geocode" | "ReverseGeocode"
    query_adapter: str = ""         # the whole request payload, as received — raw PIDF-LO text
    # CONDITIONAL, per i3 §4.12.3.1's own serviceId convention (mirrored from
    # LostQueryLogEvent) — GCS's two operations carry no service identifier
    # of their own (spec §2.1: "469 ... undefined for a request carrying no
    # service identifier"), so this stays unset in practice. Present for
    # shape parity with the registered LostQuery/LostResponse pattern
    # decision 104 mirrors, in case a future caller has one to supply.
    service_id: Optional[str] = None


@dataclass
class GcsResponseLogEvent(LogEventPrologue):
    """§4.12.3 response-side event for a /Geocode or /ReverseGeocode reply.

    response_status carries the actual HTTP status returned — 200, 307, 454,
    or 468, the closed set src/api/status.py enforces — on EVERY response,
    not only on error. See the module docstring for why this differs from
    lvf-service's response_status.
    """

    log_event_type: str = "GcsResponseLogEvent"

    response_id: str = ""           # == the paired GcsQueryLogEvent.query_id
    direction: str = ""             # always "outgoing" — the GCS answers, never relays
    response_status: int = 0        # the actual HTTP status; always set at emit time
    # None when the status carries no body (468, 307 — status.py's own
    # "§4.5 defines no body ... and none is invented"); otherwise the whole
    # response payload as sent.
    response_adapter: Optional[str] = None
