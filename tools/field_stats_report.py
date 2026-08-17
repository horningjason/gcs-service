#!/usr/bin/env python3
"""Print §6.5/§10.6 deployment discriminative factors against a real GeoPackage.

Run this against data.gpkg BEFORE trusting src/engine/scoring.py's weights in
a real deployment — it's the direct check on the claim behind the whole
design: that Country/A1 read as low-discriminative and Street Name/Community
read as high-discriminative on the ND data, not just in theory.

Usage:
    python tools/field_stats_report.py /path/to/data.gpkg
    python tools/field_stats_report.py /path/to/data.gpkg --ssap-layer SiteStructureAddressPoint --rcl-layer RoadCenterLine

Deliberately standalone — does not start the ASGI app, touch runtime_state,
or require GCS_GPKG_PATH to be set. Reads the two layers directly the same
way src/gis/provisioning.py does, then reports src/gis/field_stats.py's
measurement without registering anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gis import field_stats  # noqa: E402
from src.gis import records as gis_records  # noqa: E402


def _read_layer(gpkg_path: str, layer_name: str, converter):
    import geopandas as gpd

    gdf = gpd.read_file(gpkg_path, layer=layer_name, engine="pyogrio")
    geom_col = gdf.geometry.name
    return [converter(row, fid, geom_col) for fid, row in gdf.iterrows()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpkg_path")
    parser.add_argument("--ssap-layer", default="SiteStructureAddressPoint")
    parser.add_argument("--rcl-layer", default="RoadCenterLine")
    args = parser.parse_args()

    print(f"Reading {args.ssap_layer!r} from {args.gpkg_path} ...")
    ssap = _read_layer(args.gpkg_path, args.ssap_layer, gis_records.row_to_ssap)
    print(f"  {len(ssap)} SSAP records")

    print(f"Reading {args.rcl_layer!r} from {args.gpkg_path} ...")
    rcl = _read_layer(args.gpkg_path, args.rcl_layer, gis_records.row_to_rcl)
    print(f"  {len(rcl)} RCL records")

    field_stats.recompute(ssap, rcl)
    snapshot = field_stats.report()

    for layer_name, factors in (("SSAP", snapshot["ssap"]), ("RCL (pooled L/R)", snapshot["rcl"])):
        print(f"\n{layer_name} discriminative factors (1 - max_frequency):")
        print(f"  {'field':<12} {'factor':>8} {'n':>10}   note")
        for field, (factor, n) in sorted(factors.items(), key=lambda kv: -kv[1][0]):
            note = ""
            if n == 0:
                note = "no populated values observed"
            elif n < field_stats._MIN_POPULATION:
                note = (
                    f"population {n} below the {field_stats._MIN_POPULATION}-record "
                    f"floor — factor defaulted to 1.0, not a real measurement"
                )
            elif factor < 0.02:
                note = "near-constant in this deployment — treat as a given"
            print(f"  {field:<12} {factor:>8.4f} {n:>10}   {note}")


if __name__ == "__main__":
    main()
