"""§8.3 — the RFC 3863 / RFC 4119 envelope around a converted location.

THE ENTITY ATTRIBUTE (decision 12)

RFC 3863 makes `entity` mandatory on `<presence>`, and the GCS has no verified
presentity to name. The IETF solved the identical problem for the LIS, which
also produces PIDF-LOs without one: RFC 5985 §6.6 has identity parameters
omitted or carrying unlinked pseudonyms, and the LIS SHOULD generate a unique
unlinked presentity URI for the mandatory attribute; RFC 6753 §6.2 hardens that
to MUST for location servers absent Rule Maker policy.

This service follows that precedent with the one refinement available to it that
a LIS lacks: its input already carries an entity. Where the request has one it is
echoed — the location still belongs to that presentity, and the GCS transformed
its representation, not its ownership. Where the input has none or an unusable
one, a HELD-style unlinked pseudonym is generated exactly as a LIS does.
"Unlinked" is the operative word and is why the pseudonym is a fresh UUID: two
responses about the same address must not carry the same identifier, or the
pseudonym becomes a correlation handle for tracking a caller.

USAGE-RULES PASS THROUGH UNCHANGED

The GCS is never a Rule Maker. `retransmission-allowed` and everything alongside
it are copied from the input verbatim; nothing is added, removed or defaulted.
i3 §3.1 notes NG9-1-1 functional elements normally ignore
retransmission-allowed within the ESInet for emergency calls in any case, which
makes altering it both unnecessary and outside this service's authority.

<method> IS NEVER EMITTED (decision 33)

RFC 4119 §2.2.3 constrains `<method>` to an IANA registry pre-populated with
GPS, A-GPS, Manual, DHCP, Triangulation, Cell and 802.11 — device-positioning
methods, every one. The GCS does not observe how a location was derived; it
matches a GIS record whose own provenance is usually unavailable and, where
available, maps to no registered token. Emitting one would be a guess presented
as metadata. The provenance concept has a legitimate home in STA-006.3's
Placement Method, which is data passed through rather than vocabulary minted,
and travels on the enhanced interface instead (§3.2, §10.5).

There is deliberately no function here that emits one. Its absence is the
enforcement.
"""

from __future__ import annotations

import copy
import uuid
from typing import Iterable, Optional

from lxml import etree

from src.api.wire.xml_ns import (
    NSMAP,
    Q_GEOPRIV,
    Q_LOCATION_INFO,
    Q_PRESENCE,
    Q_STATUS,
    Q_TUPLE,
    Q_USAGE_RULES,
)


def pseudonym(server_uri: Optional[str] = None) -> str:
    """A HELD-style unlinked presentity URI (RFC 5985 §6.6, RFC 6753 §6.2).

    A fresh UUID every call. Reusing one, or deriving it from the address, would
    make it linkable — the property the pseudonym exists to deny.
    """
    from src import runtime_state

    host = (server_uri or runtime_state._server_uri or "gcs.invalid").strip()
    return f"pres:{uuid.uuid4()}@{host}"


def _tuple_id() -> str:
    """A tuple id. xs:ID is an NCName, so it cannot start with a digit."""
    return f"gcs-{uuid.uuid4().hex}"


def build_presence(
    payload: Iterable[etree._Element],
    *,
    entity: Optional[str] = None,
    usage_rules: Optional[etree._Element] = None,
) -> etree._Element:
    """Wrap converted location content in a PIDF-LO.

    `payload` is whatever the conversion produced — a civic address, a geometry,
    a confidence element — and goes inside `<location-info>` in the order given.

    RFC 4119 declares `<usage-rules>` mandatory, so an input that carried none
    still yields an empty element here. Empty is the honest rendering: it asserts
    no rule, which is exactly what an input without usage-rules asserted.
    """
    presence = etree.Element(Q_PRESENCE, nsmap=NSMAP)
    presence.set("entity", (entity or "").strip() or pseudonym())

    tuple_element = etree.SubElement(presence, Q_TUPLE)
    tuple_element.set("id", _tuple_id())
    status = etree.SubElement(tuple_element, Q_STATUS)
    geopriv = etree.SubElement(status, Q_GEOPRIV)

    location_info = etree.SubElement(geopriv, Q_LOCATION_INFO)
    for element in payload:
        location_info.append(element)

    # RFC 4119's sequence is location-info, usage-rules, method, provided-by.
    # usage-rules is appended second; method is never appended at all.
    if usage_rules is not None:
        geopriv.append(copy.deepcopy(usage_rules))
    else:
        etree.SubElement(geopriv, Q_USAGE_RULES)

    return presence


def to_string(presence: etree._Element) -> str:
    """Serialise with an XML declaration — this is a whole document.

    `etree.indent()` runs first because `pretty_print=True` alone only fills
    in indentation where an element's `.tail`/`.text` is still `None`; it
    leaves anything already set untouched. `usage_rules`, when the input
    carried one, is a `copy.deepcopy()` of an element parsed out of the
    CALLER's request (build_presence(), above) — it still carries the
    whitespace `.tail` from its position in that original document, which is
    meaningless once relocated here but is enough to make `pretty_print`
    silently skip reformatting the `<gp:geopriv>` subtree around it.
    `etree.indent()` recomputes every structural whitespace node from
    scratch regardless of what was already there, so this holds regardless
    of which payload elements were freshly built and which were copied in.
    """
    etree.indent(presence, space="  ")
    return etree.tostring(
        presence,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    ).decode("utf-8")


def document(
    payload: Iterable[etree._Element],
    *,
    entity: Optional[str] = None,
    usage_rules: Optional[etree._Element] = None,
) -> str:
    """build_presence + to_string, which is what every caller actually wants."""
    return to_string(
        build_presence(payload, entity=entity, usage_rules=usage_rules)
    )
