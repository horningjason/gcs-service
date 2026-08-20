#!/usr/bin/env python3
"""Standalone latency probe for POST /Gcs/v1/GeocodeEnhanced against real
addresses drawn from data.gpkg.

Not part of pytest or tests/regression/ — run manually against a live
service (docker-compose or `python main.py`). Reuses
tests.regression.build_inputs's Fixtures class for GeoPackage loading and
field filtering (dropping null/zero Add_Number and blank St_Name/A3) and its
civic_chunk()/presence()/_tuple() helpers for request-body templating, rather
than reimplementing either.

    python tools/perf_geocode_enhanced.py
    python tools/perf_geocode_enhanced.py --n 200 --concurrency 8
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.regression.build_inputs import Fixtures, _pos_direction, civic_chunk, presence, _tuple  # noqa: E402

_HNO_RE = re.compile(r"<ca:HNO>(.*?)</ca:HNO>")
_RD_RE = re.compile(r"<ca:RD>(.*?)</ca:RD>")


@dataclass
class Result:
    address: str
    status: int
    latency_ms: float
    matched: Optional[bool]


def _build_query(row: "pd.Series") -> tuple[str, str]:
    """A plain civicAddress query built from `row`'s own fields, mirroring
    build_inputs.build()'s exact_civic()/quiet_civic() pattern.

    Returns (address_label, request_body).
    """
    sts = row["St_PosTyp"] if pd.notna(row.get("St_PosTyp")) else ""
    hno = int(row["Add_Number"])
    chunk = civic_chunk(
        a2=row["A2"], a3=row["A3"], rd=row["St_Name"], sts=sts, hno=hno,
        pod=_pos_direction(row), st_pretyp=row.get("St_PreTyp"),
    )
    body = presence(_tuple(chunk))
    label = f"{hno} {row['St_Name']} {sts}, {row['A3']}"
    return label, body


def _check_match(hno: int, street: str, body: bytes) -> Optional[bool]:
    """Best-effort sanity signal: does candidates[0]'s pidfLo carry the same
    Add_Number/St_Name back? Not a strict pass/fail gate — this is a perf
    tool, not a conformance test.
    """
    try:
        import json

        data = json.loads(body)
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        pidf_lo = candidates[0].get("pidfLo", "")
        hno_match = _HNO_RE.search(pidf_lo)
        rd_match = _RD_RE.search(pidf_lo)
        if hno_match is None or rd_match is None:
            return None
        return hno_match.group(1).strip() == str(hno) and rd_match.group(1).strip() == street
    except Exception:
        return None


def _fire(client: httpx.Client, url: str, label: str, body: str, hno: int, street: str) -> Result:
    start = time.perf_counter()
    try:
        resp = client.post(
            url, content=body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        status = resp.status_code
        matched = _check_match(hno, street, resp.content) if status == 200 else None
        return Result(label, status, elapsed_ms, matched)
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return Result(label, -1, elapsed_ms, None)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--gpkg-path", default=os.environ.get("GCS_GPKG_PATH", "data/data.gpkg"))
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=10)
    args = parser.parse_args()

    if not os.path.exists(args.gpkg_path):
        raise SystemExit(f"--gpkg-path {args.gpkg_path!r} not found.")

    print(f"Loading {args.gpkg_path} ...")
    fx = Fixtures(args.gpkg_path)
    n = min(args.n, len(fx.ssap))
    sample = fx.ssap.sample(n=n, random_state=args.seed)
    print(f"Sampled {n} SSAP records (seed={args.seed}).")

    queries = [_build_query(row) for _, row in sample.iterrows()]
    hnos = [int(row["Add_Number"]) for _, row in sample.iterrows()]
    streets = [row["St_Name"] for _, row in sample.iterrows()]

    url = f"{args.base_url}/Gcs/v1/GeocodeEnhanced"

    with httpx.Client(timeout=30.0) as client:
        if args.warmup > 0:
            print(f"Warming up ({args.warmup} requests, discarded) ...")
            for i in range(min(args.warmup, len(queries))):
                label, body = queries[i]
                _fire(client, url, label, body, hnos[i], streets[i])

        print(f"Firing {n} requests at {url} (concurrency={args.concurrency}) ...")
        wall_start = time.perf_counter()
        results: list[Result] = []

        if args.concurrency <= 1:
            for i, (label, body) in enumerate(queries):
                results.append(_fire(client, url, label, body, hnos[i], streets[i]))
        else:
            def worker(i: int) -> Result:
                label, body = queries[i]
                with httpx.Client(timeout=30.0) as thread_client:
                    return _fire(thread_client, url, label, body, hnos[i], streets[i])

            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                results = list(pool.map(worker, range(n)))

        wall_elapsed_s = time.perf_counter() - wall_start

    ok = [r for r in results if r.status == 200]
    bad = [r for r in results if r.status != 200]
    latencies = sorted(r.latency_ms for r in ok)

    print()
    print("=" * 60)
    print("LATENCY (successful 200 responses only)" + (
        " — SEQUENTIAL, single-request timing" if args.concurrency <= 1
        else " — reported alongside throughput-under-load below; do not"
        " read as single-request latency"
    ))
    print("=" * 60)
    if latencies:
        print(f"  count : {len(latencies)}")
        print(f"  min   : {latencies[0]:.2f} ms")
        print(f"  p50   : {_percentile(latencies, 50):.2f} ms")
        print(f"  p90   : {_percentile(latencies, 90):.2f} ms")
        print(f"  p95   : {_percentile(latencies, 95):.2f} ms")
        print(f"  p99   : {_percentile(latencies, 99):.2f} ms")
        print(f"  max   : {latencies[-1]:.2f} ms")
        print(f"  mean  : {sum(latencies) / len(latencies):.2f} ms")
    else:
        print("  no successful responses")
    print(f"  total wall-clock : {wall_elapsed_s:.2f} s")

    if args.concurrency > 1:
        print()
        print(f"THROUGHPUT UNDER LOAD (concurrency={args.concurrency})")
        print(f"  {n / wall_elapsed_s:.2f} requests/sec")

    print()
    print("NON-200 RESPONSES")
    if bad:
        from collections import Counter

        counts = Counter(r.status for r in bad)
        breakdown = ", ".join(f"{count} x {status}" for status, count in sorted(counts.items()))
        print(f"  {len(bad)} total: {breakdown}")
    else:
        print("  none")

    mismatches = [r for r in ok if r.matched is False]
    if mismatches:
        print(f"\n  {len(mismatches)} of {len(ok)} 200 responses did not echo back the "
              "same HNO/street on candidates[0] (best-effort sanity signal only).")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = Path(f"perf_geocode_enhanced_{timestamp}.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "status", "latency_ms", "candidate0_matched"])
        for r in results:
            writer.writerow([r.address, r.status, f"{r.latency_ms:.3f}", r.matched])
    print(f"\nWrote {len(results)} raw results to {csv_path}")


if __name__ == "__main__":
    main()
