"""Plumbing-pass smoke tests.

Verifies that the wiring this pass delivered actually answers: the Versions
entry point, the operational endpoints, the four conversion resources, and the
schema stack. No conversion behaviour is asserted — there is none yet.
"""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")


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

    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    # Hermetic: never load GIS data, whatever the developer's .env says.
    # These tests assert plumbing, not conversion, and loading the real
    # GeoPackage costs ~37 s cold. test_ready_is_503_without_gis_data depends
    # on this being empty.
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    with TestClient(server.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Versions (i3 §4.12, spec §A.1)
# ---------------------------------------------------------------------------

def test_versions_is_a_single_entry_point(client):
    """Spec §3.9.1 / decision 34: ONE web service, ONE /Versions covering both
    operations. The YAML places it at the /Gcs base, above the /Gcs/v1 the two
    operations sit on."""
    resp = client.get("/Gcs/Versions")
    assert resp.status_code == 200
    body = resp.json()
    assert "fingerprint" in body
    assert isinstance(body["versions"], list) and len(body["versions"]) == 1
    entry = body["versions"][0]
    assert isinstance(entry["major"], int)
    assert isinstance(entry["minor"], int)
    # serviceInfo is CONDITIONAL and the GCS defines none.
    assert "serviceInfo" not in entry


def test_versions_advertises_the_enhanced_interface(client):
    """Spec §3.9.2 / decision 35: the i3-improved resources are discovered
    through the Versions vendor parameter — i3's own sanctioned hook."""
    entry = client.get("/Gcs/Versions").json()["versions"][0]
    assert "GeocodeEnhanced" in entry["vendor"]
    assert "ReverseGeocodeEnhanced" in entry["vendor"]


# ---------------------------------------------------------------------------
# Operational endpoints (spec §3.9.4)
# ---------------------------------------------------------------------------

def test_health_is_liveness_and_stays_200(client):
    """/health is liveness: 200 while the process is up, even with no GIS data
    loaded. The traffic-gating role belongs to /ready."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    for field in ("status", "elementState", "ntpHealthy"):
        assert field in body, f"core conformance requires /health.{field}"


def test_ready_is_503_without_gis_data(client):
    """No GeoPackage is provisioned in the test environment, so /ready must
    report 503 — a GCS with no GIS data can convert nothing. Unlike LVF there
    is no routing-only exemption."""
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["ready"] is False


# ---------------------------------------------------------------------------
# Conversion resources (spec §3.9.1, §3.9.2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path,profile",
    [
        ("/Gcs/v1/Geocode", "civic"),
        ("/Gcs/v1/ReverseGeocode", "geodetic"),
        ("/Gcs/v1/GeocodeEnhanced", "civic"),
        ("/Gcs/v1/ReverseGeocodeEnhanced", "geodetic"),
    ],
)
def test_conversion_routes_are_mounted(client, path, profile):
    """All four resources exist and are reachable under the /Gcs/v1 server base
    the normative YAML declares.

    Each is posted a request that PASSES Stage 0 admission, so what is asserted
    is the route reaching the engine rather than an admission rejection.

    This client has no GIS data loaded and no scorer registered, so the engine
    answers rather than converting — 468 where it searched and found nothing,
    454 where §6.5's injected scoring function is absent. Which of the two
    depends only on the order the handler reaches them, and neither is the point
    here: what matters is that the code is inside the §4.5 closed set
    (200/307/454/468/469, spec §1.2.1, decision 2). The 501 build-state
    placeholder this test used to assert is gone, along with the helper that
    emitted it.
    """
    from src.api.status import STATUS_SET
    from tests.conformance.test_admission import (
        CIVIC_CHUNK,
        GEO_CHUNK,
        presence,
        tuple_,
    )

    chunk = CIVIC_CHUNK if profile == "civic" else GEO_CHUNK
    resp = client.post(path, content=presence(tuple_(chunk)))
    assert resp.status_code in STATUS_SET
    assert resp.status_code != 501


def test_conversion_routes_reject_get(client):
    """i3 §4.5: both operations are POST."""
    assert client.get("/Gcs/v1/Geocode").status_code == 405


# ---------------------------------------------------------------------------
# Schema stack (spec §4.1, schemas/README.md)
# ---------------------------------------------------------------------------

def test_master_schema_compiles():
    from src.app import lifecycle

    schema = lifecycle._load_schema()
    assert schema is not None, "schemas/gcs-pidflo.xsd failed to compile"


def test_master_schema_validates_both_directions():
    """The point of the master wrapper: RFC 4119's <location-info> is
    xs:any lax, so validating against the envelope alone would silently accept
    any payload. Spec §4.1 requires 454 on schema-invalid input, which is only
    enforceable if the validator descends into the civic and geodetic content.
    """
    from lxml import etree

    from src.app import lifecycle

    schema = lifecycle._load_schema()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)

    civic = b"""<?xml version="1.0" encoding="UTF-8"?>
<presence xmlns="urn:ietf:params:xml:ns:pidf"
          xmlns:gp="urn:ietf:params:xml:ns:pidf:geopriv10"
          xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr"
          entity="pres:gcs-test@example.com">
  <tuple id="t1"><status><gp:geopriv>
    <gp:location-info><ca:civicAddress>
      <ca:country>US</ca:country><ca:A1>ND</ca:A1><ca:A3>Bismarck</ca:A3>
      <ca:RD>State</ca:RD><ca:STS>Street</ca:STS><ca:HNO>3401</ca:HNO>
    </ca:civicAddress></gp:location-info>
    <gp:usage-rules/>
  </gp:geopriv></status></tuple>
</presence>"""

    # An RFC 5491 §5 GeoShape — spec §9 accepts all eight shapes on input.
    geodetic = b"""<?xml version="1.0" encoding="UTF-8"?>
<presence xmlns="urn:ietf:params:xml:ns:pidf"
          xmlns:gp="urn:ietf:params:xml:ns:pidf:geopriv10"
          xmlns:gml="http://www.opengis.net/gml"
          xmlns:gs="http://www.opengis.net/pidflo/1.0"
          xmlns:conf="urn:ietf:params:xml:ns:geopriv:conf"
          entity="pres:gcs-test@example.com">
  <tuple id="t1"><status><gp:geopriv>
    <gp:location-info>
      <gs:Circle srsName="urn:ogc:def:crs:EPSG::4326">
        <gml:pos>46.828121 -100.883898</gml:pos>
        <gs:radius uom="urn:ogc:def:uom:EPSG::9001">250</gs:radius>
      </gs:Circle>
      <conf:confidence pdf="normal">95</conf:confidence>
    </gp:location-info>
    <gp:usage-rules/>
  </gp:geopriv></status></tuple>
</presence>"""

    assert schema.validate(etree.fromstring(civic, parser))
    assert schema.validate(etree.fromstring(geodetic, parser))

    # An undeclared element in a KNOWN namespace must fail. This is the case a
    # lax validator without the imports would wave through.
    bad = civic.replace(b"<ca:HNO>3401</ca:HNO>", b"<ca:NOPE>x</ca:NOPE>")
    assert not schema.validate(etree.fromstring(bad, parser))

    # RFC 3863 makes `entity` use="required" — the attribute spec §8.3 has to
    # populate for a document with no presentity.
    no_entity = civic.replace(b' entity="pres:gcs-test@example.com"', b"")
    assert not schema.validate(etree.fromstring(no_entity, parser))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_ambiguity_tolerance_is_required(monkeypatch):
    """GCS_AMBIGUITY_TOLERANCE_M deliberately has no default: §6.3 names no
    value and Appendix C item (a) does not list it among the deferred
    defaults."""
    from src import runtime_state
    from src.app import lifecycle

    monkeypatch.setattr(runtime_state, "_ambiguity_tolerance_m", None)
    with pytest.raises(RuntimeError, match="GCS_AMBIGUITY_TOLERANCE_M"):
        lifecycle.validate_config()


def test_rcl_offset_must_be_positive(monkeypatch):
    """Spec §7.3: the offset MUST never place the returned position exactly on
    the centerline itself."""
    from src import runtime_state
    from src.app import lifecycle

    monkeypatch.setattr(runtime_state, "_rcl_offset_m", 0.0)
    with pytest.raises(RuntimeError, match="GCS_RCL_OFFSET_M"):
        lifecycle.validate_config()
