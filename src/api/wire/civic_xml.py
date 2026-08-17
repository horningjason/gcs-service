"""§3.10 — PIDF-LO civic elements <-> the STA-006.3 element model.

Both directions, one table (decision 62). The engine never sees a `ca:` name and
this module never sees a scoring decision.

THE TABLE IS TRANSCRIBED, NOT AUTHORED

NENA-STA-004.2-2024 states the mapping element by element, in the form
"CLDXF-US name (PIDF-LO name)". §3.10 transcribes it for implementation
convenience and says plainly that STA-004.2 governs on any disagreement. That
is the standing instruction for this module: where the table below and the
standard differ, the standard is right and the table is a typo to be corrected.

COLUMNS WITH NO PIDF-LO COUNTERPART

`MSAGComm` and the `LSt_*` legacy street-name fields are legacy MSAG constructs
outside CLDXF-US; `AddCode`, `FloorIndex`, and a complete-form `Unit` (the
provisioned schema carries `UnitPreTyp`/`UnitValue` separately) likewise have no
counterpart. None of them is emitted to the wire or populated from it. They
remain available to §6.5 scoring where the record carries them — they simply
have no wire representation, which is a different thing from being unusable.

THE ADDRESS NUMBER IS AN INTEGER (decision 63)

STA-004.2 §3.3.3.5 types Address Number as a non-negative integer, narrowing
RFC 5139's string typing; this service is CLDXF-US-scoped (§3.1), so the integer
governs. A complete address number decomposes into prefix, integer and suffix by
STA-004.2's own rule (§3.3.2.8, §3.3.3.8, §3.3.4.8), and the caller's original
form is preserved in `AddNum_Cmp`.

Where a supplied number cannot reduce to a non-negative integer, the element is
DROPPED and the request proceeds without it. It is never a rejection. An element
the service cannot use should cost precision, not candidacy — the same posture
decision 61 takes — and a caller who mistyped a house number still has a street
name and administrative elements worth matching. The consequence is stated
rather than hidden: the answer degrades toward a street-level match and the
enhanced interface reports the drop, so a caller handed a segment can see why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from lxml import etree

from src.api.wire.xml_ns import (
    NS_CDX1,
    NS_CDX2,
    NS_CIVIC,
    NS_CIVIC_EXT,
    NSMAP,
    Q_CIVIC_ADDRESS,
    q,
)
from src.engine.models import CivicAddress

# ---------------------------------------------------------------------------
# §3.10's mapping table
# ---------------------------------------------------------------------------

#: STA-006.3 column -> (namespace, PIDF-LO local name). Order is §3.10's own,
#: which is also the order elements are emitted in — RFC 5139's content model is
#: an unbounded xs:choice, so any order validates and a stable one is kinder to
#: anyone diffing two responses.
ELEMENT_MAP: tuple[tuple[str, str, str], ...] = (
    ("Country", NS_CIVIC, "country"),
    ("A1", NS_CIVIC, "A1"),
    ("A2", NS_CIVIC, "A2"),
    ("A3", NS_CIVIC, "A3"),
    ("A4", NS_CIVIC, "A4"),
    ("A5", NS_CIVIC, "A5"),
    ("Post_Comm", NS_CIVIC, "PCN"),
    ("Post_Code", NS_CIVIC, "PC"),
    ("PostCodeEx", NS_CDX2, "PCE"),
    ("AddNum_Pre", NS_CIVIC_EXT, "HNP"),
    ("Add_Number", NS_CIVIC, "HNO"),
    ("AddNum_Suf", NS_CIVIC, "HNS"),
    ("AddNum_Cmp", NS_CDX2, "HNC"),
    ("St_PreMod", NS_CIVIC, "PRM"),
    ("St_PreDir", NS_CIVIC, "PRD"),
    ("St_PreTyp", NS_CIVIC_EXT, "STP"),
    ("St_PreSep", NS_CDX1, "STPS"),
    ("St_Name", NS_CIVIC, "RD"),
    ("St_PosTyp", NS_CIVIC, "STS"),
    ("St_PosDir", NS_CIVIC, "POD"),
    ("St_PosMod", NS_CIVIC, "POM"),
    ("Site", NS_CDX2, "SITE"),
    ("SubSite", NS_CDX2, "SUBSITE"),
    ("Structure", NS_CIVIC, "BLD"),
    ("Wing", NS_CDX2, "WING"),
    ("Floor", NS_CIVIC, "FLR"),
    ("UnitPreTyp", NS_CDX2, "UNIT_PRETYPE"),
    ("UnitValue", NS_CDX2, "UNIT_VALUE"),
    ("Room", NS_CIVIC, "ROOM"),
    ("Section", NS_CDX2, "SECTION"),
    ("Row_", NS_CDX2, "ROW"),
    ("Seat", NS_CIVIC, "SEAT"),
    ("Addtl_Loc", NS_CIVIC, "LOC"),
    ("Place_Type", NS_CIVIC, "PLC"),
)

#: Columns deliberately absent from ELEMENT_MAP, with the reason (§3.10,
#: decision 62). Asserted by a test rather than left as a silent omission.
NO_WIRE_COUNTERPART: dict[str, str] = {
    "MSAGComm": "Legacy MSAG community — a legacy construct outside CLDXF-US.",
    "LSt_PreDir": "Legacy street name field — outside CLDXF-US.",
    "LSt_Name": "Legacy street name field — outside CLDXF-US.",
    "LSt_Typ": "Legacy street name field — outside CLDXF-US.",
    "LSt_PosDir": "Legacy street name field — outside CLDXF-US.",
    "AddCode": "No CLDXF-US counterpart in STA-004.2's element list.",
    "FloorIndex": "A provisioned sort key for Floor, not an address element.",
    "Unit": "Complete-form unit; the wire carries UnitPreTyp/UnitValue "
            "separately and reconstructing a complete form would synthesise "
            "an element the caller did not send.",
}

#: PIDF-LO qualified name -> column, for the read direction.
_BY_QNAME: dict[str, str] = {
    q(ns, local): column for column, ns, local in ELEMENT_MAP
}

#: Columns typed as integers in the element model.
_INTEGER_COLUMNS = frozenset({"Add_Number", "FloorIndex"})


# ---------------------------------------------------------------------------
# Address number decomposition (STA-004.2 §3.3)
# ---------------------------------------------------------------------------

#: Every run of decimal digits. The LAST one is the Address Number; everything
#: before it is prefix material and everything after it is suffix material.
#:
#: That single rule reproduces every example STA-004.2 gives, which is why it is
#: written as one rule rather than a table of regional special cases:
#:
#:     "123 Main St"   -> 123
#:     "701B"          -> 701 + "B"                    (§3.3.4.4)
#:     "123-A"         -> 123 + "A"                    (§3.3.4.4)
#:     "119½"          -> 119 + "½"                    (§3.3.3.4)
#:     "A19"           -> "A" + 19                     Puerto Rico, §3.3.2.8a
#:     "5-5415"        -> "5" + 5415                   Hawaii, §3.3.2.8b
#:     "194-13"        -> "194" + 13                   Queens, §3.3.2.8c
#:     "194-03½"       -> "194" + 3 + "½"              Queens, §3.3.3.8
#:     "N89W16758"     -> "N89W" + 16758               Wisconsin, §3.3.2.8d
#:     "W63N 645"      -> "W63N" + 645                 Wisconsin, §3.3.2.8d
#:
#: The Wisconsin case is the one that fixes the rule as "last run" rather than
#: "first run": the grid reference N89W itself contains digits, and §3.3.2.8d
#: says the prefix is everything up to and including the last letter.
_DIGIT_RUN = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class AddressNumber:
    """A decomposed complete address number."""

    number: int
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    #: The caller's original form, where it differs from a plain integer.
    complete: Optional[str] = None


def _strip_separators(text: str) -> Optional[str]:
    """Drop separators, keep identifiers.

    STA-004.2 §3.3.2.8 and §3.3.4.8 both say the prefix and suffix exclude
    "separators such as spaces, hyphens, or other punctuation" — those are
    preserved in Address Number Complete instead. Anything alphanumeric is an
    identifier and stays, which keeps "N89W" whole and keeps "½" (a numeric
    character, though not a decimal digit) in the suffix where §3.3.4.8 puts it.
    """
    kept = "".join(ch for ch in text if ch.isalnum())
    return kept or None


def decompose(text: str) -> Optional[AddressNumber]:
    """Split a complete address number per STA-004.2 §3.3.

    Returns None where the value contains no integer at all — decision 63's
    drop case. The caller admits the request and proceeds without the element.

    STA-004.2 §3.3.3.8 says that where an address number has no integer portion
    ("½ Fifth Avenue") a zero "must be entered for the Address Number". That
    rule is NOT applied here, and the difference is deliberate: it addresses
    authoring a GIS record's fields, where some value must be stored, whereas
    this function interprets a caller's query. Zero is a real and distinct house
    number — §3.3.3.8 gives "0 Prince Street" as a valid address — so
    substituting it would turn "no usable number" into a specific wrong number
    and search for a different building. Dropping loses precision; substituting
    invents a fact. See spec Appendix C.4's open subsection.
    """
    stripped = text.strip()
    if not stripped:
        return None

    runs = list(_DIGIT_RUN.finditer(stripped))
    if not runs:
        return None

    last = runs[-1]
    number = int(last.group())
    prefix = _strip_separators(stripped[: last.start()])
    suffix = _strip_separators(stripped[last.end():])

    # Address Number Complete records "the desired formatting ... in cases where
    # simple concatenation of the prefix, number, and suffix elements does not
    # reproduce the official formatting" (§3.3.5.2). Leading zeros are the case
    # §3.3.3.8 calls out by name: an integer cannot carry them, so the original
    # is the only place they survive.
    complete = stripped if stripped != str(number) else None

    return AddressNumber(
        number=number, prefix=prefix, suffix=suffix, complete=complete
    )


# ---------------------------------------------------------------------------
# Read: PIDF-LO -> CivicAddress
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DroppedElement:
    """An element the wire carried that the element model could not accept.

    Reported on the enhanced interface (decision 63). The strict interface has
    no field for it, which is the usual §8.1 story and not a new one.
    """

    element: str
    value: str
    reason: str


@dataclass(frozen=True, slots=True)
class ParsedCivic:
    civic: CivicAddress
    dropped: tuple[DroppedElement, ...] = ()


def parse(element: etree._Element) -> ParsedCivic:
    """Read a `ca:civicAddress` into the element model.

    Elements outside §3.10's table are ignored rather than refused: the schema
    admits the full RFC 5139 vocabulary and more through its extension point,
    and an element this service has no column for is not a malformed request.
    Repeated elements take the last occurrence, matching the unbounded xs:choice
    the schema declares.
    """
    values: dict[str, object] = {}
    dropped: list[DroppedElement] = []

    #: Raw HNO text, held back until every element has been read — the
    #: decomposition must not overwrite a prefix or suffix the caller sent
    #: explicitly, and element order on the wire is not constrained.
    house_number_text: Optional[str] = None

    for child in element:
        if not isinstance(child.tag, str):
            continue  # comment or processing instruction
        column = _BY_QNAME.get(child.tag)
        if column is None:
            continue
        text = (child.text or "").strip()
        if not text:
            continue

        if column == "Add_Number":
            house_number_text = text
            continue
        values[column] = text

    if house_number_text is not None:
        parsed = decompose(house_number_text)
        if parsed is None:
            dropped.append(
                DroppedElement(
                    element="ca:HNO",
                    value=house_number_text,
                    reason=(
                        "Address number does not reduce to a non-negative "
                        "integer under NENA-STA-004.2 §3.3; the element was "
                        "dropped and the request answered without it "
                        "(spec decision 63)."
                    ),
                )
            )
        else:
            values["Add_Number"] = parsed.number
            # An element the caller sent explicitly always wins over one the
            # decomposition inferred: the caller asserted it, this module
            # merely read it out of a concatenation.
            if parsed.prefix is not None:
                values.setdefault("AddNum_Pre", parsed.prefix)
            if parsed.suffix is not None:
                values.setdefault("AddNum_Suf", parsed.suffix)
            if parsed.complete is not None:
                values.setdefault("AddNum_Cmp", parsed.complete)

    for column in _INTEGER_COLUMNS:
        raw = values.get(column)
        if isinstance(raw, str):
            try:
                values[column] = int(raw)
            except ValueError:
                del values[column]

    return ParsedCivic(civic=CivicAddress(**values), dropped=tuple(dropped))


def parse_document(text: str) -> ParsedCivic:
    """Parse a standalone `ca:civicAddress` document. Test and tooling entry."""
    from src.api.wire.xml_ns import XML_PARSER

    root = etree.fromstring(text.encode("utf-8"), XML_PARSER)
    if root.tag != Q_CIVIC_ADDRESS:
        raise ValueError(f"expected {Q_CIVIC_ADDRESS}, got {root.tag!r}")
    return parse(root)


# ---------------------------------------------------------------------------
# Write: CivicAddress -> PIDF-LO
# ---------------------------------------------------------------------------

def build(civic: CivicAddress) -> etree._Element:
    """Render the element model as a `ca:civicAddress`.

    §11.4's omit-rather-than-emit-empty rule is the whole of the selection: an
    element with no value is absent, never present and empty. A sparse record
    produces a sparse address rather than a padded one.
    """
    root = etree.Element(Q_CIVIC_ADDRESS, nsmap=NSMAP)
    populated = civic.populated()

    for column, namespace, local in ELEMENT_MAP:
        value = populated.get(column)
        if value is None:
            continue
        child = etree.SubElement(root, q(namespace, local))
        child.text = str(value)

    return root


def to_string(civic: CivicAddress) -> str:
    return etree.tostring(build(civic), pretty_print=True).decode("utf-8")
