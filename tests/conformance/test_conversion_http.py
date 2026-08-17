"""The four resources converting for real — §4-§8 forward, §9-§12 reverse.

test_admission_http.py covers Stage 0. This covers everything after it: the
engine reached, an answer assembled, a PIDF-LO built, and the §3.9.1 wrapper
around it. The scorers are injected (§6.5 and §10.6 are withheld as proprietary
tuning), so these tests supply the trivial ones in scoring_stubs.py.
"""

from __future__ import annotations

import json
import os

import pytest
from lxml import etree
from starlette.testclient import TestClient

from src.api.status import STATUS_SET
from src.api.wire.xml_ns import (
    NS_CIVIC,
    NS_GEOPRIV,
    NS_GML,
    Q_METHOD,
    XML_PARSER,
    q,
)
from src.gis.records import RCLRecord, SSAPRecord
from tests.conformance import scoring_stubs
from tests.conformance.test_admission import CIVIC_CHUNK, GEO_CHUNK, presence, tuple_

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")

GEOCODE = "/Gcs/v1/Geocode"
REVERSE = "/Gcs/v1/ReverseGeocode"
GEOCODE_ENH = "/Gcs/v1/GeocodeEnhanced"
REVERSE_ENH = "/Gcs/v1/ReverseGeocodeEnhanced"

#: Where the fixture data sits. The reverse queries below aim here.
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


#: The centerline runs ~55 m south of the address point rather than through it.
#: Placing both at the same spot would make §10.4's NGUID tie-break decide which
#: layer answers, which is realistic enough but makes every reverse assertion
#: below depend on a string comparison rather than on the geometry under test.
_RCL_LAT = LAT - 0.0005


def _rcl(fid=9, **kwargs) -> RCLRecord:
    kwargs.setdefault("NGUID", f"{{RCL-{fid}}}")
    kwargs.setdefault(
        "geometry_wkt",
        f"LINESTRING ({LON - 0.004} {_RCL_LAT}, {LON + 0.004} {_RCL_LAT})",
    )
    kwargs.setdefault("St_Name", "State")
    kwargs.setdefault("St_PosTyp", "Street")
    kwargs.setdefault("A2_L", "Burleigh")
    kwargs.setdefault("A2_R", "Burleigh")
    kwargs.setdefault("FromAddr_L", 3400)
    kwargs.setdefault("ToAddr_L", 3500)
    kwargs.setdefault("Parity_L", "E")
    return RCLRecord(fid=fid, **kwargs)


@pytest.fixture()
def client(monkeypatch):
    """A service with one address point, one centerline, and trivial scorers."""
    from src import server
    from src.gis import provisioning

    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    monkeypatch.setattr(provisioning, "_ssap", [_ssap()])
    monkeypatch.setattr(provisioning, "_rcl", [_rcl()])
    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def street_only_client(monkeypatch):
    """Centerlines but no address points — the ladder falls to rungs 2 and 3."""
    from src import server
    from src.gis import provisioning

    scoring_stubs.install(monkeypatch)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    monkeypatch.setattr(provisioning, "_ssap", [])
    monkeypatch.setattr(provisioning, "_rcl", [_rcl()])
    with TestClient(server.app) as c:
        yield c


def _pidf(resp, field: str) -> etree._Element:
    body = resp.json()
    assert field in body, body
    return etree.fromstring(body[field].encode("utf-8"), XML_PARSER)


def _point_chunk(lat=LAT, lon=LON) -> str:
    return (
        f'<gml:Point xmlns:gml="{NS_GML}" srsName="urn:ogc:def:crs:EPSG::4326">'
        f"<gml:pos>{lat} {lon}</gml:pos></gml:Point>"
    )


# ---------------------------------------------------------------------------
# The closed status set (§1.2.1, §2.1, decision 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,body", [
    (GEOCODE, presence(tuple_(CIVIC_CHUNK))),
    (REVERSE, presence(tuple_(GEO_CHUNK))),
    (GEOCODE_ENH, presence(tuple_(CIVIC_CHUNK))),
    (REVERSE_ENH, presence(tuple_(GEO_CHUNK))),
    (GEOCODE, presence(tuple_(GEO_CHUNK))),            # wrong profile -> 468
    (REVERSE, presence(tuple_(CIVIC_CHUNK))),          # wrong profile -> 468
    (GEOCODE, b"<presence><unclosed>"),                # malformed  -> 454
    (REVERSE, b"not xml at all"),                      # malformed  -> 454
    (GEOCODE, b""),                                    # empty      -> 454
    (REVERSE, presence(tuple_('<gml:Point xmlns:gml="http://www.opengis.net/gml"/>'))),
])
def test_no_resource_ever_emits_a_status_outside_the_closed_set(client, path, body):
    """i3 §4.5's set is closed to 200/307/454/468/469 and this service mints
    nothing outside it. 501 gets its own assertion because it is the one that
    used to be here: a build-state placeholder is a defect in a deployed GCS,
    not a documented departure."""
    resp = client.post(path, content=body, follow_redirects=False)
    assert resp.status_code in STATUS_SET
    assert resp.status_code != 501


def test_the_enhanced_resources_share_the_closed_set(client):
    """§1.2.1 scopes the set to the service, not to the strict paths. Being
    non-i3 does not license minting a code."""
    resp = client.post(GEOCODE_ENH, content=presence(tuple_(GEO_CHUNK)))
    assert resp.status_code == 468


# ---------------------------------------------------------------------------
# Forward — §6, §7, §8.1
# ---------------------------------------------------------------------------

def test_geocode_returns_a_pidf_lo_carrying_a_position(client):
    resp = client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))
    assert resp.status_code == 200

    document = _pidf(resp, "pidfLoGeo")
    point = document.find(f".//{q(NS_GML, 'Point')}")
    assert point is not None

    latitude, longitude = point[0].text.split()[:2]
    assert float(latitude) == pytest.approx(LAT, abs=1e-5)
    assert float(longitude) == pytest.approx(LON, abs=1e-5)


def test_the_strict_forward_response_does_not_echo_the_civic_address(client):
    """§8.1 — pidfLoGeo carries the geodetic representation ONLY. RFC 5491
    describes what a PIDF-LO may contain and has no opinion on what a Geocode
    response should contain; "the format permits it" is not "the standard asks
    for it" (§1.2.1). A fuzzy match is therefore indistinguishable from an exact
    one here, which is the deficiency carried faithfully."""
    resp = client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))
    document = _pidf(resp, "pidfLoGeo")

    assert document.find(f".//{q(NS_CIVIC, 'civicAddress')}") is None
    assert document.find(f".//{q(NS_CIVIC, 'RD')}") is None


def test_the_strict_forward_response_carries_no_score_or_rank(client):
    """The other half of §8.1. Nothing in the body names a score, a rank, a
    match type or a Placement Method — there is no i3 field for any of them."""
    resp = client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))
    assert set(resp.json()) == {"pidfLoGeo"}

    lowered = resp.json()["pidfLoGeo"].lower()
    for forbidden in ("matchscore", "locationtype", "placement", "rank"):
        assert forbidden not in lowered


def test_a_street_level_query_returns_the_segment_line_not_a_point(
    street_only_client,
):
    """§7.4 / decision 30 — rung 3 is the load-bearing case. There is no basis
    to collapse a street-level match to one position, so the line itself is
    returned; it is the honest representation of what is known and its own
    uncertainty signal. No Circle, no Ellipse, nothing invented."""
    no_hno = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "")
    resp = street_only_client.post(GEOCODE, content=presence(tuple_(no_hno)))
    assert resp.status_code == 200

    document = _pidf(resp, "pidfLoGeo")
    line = document.find(f".//{q(NS_GML, 'LineString')}")
    assert line is not None
    assert document.find(f".//{q(NS_GML, 'Point')}") is None


def test_a_line_answer_declares_4326_end_to_end(street_only_client):
    """Decision 85 (resolves Q22) — this asserted srsName was absent while the
    abstention stood. The whole path now carries the CRS: Candidate.crs reports
    CRS_2D, ForwardAnswer.crs inherits it, and the serialiser writes it onto the
    LineString. The coordinate list is 2D to match — the RCL layer's per-vertex
    Z is an export artifact and is dropped (§10.5)."""
    no_hno = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "")
    resp = street_only_client.post(GEOCODE, content=presence(tuple_(no_hno)))

    line = _pidf(resp, "pidfLoGeo").find(f".//{q(NS_GML, 'LineString')}")
    assert line.get("srsName") == "urn:ogc:def:crs:EPSG::4326"
    pos_list = line[0]
    assert pos_list.get("srsDimension") == "2"
    assert len(pos_list.text.split()) % 2 == 0


def test_an_interpolated_house_number_returns_a_point(street_only_client):
    """Rung 2 — the segment can carry 3450, so it is placed on it (§7.2)."""
    with_hno = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "<ca:HNO>3450</ca:HNO>")
    resp = street_only_client.post(GEOCODE, content=presence(tuple_(with_hno)))
    assert resp.status_code == 200
    assert _pidf(resp, "pidfLoGeo").find(f".//{q(NS_GML, 'Point')}") is not None


# ---------------------------------------------------------------------------
# Reverse — §10, §11, §12.1
# ---------------------------------------------------------------------------

def test_reverse_geocode_returns_a_civic_address(client):
    resp = client.post(REVERSE, content=presence(tuple_(_point_chunk())))
    assert resp.status_code == 200

    document = _pidf(resp, "pidfLoAddress")
    assert document.find(f".//{q(NS_CIVIC, 'RD')}").text == "State"
    assert document.find(f".//{q(NS_CIVIC, 'HNO')}").text == "3401"
    assert document.find(f".//{q(NS_CIVIC, 'A2')}").text == "Burleigh"


def test_the_strict_reverse_response_carries_the_address_and_nothing_else(client):
    """§12.1 — no rank, no score, no distance, no containment flag, no Placement
    Method, and no indication that a house number was interpolated rather than
    read. Everything §10 and §11 computed is discarded at this boundary."""
    resp = client.post(REVERSE, content=presence(tuple_(_point_chunk())))
    assert set(resp.json()) == {"pidfLoAddress"}

    lowered = resp.json()["pidfLoAddress"].lower()
    for forbidden in ("distance", "contained", "synthes", "matchscore"):
        assert forbidden not in lowered


def test_a_point_in_open_water_is_468_not_a_distant_address(client):
    """§12.3 — the radius is mandatory for a reason worth restating: without
    one, a point in open water reverse geocodes to whatever unfortunate address
    is nearest and returns 200."""
    far = _point_chunk(lat=47.900000, lon=-102.500000)
    resp = client.post(REVERSE, content=presence(tuple_(far)), follow_redirects=False)
    assert resp.status_code == 468


@pytest.mark.parametrize("shape", ["Circle", "Polygon"])
def test_reverse_accepts_shapes_other_than_point(client, shape):
    """§9 / decision 37 — accepting only a Point would be a restriction i3 does
    not impose."""
    if shape == "Circle":
        chunk = (
            '<gs:Circle xmlns:gs="http://www.opengis.net/pidflo/1.0" '
            f'xmlns:gml="{NS_GML}"><gml:pos>{LAT} {LON}</gml:pos>'
            '<gs:radius uom="urn:ogc:def:uom:EPSG::9001">100</gs:radius></gs:Circle>'
        )
    else:
        chunk = (
            f'<gml:Polygon xmlns:gml="{NS_GML}"><gml:exterior><gml:LinearRing>'
            f"<gml:posList>{LAT - 0.001} {LON - 0.001} {LAT + 0.001} {LON - 0.001} "
            f"{LAT + 0.001} {LON + 0.001} {LAT - 0.001} {LON - 0.001}</gml:posList>"
            "</gml:LinearRing></gml:exterior></gml:Polygon>"
        )
    resp = client.post(REVERSE, content=presence(tuple_(chunk)))
    assert resp.status_code == 200


def test_a_non_numeric_coordinate_is_caught_by_schema_validation(client):
    """Admission gets to this one first — gml:pos is a doubleList, so the XSD
    rejects it before the wire layer is asked to read it (§4.1)."""
    chunk = f'<gml:Point xmlns:gml="{NS_GML}"><gml:pos>north west</gml:pos></gml:Point>'
    resp = client.post(REVERSE, content=presence(tuple_(chunk)))
    assert resp.status_code == 454
    assert "schema validation" in resp.json()["reason"]


def test_a_schema_valid_but_unreadable_shape_is_454(client):
    """A Sphere with a 2D centre passes the XSD — gml:pos does not constrain the
    ordinate count — but is not a readable solid. Refusing beats defaulting the
    height to zero, which would be a specific claim about height the caller did
    not make (decision 55). Well-formed but unreadable is the same class of
    failure as a schema violation, so the same code and a reason (§4.1)."""
    chunk = (
        '<gs:Sphere xmlns:gs="http://www.opengis.net/pidflo/1.0" '
        f'xmlns:gml="{NS_GML}"><gml:pos>{LAT} {LON}</gml:pos>'
        '<gs:radius uom="urn:ogc:def:uom:EPSG::9001">50</gs:radius></gs:Sphere>'
    )
    resp = client.post(REVERSE, content=presence(tuple_(chunk)))
    assert resp.status_code == 454
    assert "could not be read" in resp.json()["reason"]


# ---------------------------------------------------------------------------
# §8.3 — the PIDF-LO envelope (decisions 12 and 33)
# ---------------------------------------------------------------------------

def test_the_input_entity_is_echoed_onto_the_response(client):
    """Decision 12 — where the input carries an entity it is echoed. The
    location still belongs to that presentity; the GCS transformed its
    representation, not its ownership."""
    body = presence(tuple_(CIVIC_CHUNK), entity="pres:caller@psap.example.net")
    resp = client.post(GEOCODE, content=body)
    assert _pidf(resp, "pidfLoGeo").get("entity") == "pres:caller@psap.example.net"


def test_an_absent_entity_becomes_an_unlinked_pseudonym():
    """RFC 5985 §6.6 / RFC 6753 §6.2 — a location server MUST generate a unique
    unlinked presentity URI where it has none. Tested at the builder because
    RFC 3863 makes the attribute mandatory on input, so a request without one
    cannot reach the handler."""
    from src.api.wire import pidf_xml

    first = pidf_xml.build_presence([]).get("entity")
    second = pidf_xml.build_presence([]).get("entity")

    assert first.startswith("pres:")
    # "Unlinked" is the operative word: a reused pseudonym would be a
    # correlation handle for tracking a caller across requests.
    assert first != second


def test_usage_rules_pass_through_unchanged(client):
    """§8.3 — the GCS is never a Rule Maker. retransmission-allowed is copied
    verbatim; nothing is added, removed or defaulted."""
    chunk = tuple_(CIVIC_CHUNK).replace(
        "<gp:usage-rules/>",
        '<gp:usage-rules><gbp:retransmission-allowed '
        'xmlns:gbp="urn:ietf:params:xml:ns:pidf:geopriv10:basicPolicy">'
        "true</gbp:retransmission-allowed></gp:usage-rules>",
    )
    resp = client.post(GEOCODE, content=presence(chunk))
    document = _pidf(resp, "pidfLoGeo")

    rules = document.find(f".//{q(NS_GEOPRIV, 'usage-rules')}")
    assert rules is not None
    assert rules[0].text == "true"


def test_method_is_never_emitted(client):
    """Decision 33 — RFC 4119 §2.2.3 limits <method> to an IANA registry of
    device-positioning methods (GPS, A-GPS, Manual, DHCP, Triangulation, Cell,
    802.11). The GCS matches a GIS record whose provenance maps to none of them,
    so emitting one would be a guess presented as metadata. Not emitted even
    when the input supplies one."""
    chunk = tuple_(CIVIC_CHUNK).replace(
        "<gp:usage-rules/>",
        "<gp:usage-rules/><gp:method>GPS</gp:method>",
    )
    resp = client.post(GEOCODE, content=presence(chunk))
    assert _pidf(resp, "pidfLoGeo").find(f".//{Q_METHOD}") is None


def test_the_response_validates_against_the_master_schema(client):
    """The service must be able to consume its own output: §14.1's round trip
    means a Geocode response is a ReverseGeocode request."""
    from src.app import lifecycle

    schema = lifecycle._load_schema()
    assert schema is not None

    for path, chunk, field in (
        (GEOCODE, CIVIC_CHUNK, "pidfLoGeo"),
        (REVERSE, _point_chunk(), "pidfLoAddress"),
    ):
        resp = client.post(path, content=presence(tuple_(chunk)))
        assert resp.status_code == 200
        assert schema.validate(_pidf(resp, field)), schema.error_log.last_error


# ---------------------------------------------------------------------------
# The enhanced resources — §3.9.2, §8.2, §12.2
# ---------------------------------------------------------------------------

def test_the_enhanced_forward_response_carries_the_full_matched_record(client):
    """§8.2 / decision 11 — civic AND geodetic together, not a bare geometry, so
    a client that queried "101 Main St" and matched "101 Mayne St" can see the
    substitution by diffing the record against its query."""
    resp = client.post(GEOCODE_ENH, content=presence(tuple_(CIVIC_CHUNK)))
    assert resp.status_code == 200

    candidates = resp.json()["candidates"]
    assert len(candidates) == 1

    document = etree.fromstring(candidates[0]["pidfLo"].encode("utf-8"), XML_PARSER)
    assert document.find(f".//{q(NS_CIVIC, 'RD')}").text == "State"
    assert document.find(f".//{q(NS_GML, 'Point')}") is not None


def test_the_enhanced_response_carries_the_three_field_quality_model(client):
    """§7.4 — matchScore and locationType are orthogonal and both travel so a
    consumer can re-rank on either; confidence is derived from the two."""
    resp = client.post(GEOCODE_ENH, content=presence(tuple_(CIVIC_CHUNK)))
    candidate = resp.json()["candidates"][0]

    assert candidate["matchScore"] == 100.0
    assert candidate["locationType"] == "ADDRESS_POINT"
    # matchScore scaled to the ADDRESS_POINT ceiling of 80.
    assert candidate["confidence"] == pytest.approx(80.0)
    assert candidate["matchType"] == "Address"


def test_the_enhanced_reverse_response_carries_distance_and_containment(client):
    """§12.2 — the disclosure that pays for §10.5's uncorrected centerline bias.
    A caller who can see the distance can see how close the call was."""
    resp = client.post(REVERSE_ENH, content=presence(tuple_(_point_chunk())))
    assert resp.status_code == 200

    candidate = resp.json()["candidates"][0]
    assert candidate["distanceMeters"] == pytest.approx(0.0, abs=1.0)
    assert candidate["contained"] is False  # a Point has no area (§10.3)
    assert candidate["houseNumberSynthesised"] is False


def test_rank_1_is_the_same_answer_on_both_interfaces(client):
    """§2.2 / decision 8 — one engine feeds both, and GCS_MIN_MATCH_SCORE floors
    admission upstream of both response assemblies, so neither interface sees a
    candidate the other does not."""
    strict = client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))
    enhanced = client.post(GEOCODE_ENH, content=presence(tuple_(CIVIC_CHUNK)))

    strict_point = _pidf(strict, "pidfLoGeo").find(f".//{q(NS_GML, 'pos')}").text
    enhanced_doc = etree.fromstring(
        enhanced.json()["candidates"][0]["pidfLo"].encode("utf-8"), XML_PARSER
    )
    assert enhanced_doc.find(f".//{q(NS_GML, 'pos')}").text == strict_point


def test_a_dropped_address_number_is_reported_on_the_enhanced_interface(
    street_only_client,
):
    """Decision 63 — the drop is reported so a caller handed a street-level
    answer can see the house number was the reason, rather than inferring it
    from a lower score. The request still answers: 200, not a rejection."""
    bad = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "<ca:HNO>not-a-number</ca:HNO>")
    resp = street_only_client.post(GEOCODE_ENH, content=presence(tuple_(bad)))

    assert resp.status_code == 200
    dropped = resp.json()["droppedElements"]
    assert len(dropped) == 1
    assert dropped[0]["element"] == "ca:HNO"
    assert dropped[0]["value"] == "not-a-number"


def test_a_dropped_address_number_still_answers_on_the_strict_interface(
    street_only_client,
):
    """The strict interface has no field to report the drop, so it reports
    nothing and answers anyway — degraded to the street-level match decision 63
    predicts. What it must not do is reject."""
    bad = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "<ca:HNO>not-a-number</ca:HNO>")
    resp = street_only_client.post(GEOCODE, content=presence(tuple_(bad)))

    assert resp.status_code == 200
    assert _pidf(resp, "pidfLoGeo").find(f".//{q(NS_GML, 'LineString')}") is not None


def test_the_location_count_surfaces_only_on_the_enhanced_interface(client):
    """§4.2 / decision 50 — i3 mandates converting the first location and gives
    no way to signal that the others were discarded. This is the only interface
    in the service where that discard is visible at all (§16)."""
    two = presence(tuple_(CIVIC_CHUNK, tid="t1"), tuple_(CIVIC_CHUNK, tid="t2"))

    enhanced = client.post(GEOCODE_ENH, content=two)
    assert enhanced.json()["locationCount"] == 2

    strict = client.post(GEOCODE, content=two)
    assert set(strict.json()) == {"pidfLoGeo"}


# ---------------------------------------------------------------------------
# The scorer seam (§6.5, §10.6, Appendix C item (d))
# ---------------------------------------------------------------------------

def test_a_missing_scorer_is_454_and_not_a_new_status_code(monkeypatch):
    """§6.5's formula is withheld and injected. A service asked to convert
    before one was installed is a residual internal error, which §8.4 assigns to
    454 — emphatically not 468, which asserts that a search was performed."""
    from src import server
    from src.app import lifecycle
    from src.engine import scoring_registry

    # src/app/lifecycle.py now registers the real scoring.py functions at
    # startup (unconditionally — see _register_scorers' docstring), which
    # would immediately overwrite the None below. Stubbing registration out
    # is what lets this test still exercise "nothing was ever registered".
    monkeypatch.setattr(lifecycle, "_register_scorers", lambda: None)
    monkeypatch.setattr(scoring_registry, "_forward", None)
    monkeypatch.setattr(scoring_registry, "_reverse", None)
    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    monkeypatch.setenv("GCS_GPKG_PATH", "")

    with TestClient(server.app) as c:
        resp = c.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))

    assert resp.status_code == 454
    assert "scoring function" in resp.json()["reason"]


def test_the_response_body_is_json_carrying_xml_as_a_string(client):
    """§3.9.1 — the YAML declares application/xml around a JSON-shaped object,
    which is incoherent as written. This is the only reading under which its
    declared schemas are implementable, and the defect is a §16 row."""
    resp = client.post(GEOCODE, content=presence(tuple_(CIVIC_CHUNK)))

    assert resp.headers["content-type"].startswith("application/json")
    payload = json.loads(resp.text)
    assert isinstance(payload["pidfLoGeo"], str)
    assert payload["pidfLoGeo"].lstrip().startswith("<?xml")
