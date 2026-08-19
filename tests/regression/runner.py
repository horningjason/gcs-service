"""GCS regression runner.

Dispatches every manifest.py Case through the real service (real
data/data.gpkg, real scoring — see harness.py) and semantically compares the
reduced outcome against its golden/*.golden.json baseline. Mirrors
lvf-service's tests/regression/runner.py, including its console output shape:
a boxed header per test, the REQUEST and ACTUAL RESPONSE printed in full (not
just the reduced fields the diff runs on), EXPECTED printed only on failure,
and a "Failed / non-passing tests" recap after the results table. Golden
files store the raw response (see seed.py); parse_outcome() reduces both the
live response and the stored golden the same way, here, at compare time —
never at seed time — exactly as lvf-service's runner parses both the live
XML and the golden XML through the same `_parse_outcome()`.

Usage:
    python -m tests.regression.runner                          # run all
    python -m tests.regression.runner --test FWD-GAP-HNO-001   # run one
"""

from __future__ import annotations

import argparse
import json
import sys

from lxml import etree

from tests.regression.harness import GOLDEN_DIR, INPUTS_DIR, Response, diff, dispatch, initialize, parse_outcome
from tests.regression.manifest import CASES

# The box-drawing header below and the XML/JSON bodies this prints are not
# ASCII-safe, and some terminals (older Windows consoles, some CI runners)
# default stdout to a codepage that isn't UTF-8 — cp1252 raises
# UnicodeEncodeError on '═' outright. Reconfigure defensively; on the
# terminals where this was already fine, this is a no-op.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HEADER_WIDTH = 56


def _pretty_xml(xml_text: str) -> str:
    """Indented XML, falling back to the raw text on parse error."""
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
        return etree.tostring(root, pretty_print=True).decode()
    except Exception:
        return xml_text


def _pretty_body(body_text: str) -> str:
    """Indented body, falling back to the raw text — this suite's analogue of
    lvf-service's _pretty_xml for the actual wire content.

    The GCS has no single body format to assume: a strict 200 is XML
    (decision 116), an enhanced 200 is JSON, and 454/468 are JSON. Only the
    JSON cases need indenting here. The strict-200 body is emitted already
    indented by src/api/wire/strict_xml.py, so the raw-text fallback prints it
    correctly — and deliberately does NOT route it through _pretty_xml, which
    would re-serialise the embedded PIDF-LO's CDATA section into escaped
    entities and make the one body a reader most wants to inspect harder to
    read, not easier."""
    if not body_text:
        return "(empty body)"
    try:
        return json.dumps(json.loads(body_text), indent=2, sort_keys=True)
    except Exception:
        return body_text


def run_tests(ids: list[str] | None = None) -> int:
    if not any(INPUTS_DIR.glob("*.xml")):
        print("No fixtures in tests/regression/inputs/ — building them from data.gpkg first...")
        from tests.regression import build_inputs
        build_inputs.build()

    cases = CASES
    if ids:
        wanted = set(ids)
        cases = [c for c in CASES if c.id in wanted]
        missing = wanted - {c.id for c in cases}
        if missing:
            for m in sorted(missing):
                print(f"ERROR: no case '{m}' in manifest.py")
            return 1

    if cases and not any((GOLDEN_DIR / f"{c.id}.golden.json").exists() for c in cases):
        print("No golden files found — seeding baseline automatically...")
        from tests.regression import seed as _seed
        _seed.seed(ids=None, force=False)
        print("Seeding complete — running tests...")

    passed = failed = errors = skipped = 0
    results: list[tuple[str, str]] = []

    initialize()

    for case in cases:
        golden_path = GOLDEN_DIR / f"{case.id}.golden.json"

        print(f"\n{'═' * _HEADER_WIDTH}")
        print(f"TEST: {case.id}  ({case.target})")
        print(f"{'═' * _HEADER_WIDTH}")

        request_text = (INPUTS_DIR / f"{case.id}.xml").read_text(encoding="utf-8")
        print(f"\nREQUEST:\n{_pretty_xml(request_text)}")

        if not golden_path.exists():
            print("SKIP  (no golden file — run seed.py first)")
            skipped += 1
            results.append((case.id, "SKIP"))
            continue

        try:
            response = dispatch(case)
        except Exception as exc:
            print(f"ACTUAL RESPONSE:\n(dispatch raised: {exc!r})")
            print("\nERROR")
            errors += 1
            results.append((case.id, "ERROR"))
            continue

        print(f"ACTUAL RESPONSE (status {response['status']}):\n{_pretty_body(response['body'])}")

        golden_raw = Response(**json.loads(golden_path.read_text(encoding="utf-8")))
        actual = parse_outcome(response)
        expected = parse_outcome(golden_raw)
        mismatches = diff(actual, expected)

        if mismatches:
            print(f"EXPECTED (status {golden_raw['status']}):\n{_pretty_body(golden_raw['body'])}")
            print("Differences:")
            for m in mismatches:
                print(f"  {m}")
            print("\nFAIL")
            failed += 1
            results.append((case.id, "FAIL"))
        else:
            print("\nPASS")
            passed += 1
            results.append((case.id, "PASS"))

    print("\n--- RESULTS ---")
    for name, status in results:
        print(f"  {status:<5}  {name}")

    total = passed + failed + errors + skipped
    parts = [f"{passed}/{total} passed"]
    if failed:
        parts.append(f"{failed} failed")
    if errors:
        parts.append(f"{errors} errors")
    if skipped:
        parts.append(f"{skipped} skipped")
    print(f"\n{', '.join(parts)}")

    non_passing = [(n, s) for n, s in results if s != "PASS"]
    if non_passing:
        print("\nFailed / non-passing tests:")
        for name, status in non_passing:
            print(f"  {status:<5}  {name}")

    return 0 if (failed == 0 and errors == 0) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="GCS regression runner")
    parser.add_argument("--test", metavar="ID", help="Run only this case ID")
    args = parser.parse_args()
    sys.exit(run_tests([args.test] if args.test else None))


if __name__ == "__main__":
    main()
