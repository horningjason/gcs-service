"""Shared machinery for seed.py and runner.py: initialize the real service
against the real data.gpkg, dispatch a manifest Case through it, and reduce
a response to the fields worth comparing.

UNLIKE tests/conformance/, THIS IS THE REAL ENGINE

tests/conformance/ injects scoring_stubs and a two-record in-memory GIS
fixture on purpose, to isolate the wire/admission/assembly logic from the
proprietary scoring formula (§6.5, §10.6 — Appendix C item (d)). This harness
does the opposite: `initialize()` (src/app/lifecycle.py) loads the real
data/data.gpkg and registers the real (if still unweighted-by-data)
scoring.py functions.

NO ASGI, NO TESTCLIENT, NO PORT — MATCHING lvf-service/tests/regression/

`lifecycle.initialize()` is this module's own documented "synchronous
startup for tests and tooling that do not run the ASGI lifespan" — it skips
NtpClient construction, the SIP listener, and the GIS watcher thread
entirely, rather than requiring them to be faked or disabled. Each of the
four resources' route handlers (src/api/geocode.py etc.) is a thin wrapper
around plain functions — `admit()`, `conversion.geocode()` /
`conversion.reverse_geocode()`, `response_json.*`, `status.*` — that take and
return plain values, not a FastAPI Request/Response cycle; `_dispatch_*`
below calls those functions directly, the same way lvf-service's
`tests/regression/runner.py` calls `handle_find_service(xml_bytes)` directly
rather than going through `src.server`'s ASGI app. Skipped relative to the
real route handlers: the query/response LogEvent emission wrapped around
them in src/api/geocode.py and src/api/reverse_geocode.py — out of scope for
a suite regressing conversion outcomes, not wire logging (that's
tests/conformance/test_log_events.py's job).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from lxml import etree
from starlette.responses import Response as StarletteResponse

from tests.regression.manifest import Case, GEOCODE, GEOCODE_ENH, REVERSE, REVERSE_ENH

load_dotenv()

INPUTS_DIR = Path(__file__).parent / "inputs"
GOLDEN_DIR = Path(__file__).parent / "golden"


def initialize() -> None:
    """Load the schema, register scorers, load data/data.gpkg. Call once."""
    from src.app import lifecycle

    lifecycle.initialize()


# ---------------------------------------------------------------------------
# Dispatch — read a fixture, run it through the plain conversion functions
# the real route handlers wrap, the way lvf-service's runner calls
# handle_find_service() directly rather than through src.server's ASGI app.
# ---------------------------------------------------------------------------

class Response(dict):
    """status/headers/body, as a plain dict so it round-trips through JSON."""


def _to_response(resp: StarletteResponse) -> Response:
    return Response(
        status=resp.status_code,
        headers=dict(resp.headers),
        body=resp.body.decode("utf-8", errors="replace"),
    )


def _dispatch_geocode(raw_body: bytes, content_type: str) -> Response:
    from src.api import conversion
    from src.api.admission import AdmissionError, Profile, admit
    from src.api.status import error_response, failure_response, no_result_response, success_xml_response
    from src.api.wire import strict_xml
    from src.app import lifecycle
    from src.engine.scoring_registry import ScorerUnavailable

    try:
        admitted = admit(raw_body, content_type, Profile.CIVIC, lifecycle._schema)
    except AdmissionError as exc:
        return _to_response(failure_response(exc))

    try:
        converted = conversion.geocode(admitted)
        answer = conversion.strict_forward_answer(converted)
    except conversion.AmbiguousResult as exc:
        return _to_response(no_result_response(str(exc)))
    except ScorerUnavailable as exc:
        return _to_response(error_response(str(exc)))

    if answer is None:
        return _to_response(no_result_response("No candidate was derivable for the query address."))
    return _to_response(success_xml_response(
        strict_xml.geodetic_data_xml(conversion.forward_document(answer, admitted))
    ))


def _dispatch_reverse(raw_body: bytes, content_type: str) -> Response:
    from src.api import conversion
    from src.api.admission import AdmissionError, Profile, admit
    from src.api.status import error_response, failure_response, no_result_response, success_xml_response
    from src.api.wire import strict_xml
    from src.api.wire.gml_xml import GmlParseError
    from src.app import lifecycle
    from src.engine.scoring_registry import ScorerUnavailable

    try:
        admitted = admit(raw_body, content_type, Profile.GEODETIC, lifecycle._schema)
    except AdmissionError as exc:
        return _to_response(failure_response(exc))

    try:
        converted = conversion.reverse_geocode(admitted)
    except GmlParseError as exc:
        return _to_response(error_response(f"Geodetic location could not be read: {exc}."))
    except ScorerUnavailable as exc:
        return _to_response(error_response(str(exc)))

    if not converted.found:
        return _to_response(no_result_response(
            "No feature fell within GCS_REVERSE_SEARCH_RADIUS_M of the origin."
        ))
    return _to_response(success_xml_response(
        strict_xml.civic_address_xml(conversion.reverse_document(converted.answers[0], admitted))
    ))


def _dispatch_geocode_enhanced(raw_body: bytes, content_type: str) -> Response:
    from src.api import conversion
    from src.api.admission import AdmissionError, Profile, admit
    from src.api.status import error_response, failure_response, no_result_response, success_response
    from src.api.wire import response_json
    from src.app import lifecycle
    from src.engine.scoring_registry import ScorerUnavailable

    try:
        admitted = admit(raw_body, content_type, Profile.CIVIC, lifecycle._schema)
    except AdmissionError as exc:
        return _to_response(failure_response(exc))

    try:
        converted = conversion.geocode(admitted)
    except ScorerUnavailable as exc:
        return _to_response(error_response(str(exc)))

    if not converted.found:
        return _to_response(no_result_response("No candidate was derivable for the query address."))
    candidates = [
        response_json.forward_candidate(
            answer, conversion.forward_record_document(candidate, answer, admitted)
        )
        for candidate, answer in conversion.enhanced_forward_answers(converted)
    ]
    return _to_response(success_response(
        response_json.enhanced_response(
            candidates, location_count=admitted.location_count, dropped=converted.dropped
        )
    ))


def _dispatch_reverse_enhanced(raw_body: bytes, content_type: str) -> Response:
    from src.api import conversion
    from src.api.admission import AdmissionError, Profile, admit
    from src.api.status import error_response, failure_response, no_result_response, success_response
    from src.api.wire import response_json
    from src.api.wire.gml_xml import GmlParseError
    from src.app import lifecycle
    from src.engine.scoring_registry import ScorerUnavailable

    try:
        admitted = admit(raw_body, content_type, Profile.GEODETIC, lifecycle._schema)
    except AdmissionError as exc:
        return _to_response(failure_response(exc))

    try:
        converted = conversion.reverse_geocode(admitted)
    except GmlParseError as exc:
        return _to_response(error_response(f"Geodetic location could not be read: {exc}."))
    except ScorerUnavailable as exc:
        return _to_response(error_response(str(exc)))

    if not converted.found:
        return _to_response(no_result_response(
            "No feature fell within GCS_REVERSE_SEARCH_RADIUS_M of the origin."
        ))
    candidates = [
        response_json.reverse_candidate(answer, conversion.reverse_record_document(answer, admitted))
        for answer in converted.answers
    ]
    return _to_response(success_response(
        response_json.enhanced_response(candidates, location_count=admitted.location_count)
    ))


_ROUTES: dict[str, Callable[[bytes, str], Response]] = {
    GEOCODE: _dispatch_geocode,
    REVERSE: _dispatch_reverse,
    GEOCODE_ENH: _dispatch_geocode_enhanced,
    REVERSE_ENH: _dispatch_reverse_enhanced,
}


def dispatch(case: Case) -> Response:
    text = (INPUTS_DIR / f"{case.id}.xml").read_bytes().decode("utf-8")
    if case.json_wrap:
        body = json.dumps(text).encode("utf-8")
        content_type = "application/json"
    else:
        body = text.encode("utf-8")
        content_type = "application/xml"
    return _ROUTES[case.target](body, content_type)


# ---------------------------------------------------------------------------
# Semantic reduction — an XML or JSON wrapper carrying an XML string, per
# src/api/wire/strict_xml.py (strict 200) and response_json.py (enhanced 200).
# parse_outcome() below branches on the response content type; _extract_pidf()
# is shared, since the embedded PIDF-LO is the same document either way.
# ---------------------------------------------------------------------------

_NS_GML = "http://www.opengis.net/gml"
_NS_GS = "http://www.opengis.net/pidflo/1.0"
_NS_CIVIC = "urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr"
_NS_CONF = "urn:ietf:params:xml:ns:geopriv:conf"
_PARSER = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)


def _q(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def _extract_pidf(xml_text: str) -> dict[str, Any]:
    """Reduce one embedded PIDF-LO document to its comparable substance:
    the presentity entity, the civic fields (if any), and the geodetic shape
    (if any) — a Point's coordinates or a LineString's posList, never both
    (§8.1/§8.2's forward answer carries exactly one)."""
    root = etree.fromstring(xml_text.encode("utf-8"), _PARSER)
    entity = root.get("entity")

    civic_el = root.find(f".//{_q(_NS_CIVIC, 'civicAddress')}")
    civic = None
    if civic_el is not None:
        civic = {}
        for child in civic_el:
            local = child.tag.split("}")[-1]
            civic[local] = (child.text or "").strip()

    geo = None
    point_el = root.find(f".//{_q(_NS_GML, 'Point')}")
    line_el = root.find(f".//{_q(_NS_GML, 'LineString')}")
    circle_el = root.find(f".//{_q(_NS_GS, 'Circle')}")
    if point_el is not None:
        pos = point_el.find(f".//{_q(_NS_GML, 'pos')}")
        coords = [round(float(v), 6) for v in (pos.text or "").split()] if pos is not None else []
        geo = {"kind": "Point", "srsName": point_el.get("srsName"), "coords": coords}
    elif line_el is not None:
        pos_list = line_el.find(f".//{_q(_NS_GML, 'posList')}")
        coords = [round(float(v), 6) for v in (pos_list.text or "").split()] if pos_list is not None else []
        geo = {
            "kind": "LineString",
            "srsName": line_el.get("srsName"),
            "srsDimension": pos_list.get("srsDimension") if pos_list is not None else None,
            "coords": coords,
        }
    elif circle_el is not None:
        # §6.3 (Session 2)'s strict-interface merge: a centroid with
        # uncertainty sized to the qualifying candidates' extent, on EITHER
        # rung — RCL-only candidates that agree within tolerance merge into
        # a Circle exactly as SSAP ones do (§6.3 draws no rung distinction).
        pos = circle_el.find(f".//{_q(_NS_GML, 'pos')}")
        radius_el = circle_el.find(f".//{_q(_NS_GS, 'radius')}")
        coords = [round(float(v), 6) for v in (pos.text or "").split()] if pos is not None else []
        geo = {
            "kind": "Circle",
            "srsName": circle_el.get("srsName"),
            "coords": coords,
            "radius": round(float(radius_el.text), 3) if radius_el is not None and radius_el.text else None,
        }

    confidence_el = root.find(f".//{_q(_NS_CONF, 'confidence')}")
    confidence = round(float(confidence_el.text), 3) if confidence_el is not None and confidence_el.text else None

    return {"entity": entity, "civic": civic, "geo": geo, "confidence": confidence}


def _extract_candidate(entry: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in entry.items() if k != "pidfLo"}
    if "pidfLo" in entry:
        out["doc"] = _extract_pidf(entry["pidfLo"])
    return out


def parse_outcome(response: Response) -> dict[str, Any]:
    """Reduce a raw Response to the fields a regression comparison cares
    about. Every code in the closed set (§8.4, §12.3) is handled; anything
    else is recorded as 'unexpected_status' rather than raising, so the diff
    output — not a traceback — is what tells a reader the response drifted."""
    status = response["status"]
    outcome: dict[str, Any] = {"status": status}

    if status == 307:
        outcome["location"] = response["headers"].get("location")
        return outcome
    if status in (454, 468):
        # 468's reason is fixed and non-distinguishing (decision 114) rather
        # than the admission/conversion-specific text that triggered it —
        # extracted the same way as 454's regardless, so a regression that
        # silently reintroduces a distinguishing 468 reason (or drops the
        # body entirely) shows up as a diff, not a passing test.
        body = response["body"]
        outcome["reason"] = json.loads(body).get("reason") if body else None
        return outcome
    if status != 200:
        outcome["kind"] = "unexpected_status"
        return outcome

    content_type = response["headers"].get("content-type", "")
    if content_type.startswith("application/xml"):
        # Strict interface (decision 116) — real XML, not JSON:
        # <GeodeticData><pidfLoGeo>CDATA</pidfLoGeo></GeodeticData> or
        # <CivicAddress><pidfLoAddress>CDATA</pidfLoAddress></CivicAddress>.
        root = etree.fromstring(response["body"].encode("utf-8"), _PARSER)
        if root.tag == "GeodeticData":
            outcome["kind"] = "strict_forward"
            outcome["doc"] = _extract_pidf(root.find("pidfLoGeo").text)
        elif root.tag == "CivicAddress":
            outcome["kind"] = "strict_reverse"
            outcome["doc"] = _extract_pidf(root.find("pidfLoAddress").text)
        else:
            outcome["kind"] = "unrecognized_200_xml"
            outcome["raw"] = response["body"]
        return outcome

    payload = json.loads(response["body"])
    if "candidates" in payload:
        outcome["kind"] = "enhanced"
        outcome["locationCount"] = payload.get("locationCount", 1)
        outcome["droppedElements"] = payload.get("droppedElements", [])
        outcome["candidates"] = [_extract_candidate(c) for c in payload["candidates"]]
    else:
        outcome["kind"] = "unrecognized_200_body"
        outcome["raw"] = payload
    return outcome


# ---------------------------------------------------------------------------
# Diff — generic structural comparison over the outcome dict, positional on
# lists (candidate rank order is meaningful — §10.3's order is preserved
# exactly, not re-sorted), reported as one human-readable line per mismatch.
# ---------------------------------------------------------------------------

def diff(actual: Any, expected: Any, path: str = "$") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: got {actual!r} ({type(actual).__name__}), expected an object"]
        out: list[str] = []
        for key in sorted(set(actual) | set(expected)):
            if key not in actual:
                out.append(f"{path}.{key}: missing (expected {expected[key]!r})")
            elif key not in expected:
                out.append(f"{path}.{key}: unexpected ({actual[key]!r})")
            else:
                out.extend(diff(actual[key], expected[key], f"{path}.{key}"))
        return out

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: got {actual!r} ({type(actual).__name__}), expected a list"]
        out = []
        if len(actual) != len(expected):
            out.append(f"{path}: {len(actual)} entries, expected {len(expected)}")
        for i, (a, e) in enumerate(zip(actual, expected)):
            out.extend(diff(a, e, f"{path}[{i}]"))
        return out

    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if abs(float(actual) - float(expected)) > 1e-6:
            return [f"{path}: {actual!r} != expected {expected!r}"]
        return []

    if actual != expected:
        return [f"{path}: {actual!r} != expected {expected!r}"]
    return []
