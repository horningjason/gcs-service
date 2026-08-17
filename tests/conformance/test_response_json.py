"""§3.9.2/§12.2 enhanced wire format (src/api/wire/response_json.py) against
the reconciled normative YAML (decision 92,
references/i3-geocode-conversion-enhanced.yaml).

WHAT THIS FILE EXISTS TO CATCH

Appendix C item (c) and response_json.py's own module docstring both stated
for three sessions that the enhanced YAML did not exist yet, while a draft
had in fact existed since Session 5 and the implementation kept moving
without either artifact being checked against the other — decision 92's own
account of the drift. The absence of a mechanical check on the two agreeing
is what let that happen silently. This file is that check: it parses the
YAML directly, resolves each schema's allOf composition into a flat key set,
and compares it against what src/api/wire/response_json.py actually emits
for a maximally-populated answer.

REQUIRES PyYAML, WHICH IS NOT A DECLARED PROJECT DEPENDENCY

PyYAML is present in this development environment as a transitive
dependency of `bandit`, not of anything pinned in requirements.txt — none
of fastapi/starlette/uvicorn pull it in without an "extra" this project does
not request. This import is deliberately NOT wrapped in
`pytest.importorskip`: a schema/emitter drift check that silently skips
when its own tooling is missing defeats the reason it exists. If this
module fails to import with ModuleNotFoundError in a clean environment,
that is the signal to add pyyaml to requirements.txt (or a dev/test-only
requirements file) — flagged here rather than decided here.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from shapely.geometry import Point

from src.api.wire import response_json
from src.api.wire.civic_xml import DroppedElement
from src.engine.models import CivicAddress, LocationType, MatchQuality, Position
from src.geocode.response_assembly import ForwardAnswer
from src.reverse.response_assembly import ReverseAnswer

_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "references" / "i3-geocode-conversion-enhanced.yaml"
)


def _schemas() -> dict:
    with open(_YAML_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc["components"]["schemas"]


def _resolve(schemas: dict, name: str) -> tuple[set[str], set[str]]:
    """Flatten a schema's allOf composition into (declared property names,
    required property names), resolving local $ref members recursively.

    Property TYPES are not inspected -- this file checks the KEY SET only,
    which is what decision 92 item 4 asks for and what actually drifted
    (fieldScores/matchScoreBreakdown was a naming disagreement, not a typing
    one).
    """
    schema = schemas[name]
    properties: set[str] = set()
    required: set[str] = set()
    if "allOf" in schema:
        for member in schema["allOf"]:
            if "$ref" in member:
                ref_name = member["$ref"].rsplit("/", 1)[-1]
                sub_properties, sub_required = _resolve(schemas, ref_name)
                properties |= sub_properties
                required |= sub_required
            else:
                properties |= set(member.get("properties", {}))
                required |= set(member.get("required", []))
    else:
        properties |= set(schema.get("properties", {}))
        required |= set(schema.get("required", []))
    return properties, required


def _fully_populated_forward_entry() -> dict:
    """A forward candidate with every optional field populated, so a
    subset-of-declared comparison against the schema is, for this fixture,
    also an equality comparison -- the check that catches a declared field
    the emitter has quietly stopped producing, not just an emitted field
    the schema does not declare."""
    quality = MatchQuality(
        match_score=95.0,
        location_type=LocationType.ADDRESS_POINT,
        field_scores={"St_Name": 100.0, "Community": 80.0},
    )
    answer = ForwardAnswer(
        geometry=Point(-100.78, 46.81),
        quality=quality,
        position=Position(-100.78, 46.81),
        horizontal_uncertainty_m=12.5,
        vertical_extent_m=3.0,
        merged_count=2,
    )
    return response_json.forward_candidate(answer, pidf_lo="<xml/>")


def _fully_populated_reverse_entry() -> dict:
    quality = MatchQuality(
        match_score=88.0,
        location_type=LocationType.STREET_SEGMENT,
        field_scores={"distance": 80.0, "containment": 100.0},
    )
    answer = ReverseAnswer(
        civic=CivicAddress(St_Name="Main"),
        quality=quality,
        distance_m=12.3,
        contained=True,
        house_number_synthesised=True,
        placement="Parcel",
    )
    return response_json.reverse_candidate(answer, pidf_lo="<xml/>")


# ---------------------------------------------------------------------------
# Decision 92 item 4 — the check whose absence let the schema and the
# emitter drift apart for three sessions. Fails loudly if they ever diverge
# again, rather than relying on a human noticing.
# ---------------------------------------------------------------------------

def test_forward_candidate_keys_match_the_reconciled_yaml():
    declared, required = _resolve(_schemas(), "GeocodeCandidate")
    emitted = set(_fully_populated_forward_entry())

    assert emitted <= declared, f"emitted but not declared: {emitted - declared}"
    assert required <= emitted, f"required but not emitted: {required - emitted}"
    # A fully-populated fixture exercises every optional field too --
    # equality here is what would have caught matchScoreBreakdown's stale
    # "fieldScores" name against the reconciled draft.
    assert emitted == declared


def test_reverse_candidate_keys_match_the_reconciled_yaml():
    declared, required = _resolve(_schemas(), "ReverseGeocodeCandidate")
    emitted = set(_fully_populated_reverse_entry())

    assert emitted <= declared, f"emitted but not declared: {emitted - declared}"
    assert required <= emitted, f"required but not emitted: {required - emitted}"
    assert emitted == declared


def test_geocode_envelope_keys_match_the_reconciled_yaml():
    declared, required = _resolve(_schemas(), "GeocodeCandidateList")
    body = response_json.enhanced_response(
        [_fully_populated_forward_entry()],
        location_count=2,
        dropped=[DroppedElement(element="ca:HNO", value="bad", reason="not an integer")],
    )
    emitted = set(body)

    assert emitted <= declared, f"emitted but not declared: {emitted - declared}"
    assert required <= emitted, f"required but not emitted: {required - emitted}"
    assert emitted == declared


def test_reverse_envelope_keys_match_the_reconciled_yaml():
    """ReverseGeocodeCandidateList shares EnhancedEnvelope with the forward
    list, and response_json.enhanced_response() builds the envelope the
    same way regardless of direction -- this exercises that one
    implementation against the OTHER schema name, confirming both sides of
    the reconciled YAML agree with it."""
    declared, required = _resolve(_schemas(), "ReverseGeocodeCandidateList")
    body = response_json.enhanced_response(
        [_fully_populated_reverse_entry()],
        location_count=2,
        dropped=[DroppedElement(element="ca:HNO", value="bad", reason="not an integer")],
    )
    emitted = set(body)

    assert emitted <= declared, f"emitted but not declared: {emitted - declared}"
    assert required <= emitted, f"required but not emitted: {required - emitted}"
    assert emitted == declared


# ---------------------------------------------------------------------------
# Decision 92 item 1 — the rename itself, pinned directly rather than only
# indirectly through the schema-diff tests above
# ---------------------------------------------------------------------------

def test_the_breakdown_field_is_matchscorebreakdown_not_fieldscores():
    entry = _fully_populated_forward_entry()

    assert "matchScoreBreakdown" in entry
    assert "fieldScores" not in entry
    assert entry["matchScoreBreakdown"] == {"St_Name": 100.0, "Community": 80.0}


def test_the_breakdown_field_is_absent_when_the_engine_produced_none():
    """§10.6's reverse-side breakdown, and the forward weighted-average edge
    case, can both legitimately return an empty mapping -- absent, never an
    empty object, per the YAML's own "never partially populated" language."""
    quality = MatchQuality(
        match_score=100.0, location_type=LocationType.ADDRESS_POINT, field_scores={},
    )
    answer = ForwardAnswer(geometry=Point(0, 0), quality=quality)

    entry = response_json.forward_candidate(answer, pidf_lo="<xml/>")

    assert "matchScoreBreakdown" not in entry
