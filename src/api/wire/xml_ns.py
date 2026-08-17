"""Namespace constants (§1.4) and the hardened XML parser.

THE PARSER CONFIGURATION IS A SECURITY CONTROL

Everything this service parses arrives from the network, and the documents are
XML, which has three well-known ways of turning a parse into an outbound
request, a file read, or a denial of service:

    resolve_entities=False   an internal entity is not expanded, which defeats
                             the billion-laughs class of expansion attack —
                             the reference is left as a reference rather than
                             recursively substituted
    load_dtd=False           no external DTD subset is fetched or applied, so
                             an external entity declaration never becomes a
                             file read (XXE) in the first place
    no_network=True          no parser-initiated network access, for entity
                             resolution or anything else

The three overlap deliberately. Any one of them alone closes most of the
attack, and closing it three ways means a future edit that relaxes one does not
silently open the whole of it. `resolve_entities=False` is the load-bearing one
for expansion; `load_dtd=False` and `no_network=True` are what stop an external
reference being followed off the host.

This matters more here than in a general-purpose service. A GCS sits on an
ESInet and answers unauthenticated-shaped conversion requests during a call;
an XXE that reads a key file, or an entity expansion that pins a worker, is an
emergency-call outage with a network path to it.

Nothing here parses with a bare `etree.fromstring`. Callers take `parser()` or
the shared `XML_PARSER`.
"""

from __future__ import annotations

from lxml import etree

# --- §1.4 PIDF-LO namespace prefixes ---------------------------------------
# The URIs are the specification's table verbatim. The prefix names below match
# the ones §1.4 assigns, so a document this service emits reads the way the
# specification's examples do.

#: RFC 3863 — the presence document root.
NS_PIDF = "urn:ietf:params:xml:ns:pidf"
#: RFC 4119 — location-info, usage-rules, method.
NS_GEOPRIV = "urn:ietf:params:xml:ns:pidf:geopriv10"
#: RFC 4119 — retransmission-allowed and the rest of the basic policy set.
NS_BASIC_POLICY = "urn:ietf:params:xml:ns:pidf:geopriv10:basicPolicy"
#: RFC 5139 — base civic address elements.
NS_CIVIC = "urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr"
#: RFC 6848 — IETF civic extensions.
NS_CIVIC_EXT = "urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr:ext"
#: NENA original CLDXF extensions (STPS only).
NS_CDX1 = "urn:nena:xml:ns:pidf:nenaCivicAddr"
#: NENA-STA-004.2-2024 CLDXF-US extensions.
NS_CDX2 = "urn:nena:xml:ns:pidf:nenaCivicAddr2"
#: OGC GML 3.1.1 subset per RFC 5491 §4.
NS_GML = "http://www.opengis.net/gml"
#: RFC 5491 §5 GeoShape extensions.
NS_GEOSHAPE = "http://www.opengis.net/pidflo/1.0"
#: RFC 7459 — the confidence element.
NS_CONFIDENCE = "urn:ietf:params:xml:ns:geopriv:conf"
#: RFC 4479 presence data model — device and person, which RFC 5491 Rule #8
#: ranks. Not part of §1.4's table; it is here because admission needs it.
NS_DATA_MODEL = "urn:ietf:params:xml:ns:pidf:data-model"

#: Prefix map for serialisation, in §1.4's own spelling. A document built with
#: this map declares every prefix on the root rather than repeating namespace
#: declarations down the tree.
NSMAP: dict[str, str] = {
    None: NS_PIDF,
    "gp": NS_GEOPRIV,
    "gbp": NS_BASIC_POLICY,
    "ca": NS_CIVIC,
    "cae": NS_CIVIC_EXT,
    "cdx1": NS_CDX1,
    "cdx2": NS_CDX2,
    "gml": NS_GML,
    "gs": NS_GEOSHAPE,
    "conf": NS_CONFIDENCE,
}


def q(namespace: str, local: str) -> str:
    """A Clark-notation qualified name, as lxml wants it."""
    return f"{{{namespace}}}{local}"


# --- Qualified names used in more than one module --------------------------

Q_PRESENCE = q(NS_PIDF, "presence")
Q_TUPLE = q(NS_PIDF, "tuple")
Q_STATUS = q(NS_PIDF, "status")
Q_DEVICE = q(NS_DATA_MODEL, "device")
Q_PERSON = q(NS_DATA_MODEL, "person")
Q_GEOPRIV = q(NS_GEOPRIV, "geopriv")
Q_LOCATION_INFO = q(NS_GEOPRIV, "location-info")
Q_USAGE_RULES = q(NS_GEOPRIV, "usage-rules")
Q_METHOD = q(NS_GEOPRIV, "method")
Q_CIVIC_ADDRESS = q(NS_CIVIC, "civicAddress")
Q_CONFIDENCE = q(NS_CONFIDENCE, "confidence")


def parser() -> etree.XMLParser:
    """A parser hardened per this module's docstring.

    A fresh instance rather than the shared one, for callers that need to hold
    a parser across threads — lxml parsers are not documented as thread-safe.
    """
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
    )


#: The shared hardened parser, for the single-threaded request path.
XML_PARSER: etree.XMLParser = parser()
