"""Admission over HTTP — asserts the i3 §4.5 status codes actually on the wire.

test_admission.py exercises the logic; this exercises the four resources, the
§8.4 / §12.3 status selection, and the 307-vs-468 referral switch.
"""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from tests.conformance import scoring_stubs
from tests.conformance.test_admission import CIVIC_CHUNK, GEO_CHUNK, presence, tuple_

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")

GEOCODE = "/Gcs/v1/Geocode"
REVERSE = "/Gcs/v1/ReverseGeocode"
GEOCODE_ENH = "/Gcs/v1/GeocodeEnhanced"
REVERSE_ENH = "/Gcs/v1/ReverseGeocodeEnhanced"


class _FakeNtpClient:
    is_healthy = True
    offset = 0.0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


@pytest.fixture()
def client(monkeypatch):
    from src import server

    # A scorer must be registered or the engine raises before it searches, and
    # these tests are about admission, not about scoring (§6.5 is injected —
    # see tests/conformance/scoring_stubs.py). No GIS data is loaded, so an
    # admitted request searches an empty dataset and gets 468.
    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def referring_client(monkeypatch):
    """A client whose service has GCS_REFERRAL_URI configured."""
    from src import runtime_state, server

    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    monkeypatch.setattr(runtime_state, "_referral_uri", "https://gcs2.example.com/Gcs/v1")
    with TestClient(server.app) as c:
        yield c


# ---------------------------------------------------------------------------
# 454 — §4.1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [GEOCODE, REVERSE, GEOCODE_ENH, REVERSE_ENH])
def test_malformed_body_is_454_with_a_reason_on_every_resource(client, path):
    """§4.1 / decision 36: 454 on BOTH operations with a human-readable body
    reason. The normative YAML omits 454 from /ReverseGeocode entirely; that
    asymmetry is declined and recorded as a §16 row."""
    resp = client.post(path, content=b"<presence><unclosed>")
    assert resp.status_code == 454
    assert "well-formed" in resp.json()["reason"]


def test_schema_invalid_is_454_not_468(client):
    bad = presence(tuple_(CIVIC_CHUNK)).replace(b"<ca:HNO>3401</ca:HNO>",
                                                b"<ca:BOGUS>x</ca:BOGUS>")
    resp = client.post(GEOCODE, content=bad)
    assert resp.status_code == 454
    assert "schema validation" in resp.json()["reason"]


def test_json_string_body_is_accepted_over_http(client):
    """The normative YAML's declared encoding: application/json, type string."""
    import json as _json

    body = _json.dumps(presence(tuple_(CIVIC_CHUNK)).decode())
    resp = client.post(GEOCODE, content=body, headers={"content-type": "application/json"})
    # Admitted. This client has no GIS data, so the engine finds nothing and
    # returns 468 — the point is that it is not 454, which is what a rejected
    # body would produce.
    assert resp.status_code == 468


# ---------------------------------------------------------------------------
# 468 — §4.2 / decision 50
# ---------------------------------------------------------------------------

def test_geocode_with_only_a_geodetic_location_is_468(client):
    resp = client.post(GEOCODE, content=presence(tuple_(GEO_CHUNK)))
    assert resp.status_code == 468
    # Decision 114: a fixed, non-distinguishing reason travels on every 468,
    # not the admission-specific text that actually triggered this one.
    assert resp.json() == {"reason": "No result was derivable for the query."}


def test_reversegeocode_with_only_a_civic_location_is_468(client):
    resp = client.post(REVERSE, content=presence(tuple_(CIVIC_CHUNK)))
    assert resp.status_code == 468


def test_no_location_at_all_is_468(client):
    doc = presence('  <tuple id="t1"><status><basic>open</basic></status></tuple>')
    assert client.post(GEOCODE, content=doc).status_code == 468


# ---------------------------------------------------------------------------
# 307 — §3.6.2 / decision 34
# ---------------------------------------------------------------------------

def test_468_becomes_307_with_location_header_when_a_referral_is_configured(
    referring_client,
):
    """decision 34, confirmed against the normative YAML: the referral URI
    travels in the Location header of a 307. GeodeticData has no
    gcsReferralUri property at all, contradicting the §4.5 text's MUST."""
    resp = referring_client.post(
        GEOCODE, content=presence(tuple_(GEO_CHUNK)), follow_redirects=False
    )
    assert resp.status_code == 307
    assert resp.headers["location"] == "https://gcs2.example.com/Gcs/v1"


def test_454_is_never_converted_into_a_referral(referring_client):
    """A malformed request is not a scope problem — handing it to a peer GCS
    would only relocate the failure."""
    resp = referring_client.post(
        GEOCODE, content=b"<presence><unclosed>", follow_redirects=False
    )
    assert resp.status_code == 454


def test_468_without_a_referral_configured_stays_468(client):
    """§3.6.2 / decision 5: where none is configured, 468 is returned without a
    referral — a knowing, documented departure from i3 §4.5's MUST."""
    resp = client.post(GEOCODE, content=presence(tuple_(GEO_CHUNK)), follow_redirects=False)
    assert resp.status_code == 468
    assert "location" not in resp.headers


# ---------------------------------------------------------------------------
# §5 over the wire
# ---------------------------------------------------------------------------

def test_no_hno_reaches_the_engine_rather_than_being_rejected(client):
    """§5: no Gate 1. A street-level query is admitted and reaches the engine,
    which searches and finds nothing in an empty dataset — 468, the same code a
    query WITH a house number gets here.

    The assertion that matters is the negative one: not 454. A 454 would mean a
    structural precondition had been introduced that i3 does not have, and it
    would look identical to the caller whether it came from admission or from a
    gate. Compare with test_a_fully_valid_request_reaches_the_engine below: the
    two must agree, because the missing HNO must not change the outcome."""
    no_hno = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "")
    resp = client.post(GEOCODE, content=presence(tuple_(no_hno)))
    assert resp.status_code == 468


def test_a_fully_valid_request_reaches_the_engine(client):
    """Admitted, searched, nothing found — this client has no GIS data. 468 is
    §6.4's answer and 468 is what a conformant service returns for it."""
    assert client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK))).status_code == 468
    assert client.post(REVERSE, content=presence(tuple_(GEO_CHUNK))).status_code == 468
