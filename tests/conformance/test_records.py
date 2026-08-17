"""The STA-006.3 row -> record layer (src/gis/records.py).

Covers the two behaviours the rest of the algorithm silently depends on: text
normalisation (R4) and geometry preservation, including RCL Z (R1).
"""

from __future__ import annotations

import json

import pytest

from src.gis import records
from src.gis.records import (
    RCL_COLUMNS,
    RCL_EXCLUDED,
    SSAP_COLUMNS,
    SSAP_EXCLUDED,
    RCLRecord,
    SSAPRecord,
    dict_to_rcl,
    dict_to_ssap,
    rcl_to_dict,
    ssap_to_dict,
)


class _Geom:
    def __init__(self, wkt: str) -> None:
        self.wkt = wkt


# ---------------------------------------------------------------------------
# Text normalisation (R4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Bismarck", "Bismarck"),
    ("Bismarck ", "Bismarck"),       # trailing pad — 1549/5000 rows carry this
    ("  Bismarck", "Bismarck"),
    ("  Bismarck  ", "Bismarck"),
    ("Grand Forks", "Grand Forks"),  # interior whitespace preserved
    (" ", None),                     # the Valid_L case
    ("", None),
    ("   ", None),
    (None, None),
])
def test_text_is_stripped_and_blanks_become_none(raw, expected):
    assert records._plain(raw) == expected


def test_numeric_values_are_not_touched():
    assert records._plain(3401) == 3401
    assert records._plain(0.0) == 0.0  # Elevation 0.0 is a value, not absence


def test_nan_becomes_none():
    assert records._plain(float("nan")) is None


def test_padded_values_would_otherwise_break_matching():
    """The concrete failure R4 prevents: an exact or case-insensitive-exact
    comparison against a fixed-width-padded value."""
    stored_raw = "Bismarck "
    assert stored_raw.upper() != "Bismarck".upper()
    assert records._plain(stored_raw).upper() == "Bismarck".upper()


# ---------------------------------------------------------------------------
# Row conversion
# ---------------------------------------------------------------------------

def test_row_to_ssap_selects_and_normalises():
    row = {
        "geometry": _Geom("POINT Z (-100.9 46.8 512)"),
        "NGUID": "{ABC}", "Add_Number": 701, "St_Name": " 16th ",
        "A3": "Mandan ", "A4": "   ", "Elevation": 0.0, "Placement": 1,
        # excluded — must not appear on the record
        "ESN": "123", "DateUpdate": "2025-04-11", "AddDataURI": "x",
    }
    rec = records.row_to_ssap(row, 7)
    assert rec.fid == 7
    assert rec.geometry_wkt == "POINT Z (-100.9 46.8 512)"
    assert rec.St_Name == "16th"
    assert rec.A3 == "Mandan"
    assert rec.A4 is None
    assert rec.Elevation == 0.0
    assert not hasattr(rec, "ESN")


def test_row_to_rcl_preserves_z():
    """R1: the record layer keeps RCL Z. §7.3 declines to PROPAGATE it to a
    rung-2 forward result, but §10.5's reverse vertical band ordering reads
    this same geometry — stripping it here to serve a forward-side decision
    would push every RCL candidate into the lower band."""
    row = {
        "geometry": _Geom("MULTILINESTRING Z ((-101.7 46.8 500, -101.6 46.9 505))"),
        "NGUID": "{DEF}", "FromAddr_L": 100, "ToAddr_L": 188,
        "Parity_L": "E", "Valid_L": " ", "St_Name": "State",
    }
    rec = records.row_to_rcl(row, 3)
    assert "MULTILINESTRING Z" in rec.geometry_wkt
    assert rec.Valid_L is None
    assert rec.Parity_L == "E"


def test_missing_columns_default_to_none():
    rec = records.row_to_ssap({"geometry": _Geom("POINT (0 0)")}, 0)
    assert rec.NGUID is None and rec.Add_Number is None


# ---------------------------------------------------------------------------
# Cache round-trip
# ---------------------------------------------------------------------------

def test_serialisation_omits_nulls():
    """The single biggest lever on cache size — a key absent means None."""
    rec = SSAPRecord(fid=1, NGUID="{ABC}", Add_Number=701, geometry_wkt="POINT (0 0)")
    d = ssap_to_dict(rec)
    assert d == {"fid": 1, "NGUID": "{ABC}", "Add_Number": 701, "geometry_wkt": "POINT (0 0)"}
    assert "A4" not in d and "Floor" not in d


@pytest.mark.parametrize("record,to_dict,from_dict", [
    (SSAPRecord(fid=1, NGUID="{A}", A3="Mandan", Elevation=0.0,
                geometry_wkt="POINT Z (1 2 3)"), ssap_to_dict, dict_to_ssap),
    (RCLRecord(fid=2, NGUID="{B}", FromAddr_L=100, ToAddr_L=188, Parity_L="E",
               geometry_wkt="MULTILINESTRING Z ((1 2 3, 4 5 6))"), rcl_to_dict, dict_to_rcl),
])
def test_round_trip_through_json_is_lossless(record, to_dict, from_dict):
    revived = from_dict(json.loads(json.dumps(to_dict(record))))
    assert revived == record


# ---------------------------------------------------------------------------
# Column selection hygiene
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("columns,cls", [(SSAP_COLUMNS, SSAPRecord), (RCL_COLUMNS, RCLRecord)])
def test_every_selected_column_exists_on_the_model(columns, cls):
    names = {f.name for f in cls.__dataclass_fields__.values()}
    missing = set(columns) - names
    assert not missing, f"selected but absent from the dataclass: {sorted(missing)}"


@pytest.mark.parametrize("columns,excluded", [
    (SSAP_COLUMNS, SSAP_EXCLUDED), (RCL_COLUMNS, RCL_EXCLUDED)])
def test_selected_and_excluded_do_not_overlap(columns, excluded):
    assert not set(columns) & set(excluded)


@pytest.mark.parametrize("excluded", [SSAP_EXCLUDED, RCL_EXCLUDED])
def test_every_exclusion_carries_a_reason(excluded):
    """Excluding a column is a decision; it has to be reversible by the next
    reader without re-deriving why."""
    for name, reason in excluded.items():
        assert reason.strip(), f"{name} excluded with no reason"


def test_selection_matches_the_provisioned_schema():
    """Guards against a source-schema change silently dropping a column: every
    selected or explicitly-excluded name must exist in the GeoPackage, and
    every GeoPackage column must be accounted for one way or the other."""
    pyogrio = pytest.importorskip("pyogrio")
    import os

    if not os.path.exists("data/data.gpkg"):
        pytest.skip("no provisioned GeoPackage available")

    for layer, columns, excluded in (
        ("SiteStructureAddressPoint", SSAP_COLUMNS, SSAP_EXCLUDED),
        ("RoadCenterLine", RCL_COLUMNS, RCL_EXCLUDED),
    ):
        source = set(pyogrio.read_info("data/data.gpkg", layer=layer)["fields"])
        accounted = set(columns) | set(excluded)
        assert not (set(columns) - source), (
            f"{layer}: selected columns absent from source: "
            f"{sorted(set(columns) - source)}"
        )
        assert not (source - accounted), (
            f"{layer}: source columns neither selected nor explicitly excluded: "
            f"{sorted(source - accounted)}"
        )
