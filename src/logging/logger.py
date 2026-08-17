"""Emit structured GCS log events to Python's standard logging and, when
GCS_LOGGING_SERVICE_URI is configured, to the i3 Logging Service — via the
shared i3_fe_core.logging.logging_client.LoggingClient built in
core_components.py (runtime_state.logging_client).

Mirrors mcs-service's src/logging/logger.py mechanism — emit_nowait(), no
background event loop — rather than lvf-service's, whose background-loop
shim exists only because some of its call sites run outside a running event
loop (the regression runner's synchronous handle_find_service()). Every GCS
call site is inside an `async def` FastAPI handler (src/api/geocode.py,
src/api/reverse_geocode.py), so a running loop is always present when
emit_log_event() runs, and that shim's reason for existing does not apply
here. LoggingClient.emit_nowait() stamps elementId/agencyId/timestamp,
writes to stdlib logging unconditionally, and best-effort-POSTs to the
Logging Service when configured — all synchronously non-blocking, per its
own docstring.
"""

from __future__ import annotations

import logging

from src import runtime_state
from src.logging.log_events import GcsQueryLogEvent, GcsResponseLogEvent

log = logging.getLogger(__name__)


def emit_log_event(event: GcsQueryLogEvent | GcsResponseLogEvent) -> None:
    if runtime_state.logging_client is None:
        log.warning(
            "logging_client not initialized (core_components.build_core_components() "
            "not called) — %s not emitted", event.log_event_type,
        )
        return
    runtime_state.logging_client.emit_nowait(event)


def make_query_event(**kwargs) -> GcsQueryLogEvent:
    return GcsQueryLogEvent(**kwargs)


def make_response_event(**kwargs) -> GcsResponseLogEvent:
    return GcsResponseLogEvent(**kwargs)
