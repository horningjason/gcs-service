"""STA-006.3 GIS row -> record model, and the cache (de)serialisation for it.

This is the layer src/gis/provisioning.py was deliberately written without: it
owns which columns exist, what they are called, and which of them the
conversion algorithm actually reads.

WHERE THESE TYPES LIVE

SSAPRecord and RCLRecord are GIS records — what the SI provisioned — and live
here beside the row conversion that produces them. src/engine/models.py holds
the query-side types (the parsed request CivicAddress, Candidate, and the
quality fields), which are a different thing: one describes what is in the
data, the other what was asked and what came back. The two share the civic
element names deliberately, so §11.1's "read the civic address directly off the
matched record's fields" is a field-for-field copy rather than a translation.

FIELD SELECTION

Every column below is listed explicitly. Nothing is picked up implicitly, so
adding a field to the model is a visible decision rather than a side effect of
the source schema changing.

Selection follows the instruction to include when unsure: a column the
algorithm turns out to need is a correctness bug, whereas a column it does not
need costs bytes. Everything excluded is listed at the bottom of each column
block with the reason, so the next reader can see what was considered and
reverse it cheaply.

CACHE SIZE

Two changes shrink the JSON cache from the 128 MB the plain row-dict approach
produced against data/data.gpkg:

  1. Explicit column selection (SSAP 59 -> 48, RCL 55 -> 46).
  2. Null omission on serialise. Measured against the provisioned data, the
     attribute payload dominates (SSAP ~1146 bytes/row against a 49-char
     geometry WKT), and much of it is null: 15 SSAP columns and 5 RCL columns
     are null in every sampled row. A key absent from the cached dict means
     None; nothing is lost.

Geometry is carried as WKT, INCLUDING Z where the source provides it. Note in
particular that RCL Z is preserved here even though §7.3 declines to propagate
it to a rung-2 forward result: that is a position-derivation decision, and
§10.5's reverse-side vertical band ordering reads this same geometry. Stripping
Z at this layer to serve a forward-side rule would silently push every RCL
candidate into the lower vertical band on the reverse side.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, fields
from typing import Any, Optional, TypeVar

# ---------------------------------------------------------------------------
# Column selection
# ---------------------------------------------------------------------------

#: SiteStructureAddressPoint. Rung 1 of the §3.3 precision ladder, and the only
#: layer STA-006.3 §4.2.1 declares 3D-capable.
SSAP_COLUMNS: tuple[str, ...] = (
    # Identity and provenance
    "NGUID",       # §10.4 deterministic tie-break identifier; §16 / Appendix C (e).
    "DiscrpAgID",  # Agency to file a discrepancy report against (§A.6) — needed
                   # for the NGUID-null path, which reports rather than substitutes.
    # Temporal filtering (§3.4). Null in every sampled row of the provisioned
    # data, so "records without them treated as always active" is the norm here,
    # not the exception.
    "Effective",
    "Expire",
    # CLDXF-US civic elements — read by §6.5 forward scoring and emitted by
    # §11.1 reverse civic derivation. The full hierarchy is kept: §6.2 excludes
    # no record from scoring on any civic element (decision 61), so every
    # element here is one the scorer may be asked to compare.
    "Country", "A1", "A2", "A3", "A4", "A5", "AddCode",
    "AddNum_Pre", "Add_Number", "AddNum_Suf", "AddNum_Cmp",
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
    "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod",
    "LSt_PreDir", "LSt_Name", "LSt_Typ", "LSt_PosDir",
    "MSAGComm", "Post_Comm", "Post_Code", "PostCodeEx",
    # Sub-address / interior hierarchy. Also the vocabulary §7.5 will need when
    # a 3D space layer exists — a query naming the unit is what makes a single
    # space resolvable at full precision rather than merged.
    "Site", "SubSite", "Structure", "Floor", "FloorIndex", "Wing",
    "Unit", "UnitPreTyp", "UnitValue", "Section", "Row_", "Room", "Seat",
    "Addtl_Loc", "Place_Type",
    # Placement Method ID — integer FK to STA-006.3 Table 15-8 (§6.1 registry).
    # Passed through on the enhanced interface (§3.2), sharpens the distance
    # bias disclosure (§10.5), and damps the spatial-fit score where the value
    # is Geocoding (§10.6).
    # The provisioned data carries the registry TOKEN directly as text
    # ('Parcel', 'Structure', 'Unknown', 'Geocoding', 'Property Access'), not
    # the integer FK the standard describes, so no join is performed — and
    # 'Property Access' is spelled with a space where the §6.1 registry token
    # is PropertyAccess, so registry-token comparisons normalise first.
    # Spec §3.2, decision 103 (resolving Appendix C.4 Q19).
    "Placement",
    # Vertical attributes. Decision 55 does not read any of them for position:
    # the geometry is the sole position source on every axis, and a Z that
    # fails the non-zero test leaves the point 2D rather than falling through
    # to a column. They are provisioned all the same — §16 notes four places a
    # vertical value can live, and this layer preserves what the SI supplied
    # rather than deciding on the engine's behalf which of them matter. In the
    # provisioned data Altitude and Height are null throughout and Elevation is
    # non-zero on 8.5% of records; decision 55 accepts leaving that unread.
    "Elevation", "Altitude", "Height",
    # Horizontal attributes duplicating the geometry's X/Y. Not read for
    # position either, and not a fallback where a record carries no geometry —
    # under decision 55 such a record has no position at all and is flagged.
    # Preserved on the same basis as the vertical columns. Decision 55
    # supersedes decision 52; see spec Appendix C.4 Q13.
    "Longitude", "Latitude",
)

#: Excluded from SSAP_COLUMNS, with reasons. Reverse any of these by moving the
#: name into SSAP_COLUMNS above; nothing else needs to change.
SSAP_EXCLUDED: dict[str, str] = {
    "DateUpdate": "Provenance audit only. No algorithm section reads it; §3.4 "
                  "filters on Effective/Expire, not last-update.",
    "DistMarker": "Distance marker reference. §3.3 provisions no marker layer to "
                  "resolve it against.",
    "Dir_Travel": "Direction of travel. Side-of-street for SSAP is not computed "
                  "(the point is already placed); §7.2's L/R comes from RCL "
                  "geometry direction and Parity_L/R. Null throughout here.",
    "ESN":        "Emergency Service Number — a routing attribute. The GCS does "
                  "not route (§3.1) and ESN is not a CLDXF civic element.",
    "LCountyID":  "Legacy county identifier. A2 carries county in the CLDXF "
                  "hierarchy §11.3 sources administrative elements from.",
    "LocMarker":  "Location marker reference; same reasoning as DistMarker.",
    "AddDataURI": "Pointer to additional data. Following it would be an outbound "
                  "dependency §4.5 does not describe.",
}

#: RoadCenterLine. Rungs 2 and 3 of the §3.3 ladder.
RCL_COLUMNS: tuple[str, ...] = (
    # Identity and provenance
    "NGUID", "DiscrpAgID",
    # Temporal filtering (§3.4)
    "Effective", "Expire",
    # Address ranges — the input to §7.2 interpolation and §11.2 inversion.
    # NOTE: the column names are Valid_L / Valid_R. §7.2's drafting note asks
    # to confirm "Validation_L/R" against the provisioned schema; that name
    # does not exist. FromAddr_L/R, ToAddr_L/R and Parity_L/R stand as written.
    "AdNumPre_L", "AdNumPre_R",
    "FromAddr_L", "ToAddr_L", "FromAddr_R", "ToAddr_R",
    "Parity_L", "Parity_R",
    "Valid_L", "Valid_R",
    # Street name elements — shared across both sides of the segment.
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
    "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod",
    "LSt_PreDir", "LSt_Name", "LSt_Typ", "LSt_PosDir",
    # Side-specific administrative attribution. §11.3: the side the origin
    # projected onto selects the attribute set, for administrative elements as
    # well as street names.
    "Country_L", "Country_R", "A1_L", "A1_R", "A2_L", "A2_R",
    "A3_L", "A3_R", "A4_L", "A4_R", "A5_L", "A5_R",
    "AddCode_L", "AddCode_R", "MSAGComm_L", "MSAGComm_R",
    "PostCode_L", "PostCode_R", "PostComm_L", "PostComm_R",
)

#: Excluded from RCL_COLUMNS, with reasons.
RCL_EXCLUDED: dict[str, str] = {
    "DateUpdate": "Provenance audit only; see SSAP_EXCLUDED.",
    "Dir_Travel": "Direction of travel. §7.2 derives the side from the segment's "
                  "own digitised direction together with Parity_L/R, not from "
                  "this field. Null throughout here.",
    "ESN_L":      "Routing attribute; the GCS does not route (§3.1).",
    "ESN_R":      "Routing attribute; the GCS does not route (§3.1).",
    "LCntyID_L":  "Legacy county identifier; A2_L carries county.",
    "LCntyID_R":  "Legacy county identifier; A2_R carries county.",
    "RoadClass":  "Road classification. §10.3's ordering is containment, tier, "
                  "distance — no term consults road class, and §10.5 explicitly "
                  "declines to adjust distance by any road attribute.",
    "OneWay":     "Routing attribute.",
    "SpeedLimit": "Routing attribute.",
}


# ---------------------------------------------------------------------------
# Record models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SSAPRecord:
    """One SiteStructureAddressPoint feature. Field names mirror the STA-006.3
    column names exactly, so there is no mapping table to keep in step."""

    fid: int
    geometry_wkt: Optional[str] = None

    NGUID: Optional[str] = None
    DiscrpAgID: Optional[str] = None
    Effective: Optional[str] = None
    Expire: Optional[str] = None

    Country: Optional[str] = None
    A1: Optional[str] = None
    A2: Optional[str] = None
    A3: Optional[str] = None
    A4: Optional[str] = None
    A5: Optional[str] = None
    AddCode: Optional[str] = None

    AddNum_Pre: Optional[str] = None
    Add_Number: Optional[int] = None
    AddNum_Suf: Optional[str] = None
    AddNum_Cmp: Optional[str] = None

    St_PreMod: Optional[str] = None
    St_PreDir: Optional[str] = None
    St_PreTyp: Optional[str] = None
    St_PreSep: Optional[str] = None
    St_Name: Optional[str] = None
    St_PosTyp: Optional[str] = None
    St_PosDir: Optional[str] = None
    St_PosMod: Optional[str] = None

    LSt_PreDir: Optional[str] = None
    LSt_Name: Optional[str] = None
    LSt_Typ: Optional[str] = None
    LSt_PosDir: Optional[str] = None

    MSAGComm: Optional[str] = None
    Post_Comm: Optional[str] = None
    Post_Code: Optional[str] = None
    PostCodeEx: Optional[str] = None

    Site: Optional[str] = None
    SubSite: Optional[str] = None
    Structure: Optional[str] = None
    Floor: Optional[str] = None
    FloorIndex: Optional[int] = None
    Wing: Optional[str] = None
    Unit: Optional[str] = None
    UnitPreTyp: Optional[str] = None
    UnitValue: Optional[str] = None
    Section: Optional[str] = None
    Row_: Optional[str] = None
    Room: Optional[str] = None
    Seat: Optional[str] = None
    Addtl_Loc: Optional[str] = None
    Place_Type: Optional[str] = None

    #: STA-006.3 §6.1 Placement Method. Typed str, not int: the provisioned
    #: data carries the registry token as text, not the standard's integer FK
    #: (spec §3.2, decision 103 — Appendix C.4 Q19).
    Placement: Optional[str] = None

    Elevation: Optional[float] = None
    Altitude: Optional[float] = None
    Height: Optional[float] = None
    Longitude: Optional[float] = None
    Latitude: Optional[float] = None


@dataclass(slots=True)
class RCLRecord:
    """One RoadCenterLine feature."""

    fid: int
    geometry_wkt: Optional[str] = None

    NGUID: Optional[str] = None
    DiscrpAgID: Optional[str] = None
    Effective: Optional[str] = None
    Expire: Optional[str] = None

    AdNumPre_L: Optional[str] = None
    AdNumPre_R: Optional[str] = None
    FromAddr_L: Optional[int] = None
    ToAddr_L: Optional[int] = None
    FromAddr_R: Optional[int] = None
    ToAddr_R: Optional[int] = None
    Parity_L: Optional[str] = None
    Parity_R: Optional[str] = None
    Valid_L: Optional[str] = None
    Valid_R: Optional[str] = None

    St_PreMod: Optional[str] = None
    St_PreDir: Optional[str] = None
    St_PreTyp: Optional[str] = None
    St_PreSep: Optional[str] = None
    St_Name: Optional[str] = None
    St_PosTyp: Optional[str] = None
    St_PosDir: Optional[str] = None
    St_PosMod: Optional[str] = None

    LSt_PreDir: Optional[str] = None
    LSt_Name: Optional[str] = None
    LSt_Typ: Optional[str] = None
    LSt_PosDir: Optional[str] = None

    Country_L: Optional[str] = None
    Country_R: Optional[str] = None
    A1_L: Optional[str] = None
    A1_R: Optional[str] = None
    A2_L: Optional[str] = None
    A2_R: Optional[str] = None
    A3_L: Optional[str] = None
    A3_R: Optional[str] = None
    A4_L: Optional[str] = None
    A4_R: Optional[str] = None
    A5_L: Optional[str] = None
    A5_R: Optional[str] = None
    AddCode_L: Optional[str] = None
    AddCode_R: Optional[str] = None
    MSAGComm_L: Optional[str] = None
    MSAGComm_R: Optional[str] = None
    PostCode_L: Optional[str] = None
    PostCode_R: Optional[str] = None
    PostComm_L: Optional[str] = None
    PostComm_R: Optional[str] = None


# ---------------------------------------------------------------------------
# Row conversion
# ---------------------------------------------------------------------------

def _plain(value: Any) -> Any:
    """Coerce a source cell to a plain, JSON-serialisable Python value.

    Returns None for null in all its forms — Python None, numpy NaN (which is
    not equal to itself), and pandas NaT.

    TEXT NORMALISATION — surrounding whitespace is stripped, and a value that
    is empty or whitespace-only becomes None.

    This is not cosmetic. The provisioned data is a fixed-width export: in a
    5,000-row sample of SiteStructureAddressPoint, 32 of 49 text columns are
    whitespace-only in more than 90% of rows, and padding is present on
    non-blank values too — A3 is padded in 1,549 of 5,000 rows, St_PosDir in
    1,049, St_PosTyp in 141. Carried through verbatim, a query for "Bismarck"
    would not match a stored "Bismarck " under any exact or
    case-insensitive-exact comparison, and §11.4's rule that an element with no
    source is omitted rather than emitted empty would be unimplementable — the
    GCS would emit <ca:A4> </ca:A4> and assert something about a value it does
    not have.

    Stripping is safe because no CLDXF-US element's meaning depends on leading
    or trailing whitespace. Interior whitespace is preserved untouched
    ("Grand Forks" stays as it is).

    Written into spec §3.2 (decision 103, adopting Appendix C.4 R4).
    """
    if value is None:
        return None
    if value != value:  # NaN / NaT
        return None
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def _from_row(cls, row, fid: int, columns: tuple[str, ...], geom_col: str):
    kwargs: dict[str, Any] = {"fid": int(fid)}
    geom = row.get(geom_col)
    kwargs["geometry_wkt"] = None if geom is None else geom.wkt
    for column in columns:
        if column in row:
            kwargs[column] = _plain(row[column])
    return cls(**kwargs)


def row_to_ssap(row, fid: int, geom_col: str = "geometry") -> SSAPRecord:
    return _from_row(SSAPRecord, row, fid, SSAP_COLUMNS, geom_col)


def row_to_rcl(row, fid: int, geom_col: str = "geometry") -> RCLRecord:
    return _from_row(RCLRecord, row, fid, RCL_COLUMNS, geom_col)


# ---------------------------------------------------------------------------
# Cache (de)serialisation
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


def record_to_dict(record) -> dict[str, Any]:
    """Serialise a record for the JSON cache, OMITTING null fields.

    A key absent from the dict means None. This is the single biggest lever on
    cache size — most CLDXF sub-address and legacy-name columns are null for
    most records, and 15 SSAP / 5 RCL columns are null in every sampled row of
    the provisioned data.
    """
    out: dict[str, Any] = {}
    for f in fields(record):
        value = getattr(record, f.name)
        if value is not None:
            out[f.name] = value
    return out


def dict_to_record(cls: type[_T], data: dict[str, Any]) -> _T:
    """Rebuild a record from a cached dict. Absent keys default to None."""
    return cls(**data)


def ssap_to_dict(record: SSAPRecord) -> dict[str, Any]:
    return record_to_dict(record)


def rcl_to_dict(record: RCLRecord) -> dict[str, Any]:
    return record_to_dict(record)


def dict_to_ssap(data: dict[str, Any]) -> SSAPRecord:
    return dict_to_record(SSAPRecord, data)


def dict_to_rcl(data: dict[str, Any]) -> RCLRecord:
    return dict_to_record(RCLRecord, data)
