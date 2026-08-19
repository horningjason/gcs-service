"""GCS golden file seeder.

Run ONCE to establish the baseline, mirroring lvf-service's
tests/regression/seed.py. Never re-run except to deliberately reset the
baseline after a reviewed, intentional behaviour change — see README.md.

Usage:
    python -m tests.regression.seed                         # seed all, skip existing
    python -m tests.regression.seed --force                 # overwrite all
    python -m tests.regression.seed --force FWD-GAP-HNO-001  # overwrite one by ID
"""

from __future__ import annotations

import argparse
import json
import sys

from tests.regression.harness import GOLDEN_DIR, INPUTS_DIR, dispatch, initialize
from tests.regression.manifest import CASES


def seed(ids: list[str] | None, force: bool) -> int:
    if not any(INPUTS_DIR.glob("*.xml")):
        print("No fixtures in tests/regression/inputs/ — building them from data.gpkg first...")
        from tests.regression import build_inputs
        build_inputs.build()

    GOLDEN_DIR.mkdir(exist_ok=True)

    cases = CASES
    if ids:
        wanted = set(ids)
        cases = [c for c in CASES if c.id in wanted]
        missing = wanted - {c.id for c in cases}
        for m in sorted(missing):
            print(f"ERROR: no case '{m}' in manifest.py")
        if missing:
            return 1

    initialize()

    wrote = skipped = 0
    for case in cases:
        golden_path = GOLDEN_DIR / f"{case.id}.golden.json"
        if golden_path.exists() and not force:
            print(f"SKIP  {case.id}  (already seeded — use --force to overwrite)")
            skipped += 1
            continue
        response = dispatch(case)
        # Raw, not reduced — mirrors lvf-service's golden files, which store
        # the actual response bytes rather than a pre-parsed summary. The
        # semantic reduction (harness.parse_outcome) runs at compare time in
        # runner.py, on both the live response AND the stored golden alike,
        # so a golden file is a faithful wire capture a human can read, and
        # a future change to what parse_outcome extracts doesn't silently
        # invalidate every already-seeded baseline.
        golden_path.write_text(json.dumps(response, indent=2, sort_keys=True), encoding="utf-8")
        action = "OVERWROTE" if golden_path.exists() and force else "WROTE"
        print(f"{action}  {case.id}  ->  status={response['status']}")
        wrote += 1

    print(f"\n{wrote} written, {skipped} skipped")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GCS regression golden file seeder — run once only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing golden files")
    parser.add_argument("ids", nargs="*", metavar="ID", help="Case ID(s) to seed (default: all)")
    args = parser.parse_args()
    sys.exit(seed(args.ids or None, args.force))


if __name__ == "__main__":
    main()
