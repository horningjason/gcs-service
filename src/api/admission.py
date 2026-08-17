"""Stage 0 — Request Admission (spec §4.1, §4.2, §9; and §5 by omission).

Shared by all four resources. Everything here is symmetric across Geocode and
ReverseGeocode except which location chunk the operation requires: §9 states
that admission "otherwise mirrors §4", and §4.2's first-location rule is
applied identically in both directions (decision 50), so there is one
implementation with a profile parameter rather than two.

WHAT THIS MODULE DOES NOT DO — §5, and it is deliberate

There is no structural conformance gate. i3 §4.5 imposes no structural
precondition on Geocode, and requiring one would add a restriction the standard
does not have (§5, §1.2.1, decision 14). Concretely: a civic address with no
HNO is ADMITTED here and answered at rung 3, and an address whose HNO matches
no record is ADMITTED and may degrade to a street-level answer. The honesty
burden moves to uncertainty (§7.4), not to admission.

This is the LVF's Gate 1, and its absence is the single largest structural
difference between the two admission paths. LVF rejects a missing HNO with
<locationInvalid>; the GCS accepts it. See tests/conformance/test_admission.py,
which asserts the absence rather than leaving it as a silent property.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from lxml import etree

log = logging.getLogger(__name__)

# --- Namespaces and the hardened parser (spec §1.4) -------------------------
# All of these live in src/api/wire/xml_ns.py, which is the one definition of
# each. XML_PARSER is re-exported because two copies of a parser hardening
# configuration is exactly the drift that leaves one of them unhardened —
# tests/conformance/test_wire_parser_hardening.py asserts the identity
# (admission.XML_PARSER is xml_ns.XML_PARSER) rather than leaving it to
# convention. The rest are imported for this module's own use below.
#
# The bare NS_CIVIC/NS_DATA_MODEL/NS_GEOPRIV names were re-exported here too,
# for callers that once took them from admission; every consumer now imports
# them from xml_ns directly, so they are gone rather than kept as an unused
# surface. The Q_* names below ARE used here.
#
# Q_DEVICE and Q_PERSON are RFC 4479's presence data model, which RFC 5491
# Rule #8 ranks. Not in schemas/: RFC 3863 admits them through xs:any ##other
# lax, so the dm:* wrapper structure is not validated — the geopriv content
# inside it still is, wherever it appears. An accepted, documented boundary:
# spec decision 105 (resolving Appendix C.4 Q15).

from src.api.wire.xml_ns import (  # noqa: E402
    NS_GEOSHAPE,
    NS_GML,
    NS_PIDF,
    Q_CIVIC_ADDRESS,
    Q_DEVICE,
    Q_GEOPRIV,
    Q_LOCATION_INFO,
    Q_PERSON,
    Q_PRESENCE,
    Q_TUPLE,
    Q_USAGE_RULES,
    XML_PARSER,
)


class Profile(str, Enum):
    """Which location chunk the operation requires."""

    CIVIC = "civic"        # Geocode  — §4
    GEODETIC = "geodetic"  # ReverseGeocode — §9


class AdmissionError(Exception):
    """A request that cannot proceed to candidate identification.

    `status` is one of the i3 §4.5 codes — the set is closed (§1.2.1,
    decision 2) and nothing here mints a new one. `reason` is emitted in the
    body for 454 only, per §4.1's stated convention; §4.5 defines no body for
    468 and none is invented.
    """

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(slots=True)
class AdmittedRequest:
    """The output of Stage 0 — everything downstream stages need from the
    request document, with nothing re-parsed later."""

    #: The <presence> root.
    document: etree._Element
    #: The elected <location-info> (§4.2 / RFC 5491 Rule #8).
    location_info: etree._Element
    #: The chunk within it matching the requested profile.
    chunk: etree._Element
    #: Which container the elected location came from — "device", "tuple" or
    #: "person". Rule #8 says person locations "SHOULD only be used as a last
    #: resort", so a value of "person" is worth logging.
    elected_from: str
    #: The presence entity attribute. §8.3 echoes this onto the response where
    #: present, and generates a HELD-style unlinked pseudonym where it is not.
    entity: Optional[str]
    #: The elected geopriv's <usage-rules>, passed through unchanged (§8.3).
    usage_rules: Optional[etree._Element]
    #: How many locations the document carried. i3 mandates converting only the
    #: first and gives no way to signal the discard, so this surfaces on the
    #: enhanced interface only (§4.2, decision 50, §16).
    location_count: int


# ---------------------------------------------------------------------------
# §4.1 — Body, Content-Type, and schema validation
# ---------------------------------------------------------------------------

def decode_body(raw: bytes, content_type: str | None) -> str:
    """Recover the PIDF-LO document text from the request body.

    The normative YAML declares the request body as `application/json` with
    `schema: {type: string}`. Read strictly that means a JSON document that IS
    a string — the XML quoted and escaped. Read as most senders will implement
    it, it means the XML itself with a confused Content-Type.

    Both are accepted, discriminated by the first non-whitespace byte: a
    double quote means a JSON string, an angle bracket means raw XML.
    Rejecting either would add a restriction i3 does not impose, which
    decision 2's corollary bars as firmly as adding capability — and the
    declaration this would be strict about is the same one §16 already records
    as incoherent. Content-Type is not enforced for the same reason; an
    unexpected one is logged, not rejected.

    Spec §3.9.1, decision 95 (resolving Appendix C.4 Q14).
    """
    if not raw or not raw.strip():
        raise AdmissionError(454, "Request body is empty; expected a PIDF-LO document.")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdmissionError(
            454, f"Request body is not valid UTF-8: {exc}."
        ) from exc

    stripped = text.lstrip()
    if stripped.startswith('"'):
        try:
            decoded = json.loads(text)
        except ValueError as exc:
            raise AdmissionError(
                454, f"Request body looks like a JSON string but does not parse: {exc}."
            ) from exc
        if not isinstance(decoded, str):
            raise AdmissionError(
                454,
                "Request body is a JSON document but not a JSON string; the "
                "normative schema declares type: string carrying the PIDF-LO.",
            )
        return decoded

    if stripped.startswith("<"):
        if content_type and "json" not in content_type.lower():
            log.debug("Raw XML body with Content-Type %r — accepted", content_type)
        return text

    raise AdmissionError(
        454,
        "Request body is neither a JSON string nor an XML document; expected a "
        "PIDF-LO carried as either.",
    )


def parse_and_validate(text: str, schema: Optional[etree.XMLSchema]) -> etree._Element:
    """Parse the document and validate it against schemas/gcs-pidflo.xsd.

    §4.1: malformed body, invalid XML, a document that is not a PIDF-LO, or a
    PIDF-LO whose structure fails the envelope schemas all return 454 with a
    human-readable reason. 468 is not used for any of them — it asserts that a
    search was performed.
    """
    try:
        root = etree.fromstring(text.encode("utf-8"), XML_PARSER)
    except etree.XMLSyntaxError as exc:
        raise AdmissionError(454, f"Request body is not well-formed XML: {exc}.") from exc

    if root.tag != Q_PRESENCE:
        raise AdmissionError(
            454,
            f"Request document root is {root.tag!r}; a PIDF-LO must be "
            f"<presence> in {NS_PIDF}.",
        )

    if schema is None:
        # Loud, because §4.1's 454 requirement cannot be enforced without it.
        log.error("Schema validation skipped — no compiled schema available")
        return root

    if not schema.validate(root):
        last = schema.error_log.last_error
        detail = last.message if last is not None else "unspecified schema violation"
        line = f" at line {last.line}" if last is not None else ""
        raise AdmissionError(454, f"PIDF-LO failed schema validation{line}: {detail}.")

    return root


# ---------------------------------------------------------------------------
# §4.2 — Multiple location handling, RFC 5491 Rule #8
# ---------------------------------------------------------------------------

def _locations_in(container: etree._Element) -> list[etree._Element]:
    """<location-info> elements under `container` that actually carry content.

    An empty <location-info> is schema-valid (its content model is xs:any with
    minOccurs 0) but carries no location, so it does not count as "containing a
    location" for Rule #8 purposes.
    """
    found = []
    for geopriv in container.iter(Q_GEOPRIV):
        info = geopriv.find(Q_LOCATION_INFO)
        if info is not None and len(info) > 0:
            found.append(info)
    return found


def elect_location(root: etree._Element) -> tuple[etree._Element, str, int]:
    """Elect exactly one location, per RFC 5491 §3 Rule #8.

    i3 §4.5 requires that a request carrying more than one location yield
    exactly one result, being the conversion of "the first location", but does
    not define first. RFC 5491 Rule #8 does, and it is a TYPED PRECEDENCE
    rather than document order:

        priority to the first <device> element containing a location;
        failing that, the first <tuple> element containing a location;
        locations in <person> elements only as a last resort.

    Returns (location_info, elected_from, total_location_count).
    """
    by_container: dict[str, list[etree._Element]] = {}
    for name, qname in (("device", Q_DEVICE), ("tuple", Q_TUPLE), ("person", Q_PERSON)):
        found: list[etree._Element] = []
        for container in root.iter(qname):
            found.extend(_locations_in(container))
        by_container[name] = found

    # A <geopriv> sitting directly under <presence>, in no container at all, is
    # outside Rule #8's vocabulary. RFC 3863 permits it via xs:any, so it is
    # counted and used as a final fallback rather than being invisible.
    contained = {id(info) for group in by_container.values() for info in group}
    loose = [info for info in _locations_in(root) if id(info) not in contained]

    total = sum(len(group) for group in by_container.values()) + len(loose)

    for name in ("device", "tuple", "person"):
        if by_container[name]:
            if name == "person":
                log.info(
                    "Elected a location from <person> — RFC 5491 Rule #8 says these "
                    "SHOULD only be used as a last resort"
                )
            return by_container[name][0], name, total

    if loose:
        log.info("Elected a <geopriv> not inside device/tuple/person — outside Rule #8")
        return loose[0], "none", total

    # §4.2 / decision 50 treat "the elected location lacks the required chunk"
    # as 468. A document carrying no location at all is the same shape of
    # failure — well-formed, schema-valid, nothing convertible — and is
    # answered the same way (spec §4.2, decision 102).
    raise AdmissionError(468, "Request PIDF-LO carries no location.")


def _find_chunk(location_info: etree._Element, profile: Profile) -> Optional[etree._Element]:
    """The chunk of the requested profile within the elected <location-info>.

    RFC 5491 Rule #7 requires the coarse element first in a compound location,
    so position within <location-info> encodes coarseness, not relevance — it
    cannot be used to select by type (§4.2). Selection is by namespace only.
    """
    for child in location_info:
        if not isinstance(child.tag, str):
            continue  # comment or processing instruction
        if profile is Profile.CIVIC:
            if child.tag == Q_CIVIC_ADDRESS:
                return child
        else:
            if child.tag.startswith(f"{{{NS_GML}}}") or child.tag.startswith(
                f"{{{NS_GEOSHAPE}}}"
            ):
                return child
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def admit(
    raw: bytes,
    content_type: str | None,
    profile: Profile,
    schema: Optional[etree.XMLSchema],
) -> AdmittedRequest:
    """Run Stage 0. Raises AdmissionError with an i3 §4.5 status on rejection."""
    text = decode_body(raw, content_type)
    root = parse_and_validate(text, schema)
    location_info, elected_from, count = elect_location(root)

    chunk = _find_chunk(location_info, profile)
    if chunk is None:
        # §4.2 / decision 50: the elected location is used as elected. Walking
        # past it to find a better-typed one would have the GCS infer intent
        # the caller did not express, and silently answer from a location the
        # standard did not nominate.
        raise AdmissionError(
            468,
            f"The elected location carries no {profile.value} location information.",
        )

    geopriv = location_info.getparent()
    usage_rules = geopriv.find(Q_USAGE_RULES) if geopriv is not None else None

    if count > 1:
        log.info(
            "Request carried %d locations; converting the first per i3 §4.5 "
            "(elected from <%s>)",
            count,
            elected_from,
        )

    return AdmittedRequest(
        document=root,
        location_info=location_info,
        chunk=chunk,
        elected_from=elected_from,
        entity=root.get("entity"),
        usage_rules=usage_rules,
        location_count=count,
    )
