"""§3.10 — the civic wire mapping, both directions (decisions 62 and 63).

The mapping is transcribed from NENA-STA-004.2-2024, which governs on any
disagreement. Where a test below encodes an expected decomposition, the citation
in its docstring is the standard's own example, not this implementation's
preference.
"""

from __future__ import annotations

import os

import pytest
from lxml import etree

from src.api.wire import civic_xml
from src.api.wire.civic_xml import ELEMENT_MAP, NO_WIRE_COUNTERPART
from src.api.wire.xml_ns import NS_CDX2, NS_CIVIC, NS_CIVIC_EXT, q
from src.engine.models import CIVIC_ELEMENTS, CivicAddress

os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")


def _civic_doc(inner: str) -> str:
    return (
        '<ca:civicAddress '
        'xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr" '
        'xmlns:cae="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr:ext" '
        'xmlns:cdx1="urn:nena:xml:ns:pidf:nenaCivicAddr" '
        'xmlns:cdx2="urn:nena:xml:ns:pidf:nenaCivicAddr2">'
        f"{inner}</ca:civicAddress>"
    )


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------

def test_every_mapped_column_is_a_real_civic_element():
    """§3.10's left column is STA-006.3 spelling, and the element model uses the
    same spelling — that identity is what makes §11.1 a copy (decision 62)."""
    for column, _, _ in ELEMENT_MAP:
        assert column in CIVIC_ELEMENTS, column


def test_the_table_and_the_no_counterpart_list_partition_the_vocabulary():
    """Every civic element is either mapped or explicitly unmapped with a
    reason. A third state — silently absent — is what this asserts against."""
    mapped = {column for column, _, _ in ELEMENT_MAP}
    assert mapped | set(NO_WIRE_COUNTERPART) == set(CIVIC_ELEMENTS)
    assert not (mapped & set(NO_WIRE_COUNTERPART))


def test_columns_with_no_counterpart_are_never_emitted():
    """§3.10, decision 62 — MSAGComm, the LSt_* legacy fields, AddCode,
    FloorIndex and a complete-form Unit have no PIDF-LO counterpart. They stay
    available to §6.5 scoring; they simply do not appear on the wire."""
    civic = CivicAddress(
        St_Name="16th",
        MSAGComm="BISMARCK",
        LSt_Name="SIXTEENTH",
        LSt_Typ="ST",
        AddCode="ND015",
        FloorIndex=3,
        Unit="APT 12",
    )
    rendered = civic_xml.to_string(civic)

    for value in ("BISMARCK", "SIXTEENTH", "ND015", "APT 12"):
        assert value not in rendered
    assert "16th" in rendered


def test_columns_with_no_counterpart_are_not_populated_from_the_wire():
    """The other half of decision 62. ca:UNIT is a real RFC 5139 element and is
    deliberately not mapped: the provisioned schema carries UnitPreTyp and
    UnitValue separately, and reconstructing a complete form would synthesise an
    element the caller did not send."""
    parsed = civic_xml.parse_document(
        _civic_doc("<ca:RD>16th</ca:RD><ca:UNIT>12</ca:UNIT>")
    )
    assert parsed.civic.St_Name == "16th"
    assert parsed.civic.Unit is None


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

def test_a_civic_address_round_trips_through_both_directions():
    """Read, write, read again. §14.1's round-trip requirement is about the two
    algorithm directions, but it cannot hold if the wire mapping is lossy."""
    original = CivicAddress(
        Country="US",
        A1="ND",
        A2="Burleigh",
        A3="Bismarck",
        A4="Hay Creek",
        A5="Northridge",
        Post_Comm="Bismarck",
        Post_Code="58503",
        PostCodeEx="1234",
        AddNum_Pre="194",
        Add_Number=3401,
        AddNum_Suf="B",
        AddNum_Cmp="194-3401B",
        St_PreMod="Old",
        St_PreDir="N",
        St_PreTyp="Avenue",
        St_PreSep="of the",
        St_Name="State",
        St_PosTyp="Street",
        St_PosDir="NW",
        St_PosMod="Extended",
        Site="Campus",
        SubSite="North Lot",
        Structure="Tower A",
        Wing="East",
        Floor="3",
        UnitPreTyp="APT",
        UnitValue="12",
        Room="311",
        Section="B",
        Row_="4",
        Seat="7",
        Addtl_Loc="Loading dock",
        Place_Type="office",
    )

    rendered = civic_xml.to_string(original)
    returned = civic_xml.parse_document(rendered).civic

    assert returned == original


def test_the_round_trip_keeps_the_address_number_an_integer():
    """STA-004.2 §3.3.3.5 types Address Number as a non-negative integer, and
    ca:HNO is xs:string on the wire — the type has to survive the crossing."""
    rendered = civic_xml.to_string(CivicAddress(Add_Number=3401, St_Name="State"))
    returned = civic_xml.parse_document(rendered).civic

    assert returned.Add_Number == 3401
    assert isinstance(returned.Add_Number, int)


def test_an_empty_element_is_omitted_rather_than_emitted_empty():
    """§11.4 — a sparse record produces a sparse address, not a padded one."""
    rendered = civic_xml.to_string(CivicAddress(St_Name="State"))
    assert "<ca:A2" not in rendered
    assert "<ca:RD>State</ca:RD>" in rendered


def test_the_mapping_uses_the_namespaces_the_table_names():
    """§1.4's prefixes carry meaning: HNP is cae: (RFC 6848), HNC is cdx2:
    (STA-004.2), and putting either in ca: would fail schema validation."""
    root = civic_xml.build(
        CivicAddress(AddNum_Pre="194", Add_Number=3, AddNum_Cmp="194-03")
    )
    assert root.find(q(NS_CIVIC_EXT, "HNP")) is not None
    assert root.find(q(NS_CDX2, "HNC")) is not None
    assert root.find(q(NS_CIVIC, "HNO")) is not None


# ---------------------------------------------------------------------------
# Decision 63 — the address number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("supplied,number,prefix,suffix", [
    # Every case below is an example STA-004.2 gives by name.
    ("123", 123, None, None),                 # §3.3.3.4
    ("701B", 701, None, "B"),                 # decision 63's own example
    ("123A", 123, None, "A"),                 # §3.3.4.4
    ("123-A", 123, None, "A"),                # §3.3.4.4
    ("123 A", 123, None, "A"),                # §3.3.4.4
    ("119½", 119, None, "½"),       # §3.3.3.4
    ("A19", 19, "A", None),                   # §3.3.2.8a, Puerto Rico
    ("5-5415", 5415, "5", None),              # §3.3.2.8b, Hawaii
    ("194-13", 13, "194", None),              # §3.3.2.8c, Queens
    ("194-03½", 3, "194", "½"),     # §3.3.3.8, worked through in full
    ("N89W16758", 16758, "N89W", None),       # §3.3.2.8d, Wisconsin
    ("W63N 645", 645, "W63N", None),          # §3.3.2.8d, Wisconsin
])
def test_a_complete_address_number_decomposes_per_sta_004_2(
    supplied, number, prefix, suffix
):
    """STA-004.2 §3.3.2-§3.3.4. Separators — spaces, hyphens, punctuation — are
    excluded from prefix and suffix and preserved in Address Number Complete.

    The Wisconsin cases are why the rule is "the last run of digits is the
    Address Number" rather than the first: the grid reference N89W itself
    contains digits, and §3.3.2.8d puts everything up to the last letter in the
    prefix."""
    parsed = civic_xml.parse_document(
        _civic_doc(f"<ca:RD>50th</ca:RD><ca:HNO>{supplied}</ca:HNO>")
    ).civic

    assert parsed.Add_Number == number
    assert parsed.AddNum_Pre == prefix
    assert parsed.AddNum_Suf == suffix


def test_701b_decomposes_and_preserves_its_original_form():
    """Decision 63's worked example, end to end."""
    parsed = civic_xml.parse_document(
        _civic_doc("<ca:RD>Main</ca:RD><ca:HNO>701B</ca:HNO>")
    ).civic

    assert parsed.Add_Number == 701
    assert parsed.AddNum_Suf == "B"
    assert parsed.AddNum_Cmp == "701B"


def test_a_leading_zero_is_preserved_in_addnum_cmp():
    """STA-004.2 §3.3.3.8: "Some address numbers may be preceded by leading
    zeroes, which cannot be represented in an integer format. The leading zero
    is preserved for reference in the Address Number Complete."

    This is the case AddNum_Cmp exists for — the integer cannot carry it and
    nothing else on the wire will."""
    parsed = civic_xml.parse_document(
        _civic_doc("<ca:RD>Main</ca:RD><ca:HNO>0123</ca:HNO>")
    ).civic

    assert parsed.Add_Number == 123
    assert parsed.AddNum_Cmp == "0123"


def test_a_plain_integer_does_not_gain_a_redundant_complete_form():
    """§3.3.5.2 scopes Address Number Complete to cases where concatenating the
    parts does not reproduce the official formatting. "3401" reproduces itself,
    so emitting an HNC for it would add an element the caller did not send."""
    parsed = civic_xml.parse_document(
        _civic_doc("<ca:RD>State</ca:RD><ca:HNO>3401</ca:HNO>")
    ).civic
    assert parsed.AddNum_Cmp is None


def test_an_undecomposable_number_is_dropped_not_rejected():
    """Decision 63. A number that cannot reduce to a non-negative integer costs
    the element, never the request: the caller still has a street name and
    administrative elements worth matching, and for an emergency service a hard
    failure on a recoverable input is the worse error."""
    parsed = civic_xml.parse_document(
        _civic_doc(
            "<ca:A2>Burleigh</ca:A2><ca:RD>State</ca:RD>"
            "<ca:HNO>not-a-number</ca:HNO>"
        )
    )

    assert parsed.civic.Add_Number is None
    # The rest of the query survives intact — that is the whole point.
    assert parsed.civic.St_Name == "State"
    assert parsed.civic.A2 == "Burleigh"


def test_the_drop_is_reported_for_the_enhanced_interface():
    """Decision 63 requires the drop be reported, so a caller handed a
    street-level answer can see the house number was the reason rather than
    inferring it from a lower score."""
    parsed = civic_xml.parse_document(
        _civic_doc("<ca:RD>State</ca:RD><ca:HNO>???</ca:HNO>")
    )

    assert len(parsed.dropped) == 1
    dropped = parsed.dropped[0]
    assert dropped.element == "ca:HNO"
    assert dropped.value == "???"
    assert "decision 63" in dropped.reason


def test_an_explicit_prefix_or_suffix_beats_the_decomposition():
    """A caller who sent cae:HNP asserted it. The decomposition merely reads a
    prefix out of a concatenation, so it must not overwrite one."""
    parsed = civic_xml.parse_document(
        _civic_doc(
            "<ca:RD>50th</ca:RD><cae:HNP>SENT</cae:HNP>"
            "<ca:HNO>194-03</ca:HNO>"
        )
    ).civic

    assert parsed.AddNum_Pre == "SENT"
    assert parsed.Add_Number == 3


def test_a_negative_looking_number_never_produces_a_negative_integer():
    """STA-004.2 §3.3.3.5 types the element non-negative. The sign is
    punctuation to the decomposition and is dropped with the other separators,
    which is the only reading that keeps the type honest."""
    parsed = civic_xml.parse_document(
        _civic_doc("<ca:RD>Main</ca:RD><ca:HNO>-5</ca:HNO>")
    ).civic
    assert parsed.Add_Number == 5


# ---------------------------------------------------------------------------
# The built document is schema-valid
# ---------------------------------------------------------------------------

def test_a_built_civic_address_validates_against_the_master_schema():
    """§4.1 compiles schemas/gcs-pidflo.xsd to reject invalid INPUT; output that
    would fail the same schema is a defect this catches."""
    from src.app import lifecycle

    schema = lifecycle._load_schema()
    assert schema is not None

    civic = CivicAddress(
        Country="US", A1="ND", A2="Burleigh", St_Name="State",
        St_PosTyp="Street", Add_Number=3401, AddNum_Suf="B",
        AddNum_Cmp="3401B", St_PreTyp="Avenue", St_PreSep="of the",
        PostCodeEx="1234", UnitPreTyp="APT", UnitValue="12",
    )
    document = etree.fromstring(civic_xml.to_string(civic).encode("utf-8"))
    assert schema.validate(document), schema.error_log.last_error
