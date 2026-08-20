"""Routing manifest for tests/regression/ — which endpoint each test ID
targets and how the request should be transported.

Committed, unlike inputs/ and golden/: this file carries no address data,
only test IDs and routing, so it is the one piece of the regression suite
that is environment-independent (same in every checkout regardless of which
GeoPackage GCS_GPKG_PATH points at). Naming follows lvf-service's
tests/regression/ convention — PREFIX-MNEMONIC-NNN, one XML file per ID under
inputs/ — adapted to a prefix scheme for GCS's own algorithm structure:

    ADM   Stage 0 request admission (spec §4, §9) — content decoding, schema
          validation, profile/location election. Status-code-only outcomes.
    FWD   Geocode candidate identification and position derivation (§5-§8).
    REV   ReverseGeocode search and civic derivation (§9-§12).

A case whose mnemonic ends in -ENH targets one of the enhanced resources and
exercises the same real-world condition as its non-ENH sibling (where one
exists) from the other interface's side of the §2.2 controlled comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

GEOCODE = "/Gcs/v1/Geocode"
REVERSE = "/Gcs/v1/ReverseGeocode"
GEOCODE_ENH = "/Gcs/v1/GeocodeEnhanced"
REVERSE_ENH = "/Gcs/v1/ReverseGeocodeEnhanced"


@dataclass(frozen=True)
class Case:
    id: str
    target: str
    #: True sends the file's content JSON-string-wrapped with
    #: Content-Type: application/json instead of raw application/xml (§4.1's
    #: other admitted body shape per the normative YAML).
    json_wrap: bool = False


CASES: tuple[Case, ...] = (
    # -- ADM: Stage 0 admission (§4, §9) -----------------------------------
    Case("ADM-MALFORMED-XML-001", GEOCODE),
    Case("ADM-EMPTY-BODY-001", GEOCODE),
    Case("ADM-NOT-PIDF-001", REVERSE),
    Case("ADM-SCHEMA-INVALID-001", GEOCODE),
    Case("ADM-WRONG-PROFILE-GEO-001", GEOCODE),
    Case("ADM-WRONG-PROFILE-CIVIC-001", REVERSE),
    Case("ADM-NO-LOCATION-001", GEOCODE),
    Case("ADM-MULTI-LOC-ENH-001", GEOCODE_ENH),
    Case("ADM-MULTI-LOC-STRICT-001", GEOCODE),
    Case("ADM-NONNUMERIC-COORD-001", REVERSE),
    Case("ADM-SPHERE-UNREADABLE-001", REVERSE),
    Case("ADM-JSON-BODY-001", GEOCODE, json_wrap=True),

    # -- FWD: Geocode candidates + position derivation (§5-§8) -------------
    Case("FWD-SSAP-EXACT-001", GEOCODE),
    Case("FWD-SSAP-EXACT-ENH-001", GEOCODE_ENH),
    Case("FWD-RCL-INTERP-001", GEOCODE),
    Case("FWD-RCL-INTERP-ENH-001", GEOCODE_ENH),
    Case("FWD-STREET-ONLY-001", GEOCODE),
    Case("FWD-NOMATCH-001", GEOCODE),
    Case("FWD-GAP-HNO-001", GEOCODE),
    Case("FWD-AMBIG-MERGE-001", GEOCODE),
    Case("FWD-AMBIG-CANDIDATES-ENH-001", GEOCODE_ENH),
    Case("FWD-UNIT-DISAMBIG-001", GEOCODE),
    Case("FWD-AMBIG-BISMARCK-ENH-001", GEOCODE_ENH),
    Case("FWD-DROPPED-HNO-ENH-001", GEOCODE_ENH),
    Case("FWD-DROPPED-HNO-STRICT-001", GEOCODE),
    Case("FWD-GEOCODED-PLACEMENT-ENH-001", GEOCODE_ENH),

    # -- REV: ReverseGeocode search + civic derivation (§9-§12) ------------
    Case("REV-POINT-SSAP-001", REVERSE),
    Case("REV-POINT-SSAP-ENH-001", REVERSE_ENH),
    Case("REV-RCL-SYNTH-HNO-001", REVERSE),
    Case("REV-RCL-SYNTH-HNO-ENH-001", REVERSE_ENH),
    Case("REV-CIRCLE-ENH-001", REVERSE_ENH),
    Case("REV-POLYGON-001", REVERSE),
    Case("REV-ELLIPSE-001", REVERSE),
    Case("REV-SPHERE-VALID-001", REVERSE),
    Case("REV-NOMATCH-OPENWATER-001", REVERSE),
    Case("REV-CROSSCOUNTY-001", REVERSE),
    Case("REV-DUPLICATE-TIEBREAK-001", REVERSE),
    Case("REV-CONTAINED-POLYGON-ENH-001", REVERSE_ENH),
    Case("REV-ELLIPSE-ENH-001", REVERSE_ENH),
    Case("REV-SPHERE-ENH-001", REVERSE_ENH),
    Case("REV-ELLIPSOID-ENH-001", REVERSE_ENH),
    Case("REV-PRISM-ENH-001", REVERSE_ENH),
    Case("REV-ARCBAND-ENH-001", REVERSE_ENH),
)

CASES_BY_ID: dict[str, Case] = {c.id: c for c in CASES}
