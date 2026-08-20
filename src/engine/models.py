"""The shared element, candidate, and quality model (spec §6.5, §7.1, §7.4, §11).

WHAT THIS MODULE IS FOR

src/gis/records.py owns what the SI provisioned — column names, row conversion,
cache serialisation. This module owns the query side and the answer side: the
civic address that was asked about, the engine's view of a matched GIS feature,
the candidate that carries one, and the three quality fields §7.4 settles.

It holds no algorithm. Nothing here scores, searches, interpolates, or ranks.
§6.5 similarity lives in scoring.py, §7.2 interpolation and §10's geodesy in
geometry.py and src/geocode/position.py, nearest-feature search in
src/reverse/search.py, and the GCS_MIN_MATCH_SCORE admission gate in
src/geocode/candidates.py. What is here is the vocabulary those modules agree
on, plus the two resolutions that have to happen the moment a GIS row becomes
a candidate: which of the four places a Z can live actually supplies one, and
which of the two places a horizontal position can live wins.

THE ELEMENT VOCABULARY IS STA-006.3's

CivicAddress carries the STA-006.3 column names, not the PIDF-LO ca: element
names, and carries them identically to SSAPRecord's civic block. That follows
from §11.1: the reverse direction reads the civic address "directly off the
matched SSAP record's fields", which is a field-for-field copy under this
choice and a mapping table under any other. The forward direction gets the same
benefit at §6.5, where per-field similarity compares like-named fields.

The PIDF-LO to element-model mapping therefore lives in the wire layer, not
here — §3.10's table, transcribed from STA-004.2 and implemented in
src/api/wire/civic_xml.py (spec Appendix C.4 Q21, resolved by decisions
62-63).

Packaging is not a question this module answers. Decision 58 specifies the GCS
standalone, so there is no sibling document to align a shared model with and no
extraction owed to one: the element vocabulary above is the GCS's own, derived
from STA-006.3 directly. A plain module in this repo is the whole of it.

DECISIONS 53 AND 55 LIVE IN THE CODE BELOW, NOT IN A COMMENT

Two rules are implemented here rather than cited:

  * Position on every axis comes solely from the matched feature's shape
    geometry. X and Y are read from the geometry and never from the
    Longitude/Latitude columns. Z is read from the geometry where it carries a
    non-zero value and from nowhere else — a geometry Z of exactly 0 is an
    empty slot rather than an asserted height, so the point is 2D at
    EPSG:4326. Altitude and Elevation are not consulted for the returned
    coordinate at all. A record whose geometry is absent or unusable yields no
    position, is flagged, and cannot be returned as a located match; the
    attribute columns are not read to repair it.

    The point of the rule is that a coordinate comes from one artifact. A
    position built from a geometry's X and Y and a column's Z is a location no
    single source asserts, and no consumer can see the seam on the wire. The
    accepted consequence is that until an SI populates geometry Z the service
    is two-dimensional everywhere — an honest report of what the data holds.

    Decision 55 supersedes 51 and 52. What carried forward from 51 is its
    admission test — non-null AND non-zero — which was never about precedence
    but about whether a populated slot asserts anything. The provisioned SSAP
    layer is declared Point Z with a uniformly zero ordinate, so presence alone
    carries no information about height.

  * A RoadCenterLine segment of more than one part is a data-quality condition,
    flagged and carried, never concatenated or traversed in a guessed order.

Neither flag files a discrepancy report here. Decision 99 settles what the GCS
files about — structural provisioning defects, which is exactly this flag
vocabulary plus GIS load failure — but the filing side of src/discrepancy/ is
deferred work; the flags recorded here are the input it will consume.
"""

from __future__ import annotations

import enum
import functools
from dataclasses import dataclass, field, fields
from typing import Any, Mapping, Optional

from shapely import wkt as _wkt
from shapely.errors import ShapelyError

from src.gis.records import RCLRecord, SSAPRecord

# ---------------------------------------------------------------------------
# Coordinate reference systems (§3.7)
# ---------------------------------------------------------------------------

#: A position with no admissible Z. Two-dimensional.
CRS_2D = "urn:ogc:def:crs:EPSG::4326"

#: A position carrying a height above the WGS84 ellipsoid.
CRS_3D = "urn:ogc:def:crs:EPSG::4979"


# ---------------------------------------------------------------------------
# Vertical resolution
# ---------------------------------------------------------------------------

def z_is_admissible(value: Optional[float]) -> bool:
    """A geometry's Z counts only if it is present AND asserts something.

    Null is absence. Exactly 0.0 is an unpopulated placeholder on the same
    basis: the provisioned SSAP layer is declared Point Z and populates every
    ordinate with 0.0, so presence alone carries no information about height.

    The cost of the test is stated plainly rather than hidden: 0 m HAE is a
    legitimate height in a handful of US locations, and this rule declines to
    report it. The trade is one-sided — the alternative reports a synthetic 0
    for every address in a jurisdiction, which is wrong far more often and
    unsignallable on the i3 interface either way.

    Failing the test is not an error and raises nothing. It is the normal
    result across the currently provisioned data, and it means the position is
    two-dimensional. Under decision 55 there is nowhere else to look: the
    Altitude and Elevation columns are not consulted for the returned
    coordinate, so this test is the whole of vertical resolution.

    NaN is rejected too. Row conversion already normalises it to None, but a
    geometry ordinate does not pass through that path.
    """
    if value is None:
        return False
    if value != value:  # NaN
        return False
    return value != 0.0


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Position:
    """A resolved geodetic position, read off one geometry. Degrees for X/Y,
    metres HAE for Z.

    Dimensionality follows the data (§3.7.1): a position either carries an
    admissible height or it does not, and the CRS is a consequence of that
    rather than a separate setting.

    There is no field recording where the height came from. Under decision 55
    there is only one place it can come from, so `is_3d` below — geometry Z
    admitted, or no Z at all — is the whole of the disclosure.
    """

    longitude: float
    latitude: float
    altitude: Optional[float] = None

    @property
    def is_3d(self) -> bool:
        return self.altitude is not None

    @property
    def crs(self) -> str:
        return CRS_3D if self.is_3d else CRS_2D


# ---------------------------------------------------------------------------
# Civic elements
# ---------------------------------------------------------------------------

#: The civic element vocabulary, in STA-006.3 spelling. This is exactly
#: SSAP_COLUMNS minus the names below, and a test holds the two in step.
CIVIC_ELEMENTS: tuple[str, ...] = (
    "Country", "A1", "A2", "A3", "A4", "A5", "AddCode",
    "AddNum_Pre", "Add_Number", "AddNum_Suf", "AddNum_Cmp",
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
    "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod",
    "LSt_PreDir", "LSt_Name", "LSt_Typ", "LSt_PosDir",
    "MSAGComm", "Post_Comm", "Post_Code", "PostCodeEx",
    "Site", "SubSite", "Structure", "Floor", "FloorIndex", "Wing",
    "Unit", "UnitPreTyp", "UnitValue", "Section", "Row_", "Room", "Seat",
    "Addtl_Loc", "Place_Type",
)

#: SSAP columns that are deliberately NOT civic elements, with the reason. A
#: caller cannot ask about these and the reverse direction does not emit them
#: as address elements, so they belong to the record and not to the address.
NON_CIVIC_SSAP_COLUMNS: dict[str, str] = {
    "NGUID":      "Feature identifier. Identifies the record, not the place.",
    "DiscrpAgID": "Provenance — who to file against (§A.6).",
    "Effective":  "Temporal filtering (§3.4), not an address element.",
    "Expire":     "Temporal filtering (§3.4), not an address element.",
    "Placement":  "STA-006.3 §6.1 registry token describing how the point was "
                  "placed. A property of the geometry's derivation, surfaced "
                  "per candidate by §10.5.",
    "Elevation":  "Provisioned vertical attribute. Decision 55 does not read it "
                  "for the returned coordinate — Z comes from the geometry or "
                  "not at all. May be revisited; carried by the record layer "
                  "meanwhile.",
    "Altitude":   "Provisioned vertical attribute, not read for position under "
                  "decision 55. Same standing as Elevation.",
    "Height":     "AGL — the difference between Altitude and Elevation. Never "
                  "read for position; carried by the record layer only.",
    "Longitude":  "Provisioned horizontal attribute duplicating the geometry's "
                  "X. Decision 55 does not read it for position, including "
                  "where the geometry is missing.",
    "Latitude":   "Provisioned horizontal attribute duplicating the geometry's "
                  "Y. Same standing as Longitude.",
}


@dataclass(frozen=True, slots=True)
class CivicAddress:
    """A civic address, whether asked about (forward) or derived (reverse).

    One type serves both directions on purpose. §14.1's round-trip requirement
    is a statement about these two being comparable, and it is easier to hold
    to when they are the same type rather than two that drifted apart.

    Every element is optional. §11.4 settles that a sparse record is returned
    rather than rejected, and §5 settles that no element is a precondition on
    the forward side — there is no completeness contract to enforce here.
    """

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

    def populated(self) -> dict[str, Any]:
        """The elements that have a value.

        §11.4's omit-rather-than-emit-empty rule serialises from this, and
        §6.5's scoring reads it to know what the caller actually asserted as
        opposed to what the schema permits.
        """
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) is not None
        }

    @property
    def is_empty(self) -> bool:
        return not self.populated()

    @classmethod
    def from_record(cls, record: SSAPRecord) -> "CivicAddress":
        """§11.1 — read straight off the matched record. No derivation."""
        return cls(**{
            name: getattr(record, name)
            for name in CIVIC_ELEMENTS
            if getattr(record, name, None) is not None
        })


#: RCL columns whose left/right pair maps onto a civic element. §11.3: the side
#: the origin projected onto selects the attribute set, administrative elements
#: as well as street names.
_RCL_SIDED_ELEMENTS: dict[str, str] = {
    "Country": "Country_{s}",
    "A1": "A1_{s}",
    "A2": "A2_{s}",
    "A3": "A3_{s}",
    "A4": "A4_{s}",
    "A5": "A5_{s}",
    "AddCode": "AddCode_{s}",
    "MSAGComm": "MSAGComm_{s}",
    "Post_Code": "PostCode_{s}",
    "Post_Comm": "PostComm_{s}",
    "AddNum_Pre": "AdNumPre_{s}",
}

#: RCL columns carrying one value for the whole segment.
_RCL_SHARED_ELEMENTS: tuple[str, ...] = (
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
    "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod",
    "LSt_PreDir", "LSt_Name", "LSt_Typ", "LSt_PosDir",
)


class Side(enum.Enum):
    """Which side of a centerline segment. The suffix is the column suffix."""

    LEFT = "L"
    RIGHT = "R"


# ---------------------------------------------------------------------------
# Precision tiers (§7.4, decision 31)
# ---------------------------------------------------------------------------

@functools.total_ordering
class LocationType(enum.Enum):
    """How precisely the matched feature locates anything.

    Keyed to the class of geometry that was matched, never to a ladder rung.
    The ladder numbers rungs 1-3 for the forward direction only; the tier has
    to mean the same thing on the reverse side, and has to admit a footprint or
    a volume without renumbering anything that already exists. Ordering comes
    from _PRECISION_ORDER below, so inserting a tier is an edit to one tuple.
    """

    SPACE_3D = "SPACE_3D"
    FOOTPRINT_2D = "FOOTPRINT_2D"
    ADDRESS_POINT = "ADDRESS_POINT"
    INTERPOLATED_POINT = "INTERPOLATED_POINT"
    STREET_SEGMENT = "STREET_SEGMENT"

    @property
    def precision(self) -> int:
        """Rank within the tier ordering. Higher is more precise."""
        return _PRECISION_ORDER.index(self)

    @property
    def ceiling(self) -> float:
        """The tier's confidence ceiling.

        Fixed by the specification rather than configured, so that two GCS
        implementations cannot disagree about what a confidence value means.
        """
        return TIER_CEILINGS[self]

    def __lt__(self, other: "LocationType") -> bool:
        if not isinstance(other, LocationType):
            return NotImplemented
        return self.precision < other.precision

    @classmethod
    def for_geometry(
        cls,
        geometry_type: str,
        *,
        position_derived: bool = False,
    ) -> "LocationType":
        """Tier a match from the class of geometry that produced it.

        `position_derived` distinguishes the two tiers a line can produce: a
        position interpolated along the segment (§7.2) is INTERPOLATED_POINT,
        while the segment returned whole because there was no house number to
        interpolate is STREET_SEGMENT.

        SPACE_3D is deliberately unmapped. §7.4 as corrected in Session 4 finds
        no volumetric feature class in STA-006.3, so nothing can key to it yet;
        naming a geometry class here would assert which class that will be.
        The tier itself exists so the ordering and the ceiling arithmetic are
        complete when a layer arrives.
        """
        name = (geometry_type or "").strip().lower()
        if name in ("point", "multipoint"):
            return cls.ADDRESS_POINT
        if name in ("linestring", "multilinestring", "linearring"):
            return cls.INTERPOLATED_POINT if position_derived else cls.STREET_SEGMENT
        if name in ("polygon", "multipolygon"):
            return cls.FOOTPRINT_2D
        raise ValueError(f"no precision tier is defined for geometry {geometry_type!r}")


#: Least to most precise. Insert here; nothing else needs to change.
_PRECISION_ORDER: tuple[LocationType, ...] = (
    LocationType.STREET_SEGMENT,
    LocationType.INTERPOLATED_POINT,
    LocationType.ADDRESS_POINT,
    LocationType.FOOTPRINT_2D,
    LocationType.SPACE_3D,
)

#: §7.4. Not configurable — see LocationType.ceiling.
TIER_CEILINGS: dict[LocationType, float] = {
    LocationType.SPACE_3D: 100.0,
    LocationType.FOOTPRINT_2D: 90.0,
    LocationType.ADDRESS_POINT: 80.0,
    LocationType.INTERPOLATED_POINT: 75.0,
    LocationType.STREET_SEGMENT: 50.0,
}


# ---------------------------------------------------------------------------
# The three quality fields (§7.4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MatchQuality:
    """matchScore, locationType, and the confidence derived from them.

    The two primary fields are orthogonal and both travel, so a consumer can
    re-rank on either: matchScore answers "did we find the right record" and
    nothing else, locationType answers "how precisely does that record locate
    anything" and nothing else.

    confidence is a property rather than a field. It is a convenience dial
    computed from the two primaries and never stored, so it cannot drift out of
    agreement with them.
    """

    match_score: float
    location_type: LocationType

    #: §6.5's per-field breakdown, following HERE's fieldScore precedent, so a
    #: consumer can see which field dragged a candidate down. Populated by
    #: scoring.py; empty on the reverse side, where there is no query address
    #: to decompose (§10.6).
    field_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.match_score <= 100.0:
            raise ValueError(f"match_score out of range: {self.match_score}")

    @property
    def confidence(self) -> float:
        """matchScore scaled to the tier's ceiling.

        Unrounded. RFC 7459 serialisation constraints are the wire layer's to
        apply — including the one at the top of the scale, where the schema's
        exclusive maximum cannot carry a value of exactly 100 and the wire
        emits "unknown" instead (spec decision 97, Appendix C.4 Q5).
        """
        return self.match_score / 100.0 * self.location_type.ceiling


# ---------------------------------------------------------------------------
# The engine's view of a matched GIS feature
# ---------------------------------------------------------------------------

class DataQualityFlag(enum.Enum):
    """Conditions in the provisioned data that the engine must not paper over.

    Recorded on the record, consumed downstream. Deliberately not filed as
    discrepancy reports here: decision 99 makes this flag set the filing
    vocabulary (structural defects against the SI, never attribution content),
    and the filing itself happens at the call sites that consume a GisRecord
    (src/geocode/candidates.py, src/reverse/search.py) via
    src/discrepancy/discrepancy_report.py — the engine only records what it
    observed.
    """

    #: Decision 55 — the record has no usable shape: geometry absent, not
    #: parseable, empty, or of a class the layer cannot locate anything with.
    #: All four are one condition because they have one consequence, and the
    #: record still carries its own geometry_wkt for anyone diagnosing which.
    #: A record carrying this flag has no position and is not a located match;
    #: the Longitude/Latitude columns are not read to rescue it.
    NO_GEOMETRY = "no_geometry"

    #: R3 — the record cannot participate in §10.4's deterministic tie-break.
    #: Not substituted with the GeoPackage FID, which is not stable across
    #: reloads and would silently defeat the cross-implementation guarantee.
    NGUID_MISSING = "nguid_missing"

    #: A centerline segment of more than one part. §7.2's walk, §7.3's
    #: left/right sense, and §11.2's inversion all assume one continuous path.
    MULTIPART_SEGMENT = "multipart_segment"


def _parse_geometry(wkt_text: Optional[str]) -> Any:
    """The record's shape, or None where it has no usable one."""
    if wkt_text is None:
        return None
    try:
        geometry = _wkt.loads(wkt_text)
    except (ShapelyError, ValueError, TypeError):
        return None
    if geometry is None or geometry.is_empty:
        return None
    return geometry


@dataclass(frozen=True, slots=True)
class GisRecord:
    """A provisioned feature as the engine sees it: geometry parsed, data
    quality assessed, identity exposed.

    The record layer's types stay reachable through `source`. Nothing is copied
    out of them that has not been transformed, so there is one answer to "what
    did the SI actually provide".
    """

    source: SSAPRecord | RCLRecord
    geometry: Any = None
    flags: frozenset[DataQualityFlag] = field(default_factory=frozenset)

    @property
    def fid(self) -> int:
        return self.source.fid

    @property
    def nguid(self) -> Optional[str]:
        return self.source.NGUID

    @property
    def is_tie_breakable(self) -> bool:
        """R3 — whether §10.4 can order this record deterministically."""
        return self.source.NGUID is not None

    @property
    def geometry_type(self) -> Optional[str]:
        return None if self.geometry is None else self.geometry.geom_type

    @property
    def is_located(self) -> bool:
        """Whether this record can be returned as a located match.

        Decision 55: a record with no usable shape has no position, and there
        is no second source to assemble one from. Candidate identification
        drops these rather than answering with a location the SI never drew.
        """
        return not self.has_flag(DataQualityFlag.NO_GEOMETRY)

    def has_flag(self, flag: DataQualityFlag) -> bool:
        return flag in self.flags


@dataclass(frozen=True, slots=True)
class SsapGisRecord(GisRecord):
    """A SiteStructureAddressPoint. Rung 1, and the only 3D-capable layer."""

    position: Optional[Position] = None

    @property
    def placement(self) -> Optional[str]:
        """STA-006.3 §6.1 Placement Method, as the SI spelled it.

        A text token rather than an integer FK, and not normalised here:
        decision 103 (resolving spec Appendix C.4 Q19) passes the token
        through uncorrected and puts the normalisation at comparison time —
        every registry-token comparison, §10.6's Geocoding damping included,
        runs after trim-and-casefold.
        """
        return self.source.Placement

    def civic(self) -> CivicAddress:
        return CivicAddress.from_record(self.source)

    @classmethod
    def from_record(cls, record: SSAPRecord) -> "SsapGisRecord":
        geometry = _parse_geometry(record.geometry_wkt)
        position = _ssap_position(geometry)

        flags: set[DataQualityFlag] = set()
        if position is None:
            flags.add(DataQualityFlag.NO_GEOMETRY)
        if record.NGUID is None:
            flags.add(DataQualityFlag.NGUID_MISSING)

        return cls(
            source=record,
            geometry=geometry,
            flags=frozenset(flags),
            position=position,
        )


def _ssap_position(geometry: Any) -> Optional[Position]:
    """Read the position off the geometry, or return None (decision 55).

    Every axis comes from this one artifact. X and Y are the geometry's; Z is
    the geometry's where it survives the admission test, and absent otherwise.
    Nothing else is consulted — not Altitude, not Elevation, and not the
    Longitude/Latitude columns, including when there is no geometry at all.

    A non-Point geometry on the address-point layer is unusable rather than
    interesting: SSAP is provisioned Point Z, and anything else there is a
    shape this function has no rule for reading a single position from.
    """
    if geometry is None or geometry.geom_type != "Point":
        return None

    altitude = None
    if geometry.has_z and z_is_admissible(geometry.z):
        altitude = float(geometry.z)

    return Position(
        longitude=float(geometry.x),
        latitude=float(geometry.y),
        altitude=altitude,
    )


@dataclass(frozen=True, slots=True)
class RclGisRecord(GisRecord):
    """A RoadCenterLine. Rungs 2 and 3.

    No position is resolved here. An RCL locates an address only after §7.2
    interpolates along it, which needs a house number this type has never seen.
    """

    #: How many parts the geometry has. One is the normal case.
    part_count: int = 0

    @property
    def is_multipart(self) -> bool:
        """More than one part — decision 53's data-quality condition.

        A MultiLineString wrapping a single part is not multi-part: the
        provisioned layer declares MultiLineString for every feature, so the
        container says nothing on its own. The part count does.
        """
        return self.part_count > 1

    def civic_for_side(self, side: Side) -> CivicAddress:
        """§11.3 — the side selects the attribute set.

        Administrative elements as well as street names. Add_Number is left
        unset: an RCL asserts a range, and turning a position into a number is
        §11.2's inversion, not a field to copy.
        """
        values: dict[str, Any] = {}
        for element, template in _RCL_SIDED_ELEMENTS.items():
            value = getattr(self.source, template.format(s=side.value), None)
            if value is not None:
                values[element] = value
        for element in _RCL_SHARED_ELEMENTS:
            value = getattr(self.source, element, None)
            if value is not None:
                values[element] = value
        return CivicAddress(**values)

    def civic_shared(self) -> CivicAddress:
        """The segment's unsided attribution — street name and type only.

        For an answer that never chose a side. A rung-3 match returns the whole
        segment precisely because there was no house number to place on it, and
        without a position there is no side; §11.3's rule that the side selects
        the attribute set has no input to run on. Reporting one side's county
        and postal community anyway would assert an attribution this answer did
        not derive, so the sided elements are omitted rather than guessed.

        RAISED AND CLOSED (Session 16) — omitting them even where BOTH SIDES
        AGREE. Where A3_L == A3_R there is no value to guess between, so the
        paragraph above looks stricter than it needs to be, and the question
        was put to the user directly off decision 119's reseeded
        FWD-DROPPED-HNO-ENH-001 output (a segment whose two sides both say
        "Bismarck", reported with no community at all). Closed with NO change,
        on a reason stronger than side-agreement: a rung-3 candidate reaches
        here having supplied no house number, so §7.2's parity has no input
        and scoring resolved side by decision 67/87's best-of-both-sides
        fallback — it kept whichever side scored higher and never COMMITTED to
        one. There is therefore no sided attribution to report regardless of
        whether the two sides agree, and value-agreement is the wrong test:
        it would have this method report an element the answer did not select,
        conditional on a coincidence in the data.

        The user's condition for accepting the omission was that the elements
        still do real work behind the scenes, which was verified rather than
        assumed: on that fixture's query, Community and A2 are live terms in
        the rung-3 breakdown, a wrong A3 drops the best score 100.00 -> 87.49
        and a wrong A2 100.00 -> 92.20, and A3 separates the real 202-candidate
        set cleanly (A3="Bismarck" 94.28-100.00, unattributed 74.70-94.54,
        A3="Mandan" 71.08-79.13). The elements order the answer; they are just
        not reported as attribution the answer never derived.
        """
        return CivicAddress(**{
            element: getattr(self.source, element)
            for element in _RCL_SHARED_ELEMENTS
            if getattr(self.source, element, None) is not None
        })

    @classmethod
    def from_record(cls, record: RCLRecord) -> "RclGisRecord":
        geometry = _parse_geometry(record.geometry_wkt)

        flags: set[DataQualityFlag] = set()
        if geometry is None:
            flags.add(DataQualityFlag.NO_GEOMETRY)
        if record.NGUID is None:
            flags.add(DataQualityFlag.NGUID_MISSING)

        part_count = _part_count(geometry)
        if part_count > 1:
            flags.add(DataQualityFlag.MULTIPART_SEGMENT)

        return cls(
            source=record,
            geometry=geometry,
            flags=frozenset(flags),
            part_count=part_count,
        )


def _part_count(geometry: Any) -> int:
    if geometry is None:
        return 0
    return len(geometry.geoms) if hasattr(geometry, "geoms") else 1


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Candidate:
    """One answer under consideration, in either direction.

    Both directions produce the same shape because §7.4's quality model is the
    same on both, and §14.1 compares them. The fields each direction leaves
    unset differ: forward fills position/answer_geometry and leaves distance_m
    None, reverse fills civic and distance_m.

    No ranking or admission logic here. GCS_MIN_MATCH_SCORE gates in
    quality.py, upstream of both response assemblies, so rank 1 is identical
    across the two interfaces.
    """

    record: GisRecord
    quality: MatchQuality

    #: The derived position, where the answer is a position. None at
    #: STREET_SEGMENT, where §7.4 returns the line itself.
    position: Optional[Position] = None

    #: §7.4's geometry-as-answer: the actual geometry returned, not a
    #: synthesised uncertainty shape. A Point at the point tiers, the segment's
    #: own line at STREET_SEGMENT.
    answer_geometry: Any = None

    #: Reverse direction (§11) — the civic address derived from the match.
    civic: Optional[CivicAddress] = None

    #: Reverse direction (§10.5) — true geodesic distance in metres, never
    #: decimal degrees.
    distance_m: Optional[float] = None

    #: Which side of a centerline the answer sits on, where one was chosen.
    #: §11.3 makes the side the selector for the matched attribute set, so the
    #: enhanced interface needs it to report the record the match actually came
    #: from (§8.2). None for an address point, which has no sides, and None at
    #: rung 3, which chose no position and therefore no side.
    side: Optional[Side] = None

    @property
    def match_score(self) -> float:
        return self.quality.match_score

    @property
    def location_type(self) -> LocationType:
        return self.quality.location_type

    @property
    def confidence(self) -> float:
        return self.quality.confidence

    @property
    def nguid(self) -> Optional[str]:
        return self.record.nguid

    @property
    def crs(self) -> str:
        """The CRS of the answer, positional or line.

        A position follows decision 55: EPSG:4979 where the geometry's Z was
        admitted, EPSG:4326 where it was not.

        A rung-3 line answer is CRS_2D (decision 85, resolving Appendix C.4
        Q22). This property used to return None there, abstaining because
        decision 55 speaks of "the point" while a line carries one Z per
        vertex. The abstention ends because a prior fact dissolves the
        question rather than answering it: RoadCenterLine is not a declared
        3D-capable feature class (§10.5), so the provisioned layer's
        MultiLineString Z geometry type is an artifact of the GeoPackage
        export — a Z-typed layer supplies a Z slot on every vertex whether or
        not the data model says the slot means anything — and not a
        declaration that road-surface elevation is authoritative vertical
        attribution. The layer's Z is never consulted, at any rung.

        That makes a rung-3 answer 2D on exactly the basis rung 2 already is.
        R1 is generalized, not contradicted: R1's conclusion was right, but
        its original argument (§7.3's perpendicular offset displacing a
        road-surface Z onto a parcel) was narrower than its scope needed, and
        Q22 was correct that the argument does not transfer to an undisplaced
        line. The broader ground covers both rungs.
        """
        return CRS_2D if self.position is None else self.position.crs
