"""§3.9.1, §8.1, §12.1 — the strict interface's 200 response, as real XML.

DECISION 116 (SESSION 14) — SUPERSEDES THE SESSION 3 JSON-WRAPPER READING

The normative YAML declares the 200 response `application/xml` with schema
`GeodeticData { pidfLoGeo: string }` / `CivicAddress { pidfLoAddress: string }`
and no `xml:` annotations on either. Session 3 read those two declarations as
irreconcilable — an XML content type carrying a JSON-shaped object schema —
and emitted `application/json` instead, discarding the declared content
type to keep the declared schema. That reading missed OpenAPI 3.0's own
default XML serialization: absent any `xml:` object, a schema's properties
become child elements named after the property, nested under a root element
named after the schema (confirmed directly against the OpenAPI 3.0.3
specification and Swagger's own reference documentation — neither states an
exception for a `type: string` property, and neither mentions CDATA, which
is standard XML below the OpenAPI layer, not something OpenAPI needs to
specify). Read that way, BOTH declarations hold at once:

    <GeodeticData><pidfLoGeo><![CDATA[...]]></pidfLoGeo></GeodeticData>
    <CivicAddress><pidfLoAddress><![CDATA[...]]></pidfLoAddress></CivicAddress>

`application/xml` is honoured literally, `pidfLoGeo`/`pidfLoAddress` remain
string-typed (CDATA content is text, precisely what a JSON string value
would have carried), and the embedded PIDF-LO travels as real, indented XML
rather than a JSON-escaped one-liner — closing the readability gap decision
115 raised without abandoning §1.2.1's discipline for a bigger, unreviewed
change. Checked against i3 §4.4 (MSAG Conversion Service) too: it uses the
identical "returns ... as a string" phrasing i3 §4.5 uses for GCS, so the
wording is i3's deliberate, repeated style for these conversion FEs, not a
one-off drafting artifact in the GCS section — and it says nothing about the
envelope encoding either way, so it does not argue against this reading.

No namespace is declared on `GeodeticData`/`CivicAddress`/`pidfLoGeo`/
`pidfLoAddress`, matching "no `xml:` annotation means no namespace override."
The `]]>` edge case (an embedded document whose content happens to contain
that literal sequence — reachable via the input's echoed `entity`, decision
12) is handled by lxml/libxml2 itself: `etree.CDATA()` splits an embedded
`]]>` into adjacent CDATA sections automatically, verified to round-trip
correctly through `etree.fromstring()`. No extra escaping code is needed
here for it.

THE ENHANCED INTERFACE IS UNAFFECTED

`references/i3-geocode-conversion-enhanced.yaml` is GCS's own additive,
non-normative schema (§2.2) — nothing here constrains it. `candidates[]`
(`src/api/wire/response_json.py`) stays JSON.
"""

from __future__ import annotations

from lxml import etree


def geodetic_data_xml(pidf_lo: str) -> str:
    """POST /Geocode's 200 body (§8.1)."""
    root = etree.Element("GeodeticData")
    child = etree.SubElement(root, "pidfLoGeo")
    child.text = etree.CDATA(pidf_lo)
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    ).decode("utf-8")


def civic_address_xml(pidf_lo: str) -> str:
    """POST /ReverseGeocode's 200 body (§12.1)."""
    root = etree.Element("CivicAddress")
    child = etree.SubElement(root, "pidfLoAddress")
    child.text = etree.CDATA(pidf_lo)
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    ).decode("utf-8")
