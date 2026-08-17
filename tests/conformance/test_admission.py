"""Stage 0 admission — spec §4.1, §4.2, §5, §9.

Exercises the admission module directly (no HTTP) plus the four resources over
HTTP, so the status codes on the wire are asserted as well as the logic.
"""

from __future__ import annotations

import json
import os

import pytest
from lxml import etree

from src.api.admission import (
    AdmissionError,
    Profile,
    admit,
    decode_body,
    elect_location,
)

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")


@pytest.fixture(scope="module")
def schema():
    from src.app import lifecycle

    compiled = lifecycle._load_schema()
    assert compiled is not None
    return compiled


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

CIVIC_CHUNK = """<ca:civicAddress xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr">
        <ca:country>US</ca:country><ca:A1>ND</ca:A1><ca:A2>Burleigh</ca:A2>
        <ca:A3>Bismarck</ca:A3><ca:RD>State</ca:RD><ca:STS>Street</ca:STS>
        <ca:HNO>3401</ca:HNO>
      </ca:civicAddress>"""

GEO_CHUNK = """<gml:Point xmlns:gml="http://www.opengis.net/gml"
        srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>46.828121 -100.883898</gml:pos></gml:Point>"""


def presence(*containers: str, entity: str = "pres:someone@example.com") -> bytes:
    inner = "\n".join(containers)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<presence xmlns="urn:ietf:params:xml:ns:pidf"
          xmlns:dm="urn:ietf:params:xml:ns:pidf:data-model"
          xmlns:gp="urn:ietf:params:xml:ns:pidf:geopriv10"
          entity="{entity}">
{inner}
</presence>""".encode()


def geopriv(chunk: str) -> str:
    return f"""<gp:geopriv>
      <gp:location-info>{chunk}</gp:location-info>
      <gp:usage-rules/>
    </gp:geopriv>"""


def tuple_(chunk: str, tid: str = "t1") -> str:
    return f'  <tuple id="{tid}"><status>{geopriv(chunk)}</status></tuple>'


def device(chunk: str, did: str = "d1") -> str:
    return f'  <dm:device id="{did}">{geopriv(chunk)}</dm:device>'


def person(chunk: str, pid: str = "p1") -> str:
    return f'  <dm:person id="{pid}">{geopriv(chunk)}</dm:person>'


# ---------------------------------------------------------------------------
# §4.1 — body decoding
# ---------------------------------------------------------------------------

def test_raw_xml_body_accepted():
    doc = presence(tuple_(CIVIC_CHUNK))
    assert decode_body(doc, "application/xml").lstrip().startswith("<?xml")


def test_json_string_body_accepted():
    """The normative YAML declares the body application/json with
    schema type: string — i.e. the XML quoted and escaped."""
    doc = presence(tuple_(CIVIC_CHUNK))
    wrapped = json.dumps(doc.decode()).encode()
    assert decode_body(wrapped, "application/json") == doc.decode()


def test_empty_body_is_454():
    with pytest.raises(AdmissionError) as e:
        decode_body(b"   ", "application/json")
    assert e.value.status == 454


def test_json_body_that_is_not_a_string_is_454():
    with pytest.raises(AdmissionError) as e:
        decode_body(b'"{\\"a\\": 1}"'.replace(b'"{', b'{').replace(b'}"', b'}'), "application/json")
    assert e.value.status == 454


def test_body_that_is_neither_is_454():
    with pytest.raises(AdmissionError) as e:
        decode_body(b"3401 State Street", "text/plain")
    assert e.value.status == 454


# ---------------------------------------------------------------------------
# §4.1 — schema validation
# ---------------------------------------------------------------------------

def test_valid_civic_document_is_admitted(schema):
    result = admit(presence(tuple_(CIVIC_CHUNK)), "application/xml", Profile.CIVIC, schema)
    assert result.chunk.tag.endswith("civicAddress")
    assert result.entity == "pres:someone@example.com"
    assert result.usage_rules is not None
    assert result.location_count == 1


def test_malformed_xml_is_454(schema):
    with pytest.raises(AdmissionError) as e:
        admit(b"<presence><unclosed>", "application/xml", Profile.CIVIC, schema)
    assert e.value.status == 454
    assert "well-formed" in e.value.reason


def test_not_a_pidf_lo_is_454(schema):
    with pytest.raises(AdmissionError) as e:
        admit(b"<findService xmlns='urn:ietf:params:xml:ns:lost1'/>", "application/xml",
              Profile.CIVIC, schema)
    assert e.value.status == 454
    assert "PIDF-LO" in e.value.reason


def test_schema_invalid_is_454_not_468(schema):
    """§4.1: 468 is not used for schema failure — it asserts a search was
    performed."""
    doc = presence(tuple_(CIVIC_CHUNK)).replace(b"<ca:HNO>3401</ca:HNO>",
                                                b"<ca:BOGUS>x</ca:BOGUS>")
    with pytest.raises(AdmissionError) as e:
        admit(doc, "application/xml", Profile.CIVIC, schema)
    assert e.value.status == 454
    assert "schema validation" in e.value.reason


def test_missing_entity_attribute_is_454(schema):
    """RFC 3863 makes entity use="required"."""
    doc = presence(tuple_(CIVIC_CHUNK)).replace(b' entity="pres:someone@example.com"', b"")
    with pytest.raises(AdmissionError) as e:
        admit(doc, "application/xml", Profile.CIVIC, schema)
    assert e.value.status == 454


# ---------------------------------------------------------------------------
# §4.2 — RFC 5491 Rule #8 election
# ---------------------------------------------------------------------------

def _elect(doc: bytes):
    root = etree.fromstring(doc)
    return elect_location(root)


def test_rule8_device_beats_tuple():
    """Rule #8: priority to the first <device> containing a location."""
    _, elected_from, count = _elect(presence(tuple_(CIVIC_CHUNK), device(GEO_CHUNK)))
    assert elected_from == "device"
    assert count == 2


def test_rule8_tuple_beats_person():
    """Rule #8: <person> locations SHOULD only be used as a last resort — so
    tuple outranks person even though person appears first in the document."""
    _, elected_from, count = _elect(presence(person(CIVIC_CHUNK), tuple_(GEO_CHUNK)))
    assert elected_from == "tuple"
    assert count == 2


def test_rule8_person_used_as_last_resort():
    _, elected_from, _ = _elect(presence(person(CIVIC_CHUNK)))
    assert elected_from == "person"


def test_rule8_is_typed_precedence_not_document_order():
    """The whole point: a <device> later in the document still wins."""
    info, elected_from, count = _elect(
        presence(person(CIVIC_CHUNK), tuple_(CIVIC_CHUNK), device(GEO_CHUNK))
    )
    assert elected_from == "device"
    assert count == 3
    assert info[0].tag.endswith("Point")


def test_first_of_several_in_the_same_container_wins():
    info, _, count = _elect(presence(tuple_(CIVIC_CHUNK, "t1"), tuple_(GEO_CHUNK, "t2")))
    assert count == 2
    assert info[0].tag.endswith("civicAddress")


def test_empty_location_info_does_not_count_as_a_location():
    doc = presence(f'  <tuple id="t1"><status><gp:geopriv>'
                   f'<gp:location-info/><gp:usage-rules/></gp:geopriv></status></tuple>',
                   tuple_(CIVIC_CHUNK, "t2"))
    info, _, count = _elect(doc)
    assert count == 1
    assert info[0].tag.endswith("civicAddress")


def test_no_location_at_all_is_468():
    doc = presence('  <tuple id="t1"><status><basic>open</basic></status></tuple>')
    with pytest.raises(AdmissionError) as e:
        _elect(doc)
    assert e.value.status == 468


# ---------------------------------------------------------------------------
# §4.2 / decision 50 — the elected location is used as elected
# ---------------------------------------------------------------------------

def test_wrong_chunk_on_elected_location_is_468_not_a_search_for_a_better_one(schema):
    """decision 50: if the elected location does not carry the chunk the
    operation requires, return 468 rather than walking the document. Here the
    device carries geodetic and a tuple carries civic — Geocode must NOT fall
    through to the tuple.

    Note the element order: RFC 3863's <presence> content model is an
    xs:sequence of tuple*, note*, then xs:any ##other*, so a <dm:device> MUST
    follow every <tuple>. Document order and Rule #8 order therefore point in
    opposite directions for device-vs-tuple by construction — which is exactly
    why Rule #8 has to be a typed precedence."""
    doc = presence(tuple_(CIVIC_CHUNK), device(GEO_CHUNK))
    with pytest.raises(AdmissionError) as e:
        admit(doc, "application/xml", Profile.CIVIC, schema)
    assert e.value.status == 468
    assert "civic" in e.value.reason


def test_the_mirror_case_for_reversegeocode(schema):
    """§9 applies §4.2 unchanged in the reverse direction."""
    doc = presence(tuple_(GEO_CHUNK), device(CIVIC_CHUNK))
    with pytest.raises(AdmissionError) as e:
        admit(doc, "application/xml", Profile.GEODETIC, schema)
    assert e.value.status == 468
    assert "geodetic" in e.value.reason


def test_compound_location_selects_by_namespace_not_position(schema):
    """RFC 5491 Rule #7 puts the COARSE element first in a compound location,
    so position encodes coarseness rather than relevance and cannot be used to
    select by type (§4.2)."""
    compound = geopriv(GEO_CHUNK + CIVIC_CHUNK)
    doc = presence(f'  <tuple id="t1"><status>{compound}</status></tuple>')
    civic = admit(doc, "application/xml", Profile.CIVIC, schema)
    assert civic.chunk.tag.endswith("civicAddress")
    geo = admit(doc, "application/xml", Profile.GEODETIC, schema)
    assert geo.chunk.tag.endswith("Point")


def test_multi_location_count_is_captured_for_disclosure(schema):
    """i3 mandates the discard and gives no way to signal it; the count is
    carried so the enhanced interface can report it (decision 50, §16)."""
    doc = presence(tuple_(CIVIC_CHUNK, "t1"), tuple_(CIVIC_CHUNK, "t2"), person(CIVIC_CHUNK))
    result = admit(doc, "application/xml", Profile.CIVIC, schema)
    assert result.location_count == 3
    assert result.elected_from == "tuple"


# ---------------------------------------------------------------------------
# §5 — Structural Conformance: there is NO Gate 1
# ---------------------------------------------------------------------------

def test_civic_address_with_no_hno_is_admitted(schema):
    """§5 / decision 14: i3 §4.5 imposes no structural precondition on Geocode.
    A street-level query with no HNO is ACCEPTED and answered at rung 3.

    This is the case LVF rejects with <locationInvalid> at its Gate 1. The GCS
    must not. Asserted explicitly so the absence of a gate is a tested
    property rather than an accident of nobody having written one."""
    no_hno = CIVIC_CHUNK.replace("<ca:HNO>3401</ca:HNO>", "")
    result = admit(presence(tuple_(no_hno)), "application/xml", Profile.CIVIC, schema)
    assert result.chunk.tag.endswith("civicAddress")


def test_civic_address_with_only_a_street_is_admitted(schema):
    """The adjacent, more dangerous case §5 also permits: almost nothing is
    supplied. The honesty burden moves to uncertainty (§7.4), not admission."""
    sparse = """<ca:civicAddress xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr">
        <ca:RD>State</ca:RD></ca:civicAddress>"""
    result = admit(presence(tuple_(sparse)), "application/xml", Profile.CIVIC, schema)
    assert result.chunk.tag.endswith("civicAddress")


def test_empty_civic_address_is_admitted(schema):
    """Even a civicAddress with no children is admitted. It will find no
    candidate and yield 468 at §6.4 — but that is a search result, not a
    structural rejection, and the distinction is the whole of §5."""
    empty = '<ca:civicAddress xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr"/>'
    result = admit(presence(tuple_(empty)), "application/xml", Profile.CIVIC, schema)
    assert result.chunk.tag.endswith("civicAddress")


@pytest.mark.parametrize("shape_xml,name", [
    ('<gml:Point xmlns:gml="http://www.opengis.net/gml"><gml:pos>46.8 -100.8</gml:pos></gml:Point>',
     "Point"),
    ('<gs:Circle xmlns:gs="http://www.opengis.net/pidflo/1.0" '
     'xmlns:gml="http://www.opengis.net/gml"><gml:pos>46.8 -100.8</gml:pos>'
     '<gs:radius uom="urn:ogc:def:uom:EPSG::9001">250</gs:radius></gs:Circle>', "Circle"),
    ('<gs:Sphere xmlns:gs="http://www.opengis.net/pidflo/1.0" '
     'xmlns:gml="http://www.opengis.net/gml"><gml:pos>46.8 -100.8</gml:pos>'
     '<gs:radius uom="urn:ogc:def:uom:EPSG::9001">250</gs:radius></gs:Sphere>', "Sphere"),
])
def test_reverse_accepts_geoshapes_beyond_point(schema, shape_xml, name):
    """§9 / decision 37: all eight RFC 5491 §5 shapes are accepted. Restricting
    to Point would add a restriction i3 does not impose."""
    result = admit(presence(tuple_(shape_xml)), "application/xml", Profile.GEODETIC, schema)
    assert result.chunk.tag.endswith(name)
