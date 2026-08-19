"""Tests for GcsQueryLogEvent / GcsResponseLogEvent wiring (spec decision 104,
NENA-STA-010.3f-2021 §4.12.3, §4.5).

Ported from lvf-service/tests/test_log_events.py's structure — query/response
emission, malformed-request handling, correlation-id propagation, camelCase
JSON key serialization, agencyId stamping — adapted to GCS's two operations
and event shape. This is the coverage mcs-service skipped when it ported the
logger mechanism without porting tests for it.

One GCS-specific addition beyond the port: LVF's malformed-request test
confirms `malformedQuery` gets set on an otherwise-mostly-empty query event.
GCS carries no such split field (see src/logging/log_events.py's module
docstring) — the design decision made in src/api/geocode.py /
reverse_geocode.py is that the query event ALWAYS fires, with the raw
request body as queryAdapter regardless of well-formedness, so
test_malformed_request_still_emits_a_query_event asserts that decision
directly rather than a field split.
"""

from __future__ import annotations

import json
import logging
import os

import pytest
from starlette.testclient import TestClient

from src.gis.records import RCLRecord, SSAPRecord
from tests.conformance import scoring_stubs
from tests.conformance.test_admission import CIVIC_CHUNK, GEO_CHUNK, presence, tuple_

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")

GEOCODE = "/Gcs/v1/Geocode"
REVERSE = "/Gcs/v1/ReverseGeocode"

LON, LAT = -100.883898, 46.828121


class _FakeNtpClient:
    is_healthy = True
    offset = 0.0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _ssap(fid=1, **kwargs) -> SSAPRecord:
    kwargs.setdefault("NGUID", f"{{SSAP-{fid}}}")
    kwargs.setdefault("geometry_wkt", f"POINT ({LON} {LAT})")
    kwargs.setdefault("Country", "US")
    kwargs.setdefault("A1", "ND")
    kwargs.setdefault("A2", "Burleigh")
    kwargs.setdefault("A3", "Bismarck")
    kwargs.setdefault("St_Name", "State")
    kwargs.setdefault("St_PosTyp", "Street")
    kwargs.setdefault("Add_Number", 3401)
    return SSAPRecord(fid=fid, **kwargs)


def _rcl(fid=9, **kwargs) -> RCLRecord:
    kwargs.setdefault("NGUID", f"{{RCL-{fid}}}")
    kwargs.setdefault("geometry_wkt", f"LINESTRING ({LON - 0.004} {LAT}, {LON + 0.004} {LAT})")
    kwargs.setdefault("St_Name", "State")
    kwargs.setdefault("St_PosTyp", "Street")
    return RCLRecord(fid=fid, **kwargs)


@pytest.fixture()
def client(monkeypatch):
    """No GIS data loaded — an admitted request searches an empty dataset and
    gets 468. Good for the malformed(454)/no-result(468) paths, which is all
    the malformed/correlation/camelCase/agencyId tests below need."""
    from src import server

    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def success_client(monkeypatch):
    """One address point loaded, for a genuine 200 round trip."""
    from src import server
    from src.gis import provisioning

    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    monkeypatch.setattr(provisioning, "_ssap", [_ssap()])
    monkeypatch.setattr(provisioning, "_rcl", [_rcl()])
    with TestClient(server.app) as c:
        yield c


def _log_events(caplog) -> list[dict]:
    return [
        json.loads(r.message[len("LogEvent: "):])
        for r in caplog.records
        if r.message.startswith("LogEvent: ")
    ]


# ---------------------------------------------------------------------------
# Query/response emission
# ---------------------------------------------------------------------------

def test_query_and_response_events_emitted_on_success(success_client, caplog):
    """A well-formed, admitted, matched request produces both a query and a
    response log event at INFO, correlated by id."""
    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        resp = success_client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))
    assert resp.status_code == 200

    events = _log_events(caplog)
    assert len(events) == 2, f"Expected 2 LogEvent records, got {len(events)}: {events}"
    query_evt, resp_evt = events

    assert query_evt["logEventType"] == "GcsQueryLogEvent"
    assert query_evt["direction"] == "incoming"
    assert query_evt["operation"] == "Geocode"
    assert query_evt["queryId"].startswith("urn:emergency:uid:queryid:")
    assert query_evt["queryAdapter"]  # the raw request body

    assert resp_evt["logEventType"] == "GcsResponseLogEvent"
    assert resp_evt["direction"] == "outgoing"
    assert resp_evt["responseId"] == query_evt["queryId"]
    assert resp_evt["responseStatus"] == 200
    assert resp_evt["responseAdapter"]  # the 200 body


def test_reverse_geocode_operation_field(success_client, caplog):
    """The operation field distinguishes which of the two resources a query
    event belongs to — GCS-specific, since decision 104's pattern covers both
    operations with one event pair rather than LVF's one-function-many-LoST-
    operations shape."""
    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        resp = success_client.post(REVERSE, content=presence(tuple_(GEO_CHUNK)))
    events = _log_events(caplog)
    query_evt = events[0]
    assert query_evt["operation"] == "ReverseGeocode"
    # Not asserting the status here — the fixture's RCL sits south of the
    # queried point and containment/radius aren't this test's concern; the
    # operation field is set regardless of what Stage 1/2 later decide.
    assert resp.status_code in (200, 468)


def test_malformed_request_still_emits_a_query_event(client, caplog):
    """Design decision (src/api/geocode.py): the query event fires BEFORE
    Stage 0 (request admission) runs, not only once admission succeeds — a
    malformed body is still "the input object" i3 §4.5 requires logging, and
    is the request most worth a forensic record of. See
    src/logging/log_events.py's module docstring for the full rationale."""
    malformed = b"<presence><unclosed>"
    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        resp = client.post(GEOCODE, content=malformed)
    assert resp.status_code == 454

    events = _log_events(caplog)
    assert len(events) == 2, f"Expected 2 LogEvent records, got {len(events)}: {events}"
    query_evt, resp_evt = events

    assert query_evt["logEventType"] == "GcsQueryLogEvent"
    assert query_evt["queryAdapter"] == malformed.decode("utf-8")

    assert resp_evt["responseId"] == query_evt["queryId"]
    assert resp_evt["responseStatus"] == 454
    assert resp_evt["responseAdapter"]  # 454 carries a {"reason": ...} body


def test_no_result_response_carries_468_and_a_fixed_generic_reason(client, caplog):
    """468 carries a body as of decision 114 — a fixed, non-distinguishing
    reason string identical on every 468 (src/api/status.py's
    no_result_response()), not the admission-error-specific text that
    triggered this particular one. responseAdapter should reflect that body,
    not be absent the way it was before decision 114."""
    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        # Wrong profile for /Geocode — admitted, but nothing to convert (§4.2).
        resp = client.post(GEOCODE, content=presence(tuple_(GEO_CHUNK)))
    assert resp.status_code == 468
    assert resp.json() == {"reason": "No result was derivable for the query."}

    events = _log_events(caplog)
    resp_evt = events[-1]
    assert resp_evt["responseStatus"] == 468
    assert json.loads(resp_evt["responseAdapter"]) == {
        "reason": "No result was derivable for the query."
    }


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def test_query_ids_are_unique_per_request(client, caplog):
    """Each request mints its own queryId — nothing is reused or hardcoded
    across requests, which is what makes the id useful for correlation in a
    Logging Service that receives many requests."""
    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        client.post(GEOCODE, content=b"<presence><unclosed>")
        client.post(GEOCODE, content=b"<presence><unclosed>")

    events = _log_events(caplog)
    query_ids = [e["queryId"] for e in events if e["logEventType"] == "GcsQueryLogEvent"]
    assert len(query_ids) == 2
    assert query_ids[0] != query_ids[1]


# ---------------------------------------------------------------------------
# Serialization / infrastructure stamping
# ---------------------------------------------------------------------------

def test_camel_case_keys_in_json(success_client, caplog):
    """All JSON keys in emitted events use lowerCamelCase (§4.12.3.1)."""
    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        success_client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))

    events = _log_events(caplog)
    assert events
    for evt in events:
        for key in evt:
            assert "_" not in key, f"Key {key!r} contains underscore — expected camelCase"


def test_agency_id_stamped_from_identity(success_client, caplog):
    """agencyId on emitted events comes from core's ElementIdentity, not from
    the event kwargs the call sites pass — src/logging/log_events.py's
    classes never set it themselves."""
    from src import runtime_state

    with caplog.at_level(logging.INFO, logger="i3_fe_core.logging.logging_client"):
        success_client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))

    events = _log_events(caplog)
    assert events
    assert events[0]["agencyId"] == runtime_state.logging_client._identity.agency_id
