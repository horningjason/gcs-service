"""TEMPORARY, one-time script — not part of the test suite, not committed.

Runs every tests/regression/inputs/*.xml fixture through the real engine
(same harness.dispatch() the regression runner uses — real data.gpkg, real
scoring, no ASGI/TestClient) and writes the request and response for each,
pretty-printed, to regression_review.txt for manual review.

Delete both this script and regression_review.txt when done reviewing —
neither is meant to stick around.

Run:
    python review_regression_output.py
"""

from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from tests.regression.harness import INPUTS_DIR, dispatch, initialize
from tests.regression.manifest import CASES

OUT_PATH = Path(__file__).parent / "regression_review.txt"
_WIDTH = 78


def _pretty_xml(text: str) -> str:
    try:
        root = etree.fromstring(text.encode("utf-8"))
        etree.indent(root, space="  ")  # re-indents even an already-compact tree
        return etree.tostring(root, pretty_print=True).decode("utf-8")
    except Exception:
        return text


def _looks_like_xml(value: str) -> bool:
    stripped = value.lstrip()
    return stripped.startswith("<?xml") or stripped.startswith("<presence")


def _render(value, indent: int, out: list[str]) -> None:
    """Walk a parsed response body and emit a YAML-like, human-readable
    rendering — the point being that string fields carrying embedded PIDF-LO
    (pidfLoGeo/pidfLoAddress/candidates[].pidfLo) get rendered as real
    multi-line indented XML instead of a JSON-escaped one-liner full of
    literal \\n sequences."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            out.append(f"{pad}{{}}")
            return
        for key, val in value.items():
            if isinstance(val, str) and _looks_like_xml(val):
                out.append(f"{pad}{key}:")
                inner_pad = "  " * (indent + 1)
                for line in _pretty_xml(val).rstrip("\n").splitlines():
                    out.append(f"{inner_pad}{line}")
            elif isinstance(val, (dict, list)) and val:
                out.append(f"{pad}{key}:")
                _render(val, indent + 1, out)
            else:
                out.append(f"{pad}{key}: {json.dumps(val)}")
    elif isinstance(value, list):
        if not value:
            out.append(f"{pad}[]")
            return
        for i, item in enumerate(value):
            if isinstance(item, (dict, list)):
                out.append(f"{pad}- [{i}]")
                _render(item, indent + 1, out)
            else:
                out.append(f"{pad}- {json.dumps(item)}")
    else:
        out.append(f"{pad}{json.dumps(value)}")


def _pretty_body(text: str) -> str:
    if not text:
        return "(empty body)"
    try:
        payload = json.loads(text)
    except Exception:
        return text
    out: list[str] = []
    _render(payload, 0, out)
    return "\n".join(out)


def main() -> None:
    initialize()

    # CASES is ordered narratively in manifest.py (grouped by ADM/FWD/REV,
    # not alphabetically within each group). Sorted here by case.id instead,
    # matching how tests/regression/inputs/*.xml sorts in VS Code's Explorer
    # (plain alphabetical — every fixture is FLAT under one directory with a
    # zero-padded numeric suffix, so lexicographic and natural sort agree).
    ordered_cases = sorted(CASES, key=lambda c: c.id)

    sections: list[str] = []
    for case in ordered_cases:
        request_text = (INPUTS_DIR / f"{case.id}.xml").read_text(encoding="utf-8")
        response = dispatch(case)

        sections.append("=" * _WIDTH)
        sections.append(f"{case.id}  ->  {case.target}")
        sections.append("=" * _WIDTH)
        sections.append("")
        sections.append("REQUEST:")
        sections.append(_pretty_xml(request_text).rstrip())
        sections.append("")
        sections.append(f"RESPONSE (status {response['status']}):")
        sections.append(_pretty_body(response["body"]).rstrip())
        sections.append("")

    OUT_PATH.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {len(ordered_cases)} request/response pairs to {OUT_PATH}")


if __name__ == "__main__":
    main()
