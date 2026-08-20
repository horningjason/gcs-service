"""Generates tests/regression/inputs/*.xml from data/data.gpkg.

This script is committed; its OUTPUT is not (tests/regression/inputs/ is
gitignored — "may contain real address data"). With ONE deliberate, named
exception (FWD-DROPPED-HNO-{ENH,STRICT}-001 — see that block's own comment
below), addresses and coordinates are never hardcoded here: every fixture is
discovered at generation time by querying whatever GeoPackage GCS_GPKG_PATH
points at, by SHAPE of condition (an exact address point, an ambiguous
same-address pair, a rural RCL segment far from any address point, ...)
rather than by name. Point this at a different jurisdiction's export and
every fixture but that one produces a different, still sensible, discovery.

Run once after cloning (or whenever data.gpkg changes):

    python -m tests.regression.build_inputs

It is idempotent — re-running overwrites inputs/ with fresh discoveries from
whatever data is currently loaded. seed.py calls this automatically when
inputs/ is empty (mirroring how it auto-seeds golden/ on a first run), but
does not re-run it once files exist, for the same "don't silently reset the
baseline" reason golden files are never casually regenerated.
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path

import geopandas as gpd
from dotenv import load_dotenv
from lxml import etree

from tests.regression.manifest import CASES

load_dotenv()

INPUTS_DIR = Path(__file__).parent / "inputs"

_ENTITY = "pres:gcs-regression@example.com"

_NS_DECL = (
    'xmlns="urn:ietf:params:xml:ns:pidf" '
    'xmlns:dm="urn:ietf:params:xml:ns:pidf:data-model" '
    'xmlns:gp="urn:ietf:params:xml:ns:pidf:geopriv10"'
)


# ---------------------------------------------------------------------------
# Document assembly (§1.4 namespaces, §4.2 device/tuple/person precedence)
# ---------------------------------------------------------------------------

def _geopriv(chunk: str) -> str:
    return f"<gp:geopriv><gp:location-info>{chunk}</gp:location-info><gp:usage-rules/></gp:geopriv>"


def _tuple(chunk: str, tid: str = "t1") -> str:
    return f'<tuple id="{tid}"><status>{_geopriv(chunk)}</status></tuple>'


def _device(chunk: str, did: str = "d1") -> str:
    return f'<dm:device id="{did}">{_geopriv(chunk)}</dm:device>'


def presence(*containers: str, entity: str = _ENTITY) -> str:
    inner = "\n  ".join(containers)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<presence {_NS_DECL} entity="{entity}">\n  {inner}\n</presence>\n'
    )


def civic_chunk(
    *, country="US", a1="ND", a2, a3, rd, sts, hno=None, pod=None, unit_value=None,
    st_pretyp=None,
) -> str:
    fields = [
        f"<ca:country>{country}</ca:country>",
        f"<ca:A1>{a1}</ca:A1>",
        f"<ca:A2>{a2}</ca:A2>",
        f"<ca:A3>{a3}</ca:A3>",
        f"<ca:RD>{rd}</ca:RD>",
        f"<ca:STS>{sts}</ca:STS>",
    ]
    if pod:
        fields.append(f"<ca:POD>{pod}</ca:POD>")
    if hno is not None:
        fields.append(f"<ca:HNO>{hno}</ca:HNO>")
    ns = 'xmlns:ca="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr"'
    if unit_value is not None:
        ns += ' xmlns:cdx2="urn:nena:xml:ns:pidf:nenaCivicAddr2"'
        fields.append(f"<cdx2:UNIT_VALUE>{unit_value}</cdx2:UNIT_VALUE>")
    # St_PreTyp (RFC 6848 civicAddr:ext, "STP" -- src/api/wire/civic_xml.py's
    # own mapping table) -- a street PRE-TYPE qualifier like "Interstate",
    # distinct from POD's pre/post-DIRECTIONAL. Included only when the
    # picked record actually carries a non-blank value, so a query built
    # around an ordinary street (no pre-type) is not padded with an empty
    # element, and one built around a route-class street (e.g. an
    # Interstate ramp/mainline) is not silently less specific than what the
    # record itself, or a real caller reading a sign, would supply.
    if st_pretyp and st_pretyp.strip():
        ns += ' xmlns:cae="urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr:ext"'
        fields.append(f"<cae:STP>{st_pretyp.strip()}</cae:STP>")
    return f'<ca:civicAddress {ns}>{"".join(fields)}</ca:civicAddress>'


_GML_NS = 'xmlns:gml="http://www.opengis.net/gml"'
_GS_NS = 'xmlns:gs="http://www.opengis.net/pidflo/1.0"'


def point_chunk(lat: float, lon: float, z: float | None = None) -> str:
    pos = f"{lat} {lon} {z}" if z is not None else f"{lat} {lon}"
    return f'<gml:Point {_GML_NS} srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>{pos}</gml:pos></gml:Point>'


def circle_chunk(lat: float, lon: float, radius_m: float) -> str:
    return (
        f'<gs:Circle {_GS_NS} {_GML_NS} srsName="urn:ogc:def:crs:EPSG::4326">'
        f"<gml:pos>{lat} {lon}</gml:pos>"
        f'<gs:radius uom="urn:ogc:def:uom:EPSG::9001">{radius_m}</gs:radius></gs:Circle>'
    )


def polygon_chunk(lat: float, lon: float, half_deg: float = 0.0005) -> str:
    ring = (
        f"{lat - half_deg} {lon - half_deg} {lat + half_deg} {lon - half_deg} "
        f"{lat + half_deg} {lon + half_deg} {lat - half_deg} {lon + half_deg} "
        f"{lat - half_deg} {lon - half_deg}"
    )
    return (
        f"<gml:Polygon {_GML_NS}><gml:exterior><gml:LinearRing>"
        f"<gml:posList>{ring}</gml:posList>"
        "</gml:LinearRing></gml:exterior></gml:Polygon>"
    )


def ellipse_chunk(lat: float, lon: float, major_m: float, minor_m: float, orientation_deg: float) -> str:
    return (
        f'<gs:Ellipse {_GS_NS} {_GML_NS}><gml:pos>{lat} {lon}</gml:pos>'
        f'<gs:semiMajorAxis uom="urn:ogc:def:uom:EPSG::9001">{major_m}</gs:semiMajorAxis>'
        f'<gs:semiMinorAxis uom="urn:ogc:def:uom:EPSG::9001">{minor_m}</gs:semiMinorAxis>'
        f'<gs:orientation uom="urn:ogc:def:uom:EPSG::9102">{orientation_deg}</gs:orientation></gs:Ellipse>'
    )


def sphere_chunk(lat: float, lon: float, radius_m: float, z: float | None = None) -> str:
    pos = f"{lat} {lon} {z}" if z is not None else f"{lat} {lon}"
    return (
        f'<gs:Sphere {_GS_NS} {_GML_NS}><gml:pos>{pos}</gml:pos>'
        f'<gs:radius uom="urn:ogc:def:uom:EPSG::9001">{radius_m}</gs:radius></gs:Sphere>'
    )


def ellipsoid_chunk(
    lat: float, lon: float, z: float, major_m: float, minor_m: float,
    vertical_m: float, orientation_deg: float,
) -> str:
    return (
        f'<gs:Ellipsoid {_GS_NS} {_GML_NS}><gml:pos>{lat} {lon} {z}</gml:pos>'
        f'<gs:semiMajorAxis uom="urn:ogc:def:uom:EPSG::9001">{major_m}</gs:semiMajorAxis>'
        f'<gs:semiMinorAxis uom="urn:ogc:def:uom:EPSG::9001">{minor_m}</gs:semiMinorAxis>'
        f'<gs:verticalAxis uom="urn:ogc:def:uom:EPSG::9001">{vertical_m}</gs:verticalAxis>'
        f'<gs:orientation uom="urn:ogc:def:uom:EPSG::9102">{orientation_deg}</gs:orientation>'
        "</gs:Ellipsoid>"
    )


def prism_chunk(lat: float, lon: float, z: float, half_deg: float, height_m: float) -> str:
    """A base polygon congruent with `polygon_chunk`'s, extruded to `height_m`.

    Matching the base footprint exactly (rather than an independently chosen
    one) is deliberate — REV-PRISM-ENH-001 uses it to assert equivalence with
    REV-CONTAINED-POLYGON-ENH-001's contained set, since no provisioned SSAP
    carries a Z (§10.5, decision 60) and `Prism.contains()` skips the vertical
    test entirely when the candidate's altitude is None.

    Uses the `gml:pos`-per-vertex ring spelling (schemas/gml-geoshape's
    LinearRingType offers this as an explicit alternative to `gml:posList`),
    NOT `gml:posList srsDimension="3"` — the bundled GML schema's
    DirectPositionListType declares only a `count` attribute, no
    `srsDimension`, so a 3D posList 454s at schema validation even though
    `gml_xml.py::_ring_vertices` parses `srsDimension` when present. Real gap
    between the schema and the parser, found building this fixture; reported
    rather than worked around in src/, since this module writes fixtures and
    the pos-per-vertex spelling is independently valid GML that already
    exercises `_ring_vertices`'s other branch.
    """
    corners = (
        (lat - half_deg, lon - half_deg),
        (lat + half_deg, lon - half_deg),
        (lat + half_deg, lon + half_deg),
        (lat - half_deg, lon + half_deg),
    )
    pos_elements = "".join(f"<gml:pos>{a} {b} {z}</gml:pos>" for a, b in corners)
    return (
        f'<gs:Prism {_GS_NS} {_GML_NS}><gs:base><gml:Polygon><gml:exterior>'
        f"<gml:LinearRing>{pos_elements}</gml:LinearRing>"
        "</gml:exterior></gml:Polygon></gs:base>"
        f'<gs:height uom="urn:ogc:def:uom:EPSG::9001">{height_m}</gs:height></gs:Prism>'
    )


def arcband_chunk(
    lat: float, lon: float, inner_m: float, outer_m: float,
    start_deg: float, opening_deg: float,
) -> str:
    return (
        f'<gs:ArcBand {_GS_NS} {_GML_NS}><gml:pos>{lat} {lon}</gml:pos>'
        f'<gs:innerRadius uom="urn:ogc:def:uom:EPSG::9001">{inner_m}</gs:innerRadius>'
        f'<gs:outerRadius uom="urn:ogc:def:uom:EPSG::9001">{outer_m}</gs:outerRadius>'
        f'<gs:startAngle uom="urn:ogc:def:uom:EPSG::9102">{start_deg}</gs:startAngle>'
        f'<gs:openingAngle uom="urn:ogc:def:uom:EPSG::9102">{opening_deg}</gs:openingAngle>'
        "</gs:ArcBand>"
    )


# ---------------------------------------------------------------------------
# Discovery — find real records satisfying a condition, never by name
# ---------------------------------------------------------------------------

class Fixtures:
    """One load of data.gpkg, then a set of condition-based lookups."""

    def __init__(self, gpkg_path: str):
        self.ssap = gpd.read_file(gpkg_path, layer="SiteStructureAddressPoint")
        self.rcl = gpd.read_file(gpkg_path, layer="RoadCenterLine")
        self.ssap = self.ssap[self.ssap["Add_Number"].notna() & (self.ssap["Add_Number"] > 0)]
        # Captured BEFORE the A3-blank filter below, for rcl_only_street()'s
        # "does any address point exist on this street at all" check. A
        # record with a blank A3 (city resolved only through the community
        # cascade's Post_Comm fallback — decision 66/76 — never through A3
        # itself) is still a real, scoreable SSAP record; excluding it here
        # would make rcl_only_street() blind to it and pick a street that
        # is not actually SSAP-free. Real example this caught: two
        # Interstate-94 address points in Bismarck (Add_Number 13100/13101,
        # St_PreTyp='Interstate', A3='') were invisible to the OLD
        # ssap_names check below, which let rcl_only_street() pick "94" as
        # "quiet" when it demonstrably is not. The self.ssap filtered below
        # is still correct for every OTHER lookup in this class, which do
        # need a real, fully-attributed A3 (home_city(), exact_point(),
        # ambiguous_pair(), etc.) — only "does an address point exist on
        # this street at all" questions (rcl_only_street(),
        # sparse_scattered_street()) must see every address point,
        # attributed or not.
        self._ssap_raw = self.ssap[self.ssap["St_Name"].notna()]
        self._all_ssap_street_names = set(self._ssap_raw["St_Name"])
        self.ssap = self.ssap[self.ssap["St_Name"].notna() & (self.ssap["A3"].str.strip() != "")]

    # -- a clean, ordinary exact address point in the busiest jurisdiction --
    def home_city(self) -> str:
        return self.ssap["A3"].value_counts().idxmax()

    def exact_point(self) -> "gpd.GeoSeries":
        city = self.home_city()
        candidates = self.ssap[self.ssap["A3"] == city].sort_values("NGUID")
        return candidates.iloc[0]

    # -- a real RoadCenterLine street with NO SiteStructureAddressPoint on
    #    it anywhere in the dataset -- the only way a no-house-number query
    #    cleanly degrades to a rung-3 LineString on real data. §6.2 has no
    #    progressive filter: dropping HNO doesn't narrow anything, so on a
    #    well-provisioned street EVERY address point on it still scores 100
    #    (Add_Number isn't even a compared term once unpopulated, decision
    #    66) and rung-1 always beats rung-3 (decision 70) -- with enough
    #    points on a real street almost always spanning more than
    #    GCS_AMBIGUITY_TOLERANCE_M, that's 468, not a clean LineString.
    #    Only a street genuinely absent from the SSAP layer forces rung-3.
    #
    #    EXACT-STRING ABSENCE IS NECESSARY BUT NOT SUFFICIENT. The real
    #    scorer compares street names by Soundex-or-edit-distance (decision
    #    71/72), not exact match, so a name merely ABSENT from SSAP can
    #    still pull in every address point on a DIFFERENT, fuzzy-similar
    #    real street. Found on real data: "Airport Frontage Road" is
    #    genuinely absent from SSAP, but 138 real "Airport Road" address
    #    points in Bismarck scored 71.88% similar on St_Name -- comfortably
    #    above _STREET_QUALIFY_MIN_EDIT_SIM (0.5) -- and flooded in when
    #    this method picked it purely on exact-name exclusion. Each
    #    name-exclusive candidate below is therefore validated empirically
    #    against the REAL engine (this suite's own "confirm the observed
    #    outcome is actually correct, not just plausible" discipline,
    #    tests/regression/README.md) before being accepted -- a check that
    #    cannot go stale the way reimplementing the similarity threshold
    #    here would. --
    def rcl_only_street(self):
        city = self.home_city()
        segs = self.rcl[
            (self.rcl["A3_L"] == city) & ~self.rcl["St_Name"].isin(self._all_ssap_street_names)
            & self.rcl["St_Name"].notna()
        ].sort_values("NGUID")

        seen_names: set[str] = set()
        tried: list[str] = []
        for _, row in segs.iterrows():
            name = row["St_Name"]
            if name in seen_names:
                continue
            seen_names.add(name)
            tried.append(name)
            if _rcl_candidate_is_empirically_quiet(row):
                return row

        raise LookupError(
            f"no RCL street in {city!r} produced a clean, single-candidate "
            f"rung-3 answer after empirical validation against the real "
            f"engine -- tried {len(tried)} name-exclusive candidates "
            f"({tried[:10]}{'...' if len(tried) > 10 else ''})"
        )

    # -- the same street/number one block over, with no address point there,
    #    but inside an RCL segment's range: rung-2 interpolation --
    def interpolation_target(self, exact_row) -> tuple[str, int]:
        street, city = exact_row["St_Name"], exact_row["A3"]
        covered = set(self.ssap[(self.ssap["St_Name"] == street) & (self.ssap["A3"] == city)]["Add_Number"])
        segs = self.rcl[(self.rcl["St_Name"] == street)]
        for _, seg in segs.iterrows():
            for lo, hi, parity in ((seg["FromAddr_L"], seg["ToAddr_L"], seg["Parity_L"]),
                                    (seg["FromAddr_R"], seg["ToAddr_R"], seg["Parity_R"])):
                if lo is None or hi is None or hi <= lo:
                    continue
                step = 2
                start = int(lo) + step * 2  # inside the endpoint margin, not on it
                for n in range(start, int(hi) - step, step):
                    if n not in covered:
                        return street, n
        raise LookupError(f"no interpolation gap found on {street!r}")

    # -- a house number between two consecutive same-street segments'
    #    ranges: covered by neither, so rung-2 cannot place it --
    def range_gap_target(self, street: str) -> int:
        segs = self.rcl[self.rcl["St_Name"] == street].copy()
        bounds = sorted(
            {int(v) for v in list(segs["FromAddr_L"].dropna()) + list(segs["ToAddr_L"].dropna())
             if v is not None}
        )
        for lo, hi in zip(bounds, bounds[1:]):
            if hi - lo >= 4:
                candidate = lo + 1  # first number strictly after lo, before the next range starts
                covered_by_any = any(
                    (seg["FromAddr_L"] is not None and seg["FromAddr_L"] <= candidate <= seg["ToAddr_L"])
                    or (seg["FromAddr_R"] is not None and seg["FromAddr_R"] <= candidate <= seg["ToAddr_R"])
                    for _, seg in segs.iterrows()
                )
                if not covered_by_any:
                    return candidate
        raise LookupError(f"no range gap found on {street!r}")

    # -- two SSAPs sharing (Add_Number, St_Name, St_PosTyp) but distinct
    #    UnitValue: the legitimate multi-candidate case §6.3 exists for.
    #    `skip` selects the Nth qualifying pair, so two independent fixtures
    #    (an ambiguity case and a contrasting one) don't collide on the same
    #    real address. --
    def ambiguous_pair(self, skip: int = 0):
        key = ["Add_Number", "St_Name", "St_PosTyp"]
        counts = self.ssap.groupby(key).size()
        pairs = counts[counts == 2].index
        found = 0
        for num, name, postyp in pairs:
            rows = self.ssap[(self.ssap["Add_Number"] == num) & (self.ssap["St_Name"] == name)
                              & (self.ssap["St_PosTyp"] == postyp)]
            units = rows["UnitValue"].dropna().unique()
            if len(units) == 2 and all(u and str(u).strip() for u in units):
                if found == skip:
                    return rows.iloc[0], rows.iloc[1]
                found += 1
        raise LookupError(f"no ambiguous same-address pair found at skip={skip}")

    # -- an address point in a jurisdiction other than the busiest one, for
    #    cross-boundary admin-element sourcing --
    def cross_boundary_point(self):
        home_county = self.ssap[self.ssap["A3"] == self.home_city()]["A2"].iloc[0]
        other = self.ssap[self.ssap["A2"] != home_county]
        return other.sort_values("NGUID").iloc[0]

    # -- a genuine data-hygiene duplicate cluster: same full address, four
    #    or more distinct NGUIDs --
    def duplicate_cluster(self):
        key = ["Add_Number", "St_Name", "St_PosTyp", "A2", "A3"]
        counts = self.ssap.groupby(key).size()
        big = counts[counts >= 4]
        if len(big) == 0:
            raise LookupError("no duplicate cluster of >=4 found")
        num, name, postyp, a2, a3 = big.index[0]
        row = self.ssap[(self.ssap["Add_Number"] == num) & (self.ssap["St_Name"] == name)
                         & (self.ssap["St_PosTyp"] == postyp) & (self.ssap["A2"] == a2)
                         & (self.ssap["A3"] == a3)].iloc[0]
        return row

    # -- a rural RCL segment whose midpoint is farther than the reverse
    #    search radius from the nearest address point: reverse search can
    #    only land on the road, so the house number must be synthesised --
    def isolated_rcl_midpoint(self, radius_m: float) -> tuple[float, float]:
        metric_ssap = self.ssap.to_crs(32614)
        metric_rcl = self.rcl[self.rcl.geometry.notnull()].to_crs(32614)
        sindex = metric_ssap.sindex
        for _, seg in metric_rcl.sample(frac=1.0, random_state=7).iterrows():
            mid = seg.geometry.interpolate(0.5, normalized=True)
            idx = sindex.nearest(mid, return_all=False)[1][0]
            nearest = metric_ssap.geometry.iloc[idx]
            if mid.distance(nearest) > radius_m * 1.5:
                lonlat = gpd.GeoSeries([mid], crs=32614).to_crs(4326).iloc[0]
                return lonlat.y, lonlat.x
        raise LookupError("no isolated RCL segment found")

    # -- a point nowhere near any provisioned feature at all --
    def far_no_match_point(self) -> tuple[float, float]:
        miny = min(self.ssap["Latitude"].min(), self.rcl.total_bounds[1])
        minx = min(self.ssap["Longitude"].min(), self.rcl.total_bounds[0])
        return miny - 3.0, minx - 3.0

    def geocoded_placement_point(self):
        rows = self.ssap[self.ssap["Placement"] == "Geocoding"]
        if len(rows) == 0:
            raise LookupError("no Placement=Geocoding record found")
        return rows.sort_values("NGUID").iloc[0]


def _pos_direction(row) -> str | None:
    v = row.get("St_PosDir")
    return v if isinstance(v, str) and v.strip() else None


def _rcl_candidate_is_empirically_quiet(row) -> bool:
    """Dispatches a no-house-number query for `row`'s street through the
    REAL engine (harness.initialize() must already have run — see build())
    and confirms it produces exactly one candidate, a STREET_SEGMENT. That
    is the only check that actually proves the street is free of
    interfering address points, real or fuzzy-matched -- see
    rcl_only_street()'s own docstring for the real-data case (name-absent
    "Airport Frontage Road" vs. fuzzy-matched "Airport Road") that made
    exact-string absence from SSAP insufficient on its own.
    """
    from tests.regression.harness import _dispatch_geocode_enhanced

    doc = presence(_tuple(civic_chunk(
        a2=row["A2_L"], a3=row["A3_L"], rd=row["St_Name"], sts=row["St_PosTyp"],
        pod=_pos_direction(row), st_pretyp=row.get("St_PreTyp"),
    )))
    response = _dispatch_geocode_enhanced(doc.encode("utf-8"), "application/xml")
    if response["status"] != 200:
        return False
    candidates = json.loads(response["body"]).get("candidates", [])
    return len(candidates) == 1 and candidates[0]["locationType"] == "STREET_SEGMENT"


def _narrowing_demonstrated(fixture_id: str, chunk: str, doc: str) -> tuple[int, int]:
    """Confirms decision 122's narrowing is actually exercised by `doc`,
    against the REAL engine (harness.initialize() must already have run —
    see build()), the same "validate against the real engine, not just the
    discovery condition" discipline `_rcl_candidate_is_empirically_quiet`
    uses.

    `chunk` is dispatched through `src.reverse.search.search` directly to
    get the UNNARROWED hit count — the same real ssap/rcl records and
    GCS_REVERSE_SEARCH_RADIUS_M the production path uses, before decision
    122's narrowing ever runs. `doc` is dispatched through the real
    ReverseGeocodeEnhanced handler to get the NARROWED candidate count decision
    122 actually returns. Raises AssertionError — a generation-time failure,
    not something to seed anyway — where:

    * any surviving candidate is not `contained` (the narrowing is broken, or
      this fixture's shape has no extent and doesn't belong in this set), or
    * the narrowed count is not strictly between 0 and the unnarrowed count —
      a shape containing everything within the radius, or nothing, exercises
      no narrowing and proves nothing about decision 122.

    Returns (unnarrowed, narrowed) so the caller can report both, the same
    numbers this function used to decide pass/fail.
    """
    from src import runtime_state
    from src.api.wire import gml_xml
    from src.api.wire.xml_ns import XML_PARSER
    from src.gis import provisioning
    from src.reverse import origin as origin_shapes
    from src.reverse import search as reverse_search
    from tests.regression.harness import _dispatch_reverse_enhanced

    shape = gml_xml.parse_shape(etree.fromstring(chunk.encode("utf-8"), XML_PARSER))
    origin = origin_shapes.origin_of(shape)
    unnarrowed = reverse_search.search(
        origin,
        ssap=provisioning.ssap_records(),
        rcl=provisioning.rcl_records(),
        radius_m=runtime_state._reverse_search_radius_m,
    )

    response = _dispatch_reverse_enhanced(doc.encode("utf-8"), "application/xml")
    if response["status"] != 200:
        raise AssertionError(f"{fixture_id}: expected 200, got {response['status']}")
    narrowed = json.loads(response["body"])["candidates"]

    if not all(c["contained"] for c in narrowed):
        raise AssertionError(
            f"{fixture_id}: a surviving candidate is not contained — decision "
            "122's narrowing should have removed it"
        )
    if not (0 < len(narrowed) < len(unnarrowed)):
        raise AssertionError(
            f"{fixture_id}: narrowing not demonstrated — {len(narrowed)} of "
            f"{len(unnarrowed)} unnarrowed hits survived, not strictly "
            "between 0 and the unnarrowed count. Resize the shape."
        )
    print(f"  {fixture_id}: {len(unnarrowed)} unnarrowed -> {len(narrowed)} contained")
    return len(unnarrowed), len(narrowed)


#: Comment prose wraps to this width, GCS's own tests/requests/*.xml style
#: (2-space indent) rather than lvf-service's flush-left, but the same
#: underlying discipline lvf's own comments follow — nothing left as one
#: unbroken line, everything comfortably under 90 columns.
_COMMENT_WIDTH = 78
_COMMENT_INDENT = "  "

#: A root <presence ...> tag's namespace declarations plus `entity` routinely
#: run 150-250 columns as one line. Matched against the opening tag lxml's
#: pretty-printer emits (attributes stay inline; only child ELEMENTS get
#: indented onto their own lines) and rewritten one attribute per line,
#: aligned under the tag name — GCS's own tests/requests/*.xml convention.
_ROOT_TAG_RE = re.compile(r'^<(\w+)((?:\s+[\w:.\-]+="[^"]*")*)>$')
_ATTR_RE = re.compile(r'([\w:.\-]+)="([^"]*)"')


def _reformat_root_tag(xml_text: str) -> str:
    first_line, _, rest = xml_text.partition("\n")
    match = _ROOT_TAG_RE.match(first_line)
    if match is None:
        return xml_text
    tag, attrs_blob = match.group(1), match.group(2)
    attrs = _ATTR_RE.findall(attrs_blob)
    if len(attrs) <= 1:
        return xml_text
    indent = " " * (len(tag) + 2)
    lines = [f'<{tag} {attrs[0][0]}="{attrs[0][1]}"']
    lines += [f'{indent}{name}="{value}"' for name, value in attrs[1:]]
    return "\n".join(lines) + ">\n" + rest


def _write(test_id: str, comment: str, doc: str) -> None:
    """Pretty-print the assembled document (lxml's etree.indent, one element
    per line, matching both lvf-service's and GCS's own hand-formatted
    fixtures) and wrap the header comment, rather than emitting either as
    one long line."""
    header, body_xml = doc.split("\n", 1)
    root = etree.fromstring(body_xml.encode("utf-8"))
    etree.indent(root, space="  ")
    pretty = etree.tostring(root, pretty_print=True).decode("utf-8")
    pretty = _reformat_root_tag(pretty)
    wrapped_comment = textwrap.fill(
        comment.strip(), width=_COMMENT_WIDTH,
        initial_indent=_COMMENT_INDENT, subsequent_indent=_COMMENT_INDENT,
    )
    (INPUTS_DIR / f"{test_id}.xml").write_bytes(
        f"{header}\n<!--\n{wrapped_comment}\n-->\n{pretty}".encode("utf-8")
    )


def _write_raw(test_id: str, body: bytes) -> None:
    (INPUTS_DIR / f"{test_id}.xml").write_bytes(body)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build() -> None:
    gpkg_path = os.environ.get("GCS_GPKG_PATH", "data/data.gpkg")
    if not os.path.exists(gpkg_path):
        raise SystemExit(
            f"GCS_GPKG_PATH={gpkg_path!r} not found — set it in .env before "
            "building regression fixtures."
        )
    INPUTS_DIR.mkdir(exist_ok=True)

    # rcl_only_street() validates its candidates empirically against the
    # real engine (see its own docstring for why exact-string absence from
    # SSAP isn't sufficient), which needs the real schema, scorer, and GIS
    # data loaded first -- the same "synchronous startup for tests and
    # tooling that do not run the ASGI lifespan" harness.py itself uses.
    from tests.regression import harness
    harness.initialize()

    fx = Fixtures(gpkg_path)
    radius_m = float(os.environ.get("GCS_REVERSE_SEARCH_RADIUS_M", "250"))

    exact = fx.exact_point()
    city, county = exact["A3"], exact["A2"]
    street, postyp = exact["St_Name"], exact["St_PosTyp"]
    hno = int(exact["Add_Number"])
    lat, lon = float(exact["Latitude"]), float(exact["Longitude"])
    pod = _pos_direction(exact)

    def exact_civic(**overrides) -> str:
        fields = dict(a2=county, a3=city, rd=street, sts=postyp, hno=hno, pod=pod)
        fields.update(overrides)
        return civic_chunk(**fields)

    interp_street, interp_hno = fx.interpolation_target(exact)
    gap_hno = fx.range_gap_target(street)

    (pair0_a, pair0_b) = fx.ambiguous_pair(skip=0)
    (pair1_a, pair1_b) = fx.ambiguous_pair(skip=1)

    def pair_civic(row, with_unit: bool) -> str:
        return civic_chunk(
            a2=row["A2"], a3=row["A3"], rd=row["St_Name"], sts=row["St_PosTyp"],
            hno=int(row["Add_Number"]),
            unit_value=row["UnitValue"] if with_unit else None,
        )

    quiet = fx.rcl_only_street()
    quiet_city, quiet_county = quiet["A3_L"], quiet["A2_L"]
    quiet_street, quiet_postyp = quiet["St_Name"], quiet["St_PosTyp"]
    quiet_pretyp = quiet.get("St_PreTyp")
    quiet_pod = _pos_direction(quiet)

    def quiet_civic(**overrides) -> str:
        fields = dict(a2=quiet_county, a3=quiet_city, rd=quiet_street, sts=quiet_postyp,
                      pod=quiet_pod, st_pretyp=quiet_pretyp)
        fields.update(overrides)
        return civic_chunk(**fields)

    # Human-readable form for the two comment templates below -- includes
    # the pre-type ("Interstate 94 Ramp") when the picked street has one,
    # rather than always reading as an ordinary street ("94 Ramp").
    quiet_label = (
        f"{quiet_pretyp.strip()} {quiet_street} {quiet_postyp}"
        if quiet_pretyp and quiet_pretyp.strip()
        else f"{quiet_street} {quiet_postyp}"
    )

    cross = fx.cross_boundary_point()
    dup = fx.duplicate_cluster()
    placement = fx.geocoded_placement_point()
    iso_lat, iso_lon = fx.isolated_rcl_midpoint(radius_m)
    far_lat, far_lon = fx.far_no_match_point()

    # -- ADM -----------------------------------------------------------
    _write_raw("ADM-MALFORMED-XML-001", b"<presence><unclosed>")
    _write_raw("ADM-EMPTY-BODY-001", b"")
    _write_raw(
        "ADM-NOT-PIDF-001",
        b'<?xml version="1.0"?><findService xmlns="urn:ietf:params:xml:ns:lost1"/>',
    )
    _write(
        "ADM-SCHEMA-INVALID-001",
        f"POST to /Gcs/v1/Geocode. An otherwise-valid civicAddress for "
        f"{hno} {street} {postyp}, {city}, {county}, carrying one bogus "
        f"element the schema does not declare. Expected: 454 schema "
        f"validation failure.",
        presence(_tuple(exact_civic().replace(
            "</ca:civicAddress>", "<ca:BOGUS>x</ca:BOGUS></ca:civicAddress>"
        ))),
    )
    _write(
        "ADM-WRONG-PROFILE-GEO-001",
        "POST to /Gcs/v1/Geocode with a geodetic chunk instead of a civic "
        "one — a schema-valid PIDF-LO carrying the wrong profile for this "
        "operation. Expected: 468.",
        presence(_tuple(point_chunk(lat, lon))),
    )
    _write(
        "ADM-WRONG-PROFILE-CIVIC-001",
        "POST to /Gcs/v1/ReverseGeocode with a civic chunk instead of a "
        f"geodetic one ({hno} {street} {postyp}, {city}). Expected: 468.",
        presence(_tuple(exact_civic())),
    )
    _write(
        "ADM-NO-LOCATION-001",
        "POST to /Gcs/v1/Geocode. A well-formed, schema-valid presence "
        "document whose tuple carries <status> with no <gp:geopriv> at all: "
        "nothing convertible, but the request is not malformed. "
        "Expected: 468.",
        presence('<tuple id="t1"><status><basic>open</basic></status></tuple>'),
    )
    multi_doc = presence(
        _tuple(exact_civic(a2=cross["A2"], a3=cross["A3"], rd=cross["St_Name"],
                            sts=cross["St_PosTyp"], hno=int(cross["Add_Number"]),
                            pod=_pos_direction(cross))),
        _device(exact_civic()),
    )
    _write(
        "ADM-MULTI-LOC-ENH-001",
        "POST to /Gcs/v1/GeocodeEnhanced. Two locations: a <tuple> carrying "
        f"{int(cross['Add_Number'])} {cross['St_Name']} {cross['St_PosTyp']}, "
        f"{cross['A3']}, and a <dm:device> carrying {hno} {street} {postyp}, "
        f"{city}. The device location is elected regardless of document "
        "order. Expected: 200, locationCount=2, candidates for the device's "
        "address.",
        multi_doc,
    )
    _write(
        "ADM-MULTI-LOC-STRICT-001",
        "The same two-location document as ADM-MULTI-LOC-ENH-001, POSTed to "
        "the strict /Gcs/v1/Geocode instead. Expected: 200, no "
        "locationCount in the body — the strict interface has no field for "
        "it — only the elected device address's converted result.",
        multi_doc,
    )
    _write(
        "ADM-NONNUMERIC-COORD-001",
        "POST to /Gcs/v1/ReverseGeocode. A gml:pos carrying "
        '"north west" where the XSD requires a doubleList. Expected: 454.',
        presence(_tuple(
            '<gml:Point xmlns:gml="http://www.opengis.net/gml">'
            "<gml:pos>north west</gml:pos></gml:Point>"
        )),
    )
    _write(
        "ADM-SPHERE-UNREADABLE-001",
        "POST to /Gcs/v1/ReverseGeocode. A gs:Sphere with a 2D centre — "
        "schema-valid, since gml:pos does not constrain ordinate count, but "
        "not a readable solid. Expected: 454, 'could not be read'.",
        presence(_tuple(sphere_chunk(lat, lon, 50))),
    )
    _write(
        "ADM-JSON-BODY-001",
        "POST to /Gcs/v1/Geocode with Content-Type: application/json, body "
        "the XML quoted as a JSON string — the other body shape the "
        f"normative YAML declares. Same {hno} {street} {postyp}, {city} "
        "address as FWD-SSAP-EXACT-001. Expected: 200.",
        presence(_tuple(exact_civic())),
    )

    # -- FWD -------------------------------------------------------------
    exact_doc = presence(_tuple(exact_civic()))
    exact_comment = (
        f"POST to {{TARGET}}. {hno} {street} {postyp}, {city}, {county} is a "
        "real SiteStructureAddressPoint, matched exactly at rung 1."
    )
    _write("FWD-SSAP-EXACT-001", exact_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Expected: 200, a gml:Point.", exact_doc)
    _write("FWD-SSAP-EXACT-ENH-001", exact_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Expected: 200, one ranked candidate carrying matchScore, "
           "locationType, confidence and matchType.", exact_doc)

    interp_doc = presence(_tuple(civic_chunk(
        a2=county, a3=city, rd=interp_street, sts=postyp, hno=interp_hno,
    )))
    interp_comment = (
        f"POST to {{TARGET}}. {interp_hno} {interp_street} {postyp}, {city} is "
        "NOT a SiteStructureAddressPoint, but falls inside a RoadCenterLine "
        "segment's address range, so the position is interpolated along that "
        "segment at rung 2."
    )
    _write("FWD-RCL-INTERP-001", interp_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Expected: 200, a gml:Point.", interp_doc)
    _write("FWD-RCL-INTERP-ENH-001", interp_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Expected: 200, locationType=INTERPOLATED_POINT.", interp_doc)

    _write(
        "FWD-STREET-ONLY-001",
        f"POST to /Gcs/v1/Geocode. {quiet_label}, {quiet_city}, queried with "
        "no house number at all. A street-level query is accepted and "
        "answered rather than rejected, at rung 3. This street additionally "
        "carries no SiteStructureAddressPoint anywhere in the data, so "
        "exactly one segment matches and the answer is unambiguous. "
        "Expected: 200, a gml:LineString — the segment's own geometry, not "
        "a Point.",
        presence(_tuple(quiet_civic(hno=None))),
    )
    _write(
        "FWD-NOMATCH-001",
        "POST to /Gcs/v1/Geocode. A street name that does not exist "
        f"anywhere in the loaded GIS data, in the real jurisdiction {city}, "
        "{county}. No candidate clears GCS_MIN_MATCH_SCORE. "
        "Expected: 468.".format(city=city, county=county),
        presence(_tuple(civic_chunk(
            a2=county, a3=city, rd="Nonexistent Fictional", sts="Trail", hno=1,
        ))),
    )
    _write(
        "FWD-GAP-HNO-001",
        f"POST to /Gcs/v1/Geocode. {gap_hno} {street} {postyp}, {city} names "
        "a real street, but that specific house number falls between two "
        "RoadCenterLine segments' address ranges — covered by neither, so "
        "rung-2 interpolation cannot place it. The street itself still "
        "matches, so the answer degrades to a street-level match at rung 3, "
        "on the segment whose own address range sits closest to the queried "
        "number. Expected: 200, a gml:LineString. Distinct from "
        "FWD-NOMATCH-001, where the street itself does not exist.",
        presence(_tuple(civic_chunk(
            a2=county, a3=city, rd=street, sts=postyp, hno=gap_hno,
        ))),
    )

    ambig_doc = presence(_tuple(pair_civic(pair0_a, with_unit=False)))
    ambig_comment = (
        f"POST to {{TARGET}}. {int(pair0_a['Add_Number'])} {pair0_a['St_Name']} "
        f"{pair0_a['St_PosTyp']}, {pair0_a['A3']} resolves to two distinct "
        "SSAP candidates sharing one parcel, differing only by UnitValue — a "
        "genuine multi-candidate address, not a data-hygiene duplicate. On "
        "real statewide data, other "
        f"'{pair0_a['Add_Number']} {pair0_a['St_Name']} *' addresses "
        "elsewhere in the state (different STS/A3, same house number, "
        "fuzzy-similar street name) also clear GCS_MIN_MATCH_SCORE and join "
        "the candidate set, trailing the two intended units by tens of "
        "points."
    )
    _write("FWD-AMBIG-MERGE-001", ambig_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Only the top-scoring tier competes for the single strict "
           "answer, so the far-flung matches take no part. Expected: 200, "
           "the two co-located units merged into a small gs:Circle centred "
           "on them, with its radius sized to their extent.", ambig_doc)
    _write("FWD-AMBIG-CANDIDATES-ENH-001",
           ambig_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Expected: 200, every surviving candidate listed and ranked on "
           "its own merits — no merge, no averaging and no tolerance gate, "
           "so the far-flung matches are visible rather than collapsed "
           "away.", ambig_doc)
    _write(
        "FWD-UNIT-DISAMBIG-001",
        f"POST to /Gcs/v1/Geocode. The same address as FWD-AMBIG-MERGE-001, "
        f"but with UnitValue={pair0_a['UnitValue']!r} supplied. The other "
        "unit on that parcel carries a different UnitValue and is gated out "
        "before scoring, leaving one candidate on the parcel. The far-flung "
        "same-house-number candidates elsewhere in the state carry no "
        "UnitValue to differ on, so they survive that gate and still appear "
        "on GeocodeEnhanced, but they trail the remaining candidate by tens "
        "of points and fall outside the top-scoring tier the strict answer "
        f"is elected from. Expected: 200, the UnitValue="
        f"{pair0_a['UnitValue']!r} record alone.",
        presence(_tuple(pair_civic(pair0_a, with_unit=True))),
    )
    _write(
        "FWD-AMBIG-BISMARCK-ENH-001",
        f"POST to /Gcs/v1/GeocodeEnhanced. A second, independent ambiguous "
        f"pair — {int(pair1_a['Add_Number'])} {pair1_a['St_Name']} "
        f"{pair1_a['St_PosTyp']}, {pair1_a['A3']} — queried without a unit: "
        "a different real address exhibiting the same multi-candidate "
        "condition as FWD-AMBIG-*-001. Expected: 200, the surviving "
        "candidates listed and ranked.",
        presence(_tuple(pair_civic(pair1_a, with_unit=False))),
    )

    # The "94" condition, PINNED BY NAME -- a deliberate, one-time exception
    # to this module's own "discover by shape, never by name" rule (see the
    # module docstring). Interstate 94, Bismarck has exactly two real SSAP
    # records on it, 189.5 m apart -- not FWD-STREET-ONLY-001's zero-
    # address-point street (that fixture still uses quiet_civic(), the
    # genuine "discover a clean street" path, below), and not a tight
    # same-parcel pair either. Real address data, same as every other
    # fixture here -- this file is committed, its output is not (gitignored,
    # see the module docstring). Includes St_PreTyp="Interstate" (`cae:STP`)
    # so the query is as complete as the record itself, and a real caller
    # reading the sign, would supply.
    #
    # PINNED, NOT DISCOVERED, BY EXPLICIT REQUEST: an earlier version of this
    # fixture picked "94" BY ACCIDENT, through two real bugs in
    # rcl_only_street() (see that method's own docstring) -- it queried
    # this address believing it was a "zero address points" street, which
    # it is not, so the fixture's comment claimed a clean rung-3 LineString
    # this address never actually produced. A later revision moved this ID
    # onto a genuinely-quiet discovered street and added a SEPARATE ID to
    # cover "94" on purpose. Collapsed back to one ID, on request, once the
    # comment could finally describe the address's REAL behaviour instead of
    # a discovery-artifact's mistaken claim.
    #
    # That comment then had to be rewritten a THIRD time, by decision 119,
    # and the history is worth keeping because of what each revision was
    # confident about. The accidental version claimed a rung-3 LineString
    # for a bad reason. The corrected version described what the service
    # then actually did -- merge the two SSAP records into a Circle -- and
    # was accurate about the code while the code was wrong: a query with no
    # usable house number was being answered with two address points that
    # are not ramps, carry an empty A3, and sit outside the city limits the
    # caller named, while 19 RoadCenterLine segments matching every element
    # of the query exactly went unscored behind decision 70's short-circuit.
    # Decision 119 makes rung 1 inapplicable without a house number, and the
    # address finally produces the rung-3 LineString the FIRST version
    # claimed for the wrong reason. A fixture comment that faithfully
    # describes observed behaviour is not thereby describing correct
    # behaviour -- which is the argument for reading these comments as a
    # record of what was seen, and the spec as the record of what is right.
    dropped_doc = presence(_tuple(civic_chunk(
        a2="Burleigh County", a3="Bismarck", rd="94", sts="Ramp",
        st_pretyp="Interstate", hno="not-a-number",
    )))
    dropped_comment = (
        "POST to {TARGET}. Interstate 94 Ramp, Bismarck, with an HNO that "
        "will not reduce to a non-negative integer. The element is dropped "
        "rather than the request rejected, and with no usable house number "
        "left the answer falls to a street-level match at rung 3. 19 real "
        "RoadCenterLine segments match every element supplied here exactly "
        "(Interstate/94/Ramp, A3=Bismarck on both sides), tie at identical "
        "confidence and matchScore, and have segment midpoints spanning "
        "roughly 7 km along the corridor."
    )
    _write("FWD-DROPPED-HNO-ENH-001",
           dropped_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Expected: 200, all 19 candidates ranked and scored — top tier "
           "at matchScore 100.0, locationType STREET_SEGMENT, confidence "
           "50.0 — with droppedElements reporting ca:HNO, so a caller "
           "receiving a segment can see why it is a segment.",
           dropped_doc)
    _write("FWD-DROPPED-HNO-STRICT-001",
           dropped_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Rung 3 carries no house-number term to break that tie on, and "
           "this query supplies no house number to measure range proximity "
           "against either, so the tied segments' 7 km spread is tested "
           "against GCS_AMBIGUITY_TOLERANCE_M rather than one of the 19 "
           "being returned as though it were a confident single answer. "
           "Expected: 468.", dropped_doc)

    _write(
        "FWD-GEOCODED-PLACEMENT-ENH-001",
        f"POST to /Gcs/v1/GeocodeEnhanced. {int(placement['Add_Number'])} "
        f"{placement['St_Name']} {placement['St_PosTyp']}, {placement['A3']} "
        "is a real SSAP whose Placement is 'Geocoding' rather than "
        "'Structure' or 'Parcel', so GCS_GEOCODED_PLACEMENT_PENALTY applies "
        "to its score. Expected: 200, the candidate returned with the "
        "penalty reflected in its matchScore and confidence.",
        presence(_tuple(civic_chunk(
            a2=placement["A2"], a3=placement["A3"], rd=placement["St_Name"],
            sts=placement["St_PosTyp"], hno=int(placement["Add_Number"]),
            pod=_pos_direction(placement),
        ))),
    )

    # -- REV ---------------------------------------------------------------
    point_doc = presence(_tuple(point_chunk(lat, lon)))
    point_comment = (
        f"POST to {{TARGET}}. The exact coordinate of the SSAP at {hno} "
        f"{street} {postyp}, {city} (the same address as FWD-SSAP-EXACT-001), "
        "as a bare gml:Point."
    )
    _write("REV-POINT-SSAP-001", point_comment.format(TARGET="/Gcs/v1/ReverseGeocode") +
           " Expected: 200, that same civicAddress handed back.", point_doc)
    _write("REV-POINT-SSAP-ENH-001",
           point_comment.format(TARGET="/Gcs/v1/ReverseGeocodeEnhanced") +
           " Expected: 200, that same address at distanceMeters~=0 with "
           "houseNumberSynthesised=False. A Point has no extent, so it "
           "contains nothing and the candidate list is not narrowed: every "
           "feature within GCS_REVERSE_SEARCH_RADIUS_M is listed.", point_doc)

    iso_doc = presence(_tuple(point_chunk(iso_lat, iso_lon)))
    iso_comment = (
        "POST to {TARGET}. A point on a RoadCenterLine segment farther from "
        "any SiteStructureAddressPoint than 1.5x GCS_REVERSE_SEARCH_RADIUS_M, "
        "so no address point is in range to answer and the house number is "
        "computed by inverting the forward interpolation along that segment."
    )
    _write("REV-RCL-SYNTH-HNO-001", iso_comment.format(TARGET="/Gcs/v1/ReverseGeocode") +
           " Expected: 200, a civicAddress whose HNO was synthesised.", iso_doc)
    _write("REV-RCL-SYNTH-HNO-ENH-001",
           iso_comment.format(TARGET="/Gcs/v1/ReverseGeocodeEnhanced") +
           " Expected: 200, houseNumberSynthesised=True.", iso_doc)

    _write(
        "REV-CIRCLE-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A 100 m gs:Circle around "
        f"{hno} {street} {postyp}, {city} instead of a bare gml:Point. The "
        "shape has extent, so the candidate list narrows to what it "
        "contains, and its extent also damps each candidate's spatial-fit "
        "score. Expected: 200, 49 candidates, all contained=True and all "
        "within the 100 m radius — down from the 154 the flat "
        "GCS_REVERSE_SEARCH_RADIUS_M alone would retrieve.",
        presence(_tuple(circle_chunk(lat, lon, 100))),
    )
    _write(
        "REV-POLYGON-001",
        f"POST to /Gcs/v1/ReverseGeocode. A small gml:Polygon around {hno} "
        f"{street} {postyp}, {city} — the Polygon shape on the strict "
        "interface. Expected: 200, a single civicAddress.",
        presence(_tuple(polygon_chunk(lat, lon, half_deg=0.0004))),
    )
    _write(
        "REV-ELLIPSE-001",
        f"POST to /Gcs/v1/ReverseGeocode. A gs:Ellipse around {hno} {street} "
        f"{postyp}, {city} — one of the less-common RFC 5491 shapes, on the "
        "strict interface. Expected: 200, a single civicAddress.",
        presence(_tuple(ellipse_chunk(lat, lon, 150, 80, 30))),
    )
    _write(
        "REV-SPHERE-VALID-001",
        f"POST to /Gcs/v1/ReverseGeocode. A gs:Sphere with a 3D centre — "
        "readable, unlike ADM-SPHERE-UNREADABLE-001's 2D one — around "
        f"{hno} {street} {postyp}, {city}. Expected: 200, a single "
        "civicAddress.",
        presence(_tuple(sphere_chunk(lat, lon, 50, z=500))),
    )
    _write(
        "REV-NOMATCH-OPENWATER-001",
        "POST to /Gcs/v1/ReverseGeocode. A point well outside this dataset's "
        "coverage entirely, so nothing falls within "
        "GCS_REVERSE_SEARCH_RADIUS_M. Expected: 468, not the nearest "
        "distant address.",
        presence(_tuple(point_chunk(far_lat, far_lon))),
    )
    _write(
        "REV-CROSSCOUNTY-001",
        f"POST to /Gcs/v1/ReverseGeocode. The coordinate of a real SSAP in "
        f"{cross['A2']} ({cross['A3']}), a different jurisdiction from the "
        f"{county} ({city}) most other fixtures sit in. Administrative "
        "elements come from the matched record's own fields rather than "
        "from a boundary polygon. Expected: 200, a civicAddress attributed "
        "to its own county.",
        presence(_tuple(point_chunk(float(cross["Latitude"]), float(cross["Longitude"])))),
    )
    _write(
        "REV-DUPLICATE-TIEBREAK-001",
        f"POST to /Gcs/v1/ReverseGeocode. The coordinate of "
        f"{int(dup['Add_Number'])} {dup['St_Name']} {dup['St_PosTyp']}, "
        f"{dup['A3']}, where the source data carries several SSAP records "
        "with identical attributes but distinct NGUIDs. Expected: 200, a "
        "single civic answer, and the same one on every run — ties break "
        "deterministically by NGUID.",
        presence(_tuple(point_chunk(float(dup["Latitude"]), float(dup["Longitude"])))),
    )
    _write(
        "REV-CONTAINED-POLYGON-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A gml:Polygon clearly "
        f"enclosing {hno} {street} {postyp}, {city}'s SSAP point. The shape "
        "has extent, so the candidate list narrows to what it contains — in "
        "contrast to REV-POINT-SSAP-ENH-001's Point query, which has no "
        "area and so contains nothing. Expected: 200, 54 candidates, all "
        "contained=True, down from the 154 the flat "
        "GCS_REVERSE_SEARCH_RADIUS_M alone would retrieve.",
        presence(_tuple(polygon_chunk(lat, lon, half_deg=0.001))),
    )

    # -- decision 122's narrowing, across every extent-bearing shape --------
    # REV-CIRCLE-ENH-001 and REV-CONTAINED-POLYGON-ENH-001 above are the only
    # two of the seven extent-bearing RFC 5491 shapes decision 122's
    # narrowing had fixture coverage on. The five below close that out.
    # Every one is verified against the real engine before being written
    # (_narrowing_demonstrated) — a shape that turns out to contain
    # everything within GCS_REVERSE_SEARCH_RADIUS_M, or nothing, would be a
    # generation-time failure here rather than a silently-useless fixture.
    ellipse_chunk_ = ellipse_chunk(lat, lon, 180.0, 40.0, 0.0)
    ellipse_doc = presence(_tuple(ellipse_chunk_))
    _write(
        "REV-ELLIPSE-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A markedly non-circular "
        f"gs:Ellipse around {hno} {street} {postyp}, {city} — semi-major "
        "180 m, semi-minor 40 m, oriented due north (0°). Containment here "
        "is directional in a way a Circle's is not: real address points "
        "110-125 m north of the centre, near the major axis, are contained, "
        "while real address points at similar or shorter distance to the "
        "east, off the minor axis, are not. Expected: 200, 32 candidates, "
        "all contained=True, down from the 154 the flat "
        "GCS_REVERSE_SEARCH_RADIUS_M alone would retrieve.",
        ellipse_doc,
    )
    _narrowing_demonstrated("REV-ELLIPSE-ENH-001", ellipse_chunk_, ellipse_doc)

    sphere_chunk_ = sphere_chunk(lat, lon, 100.0, z=500)
    sphere_doc = presence(_tuple(sphere_chunk_))
    _write(
        "REV-SPHERE-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A gs:Sphere (radius 100 m, "
        f"centre Z=500) around {hno} {street} {postyp}, {city} — a solid "
        "rather than a footprint shape. No provisioned SSAP or RCL record "
        "carries an altitude, so the containment test falls back to its "
        "horizontal half and the vertical term does nothing on this data. "
        "Expected: 200, 49 candidates, all contained=True — the same set "
        "REV-CIRCLE-ENH-001's equal-radius Circle returns, down from the "
        "154 the flat GCS_REVERSE_SEARCH_RADIUS_M alone would retrieve.",
        sphere_doc,
    )
    _narrowing_demonstrated("REV-SPHERE-ENH-001", sphere_chunk_, sphere_doc)

    ellipsoid_chunk_ = ellipsoid_chunk(lat, lon, 500.0, 180.0, 40.0, 30.0, 0.0)
    ellipsoid_doc = presence(_tuple(ellipsoid_chunk_))
    _write(
        "REV-ELLIPSOID-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A gs:Ellipsoid around "
        f"{hno} {street} {postyp}, {city} — the same semi-major, semi-minor "
        "and orientation as REV-ELLIPSE-ENH-001 (180 m / 40 m / 0°), plus a "
        "30 m vertical axis. As with REV-SPHERE-ENH-001, no provisioned "
        "record carries an altitude, so containment falls back to its "
        "horizontal ellipse half. Expected: 200, 32 candidates, all "
        "contained=True — the same set REV-ELLIPSE-ENH-001 returns, down "
        "from the 154 the flat GCS_REVERSE_SEARCH_RADIUS_M alone would "
        "retrieve.",
        ellipsoid_doc,
    )
    _narrowing_demonstrated("REV-ELLIPSOID-ENH-001", ellipsoid_chunk_, ellipsoid_doc)

    prism_chunk_ = prism_chunk(lat, lon, 490.0, 0.001, 30.0)
    prism_doc = presence(_tuple(prism_chunk_))
    _write(
        "REV-PRISM-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A gs:Prism over the exact "
        f"same footprint as REV-CONTAINED-POLYGON-ENH-001's gml:Polygon "
        f"around {hno} {street} {postyp}, {city}, extruded from Z=490 to "
        "Z=520. No provisioned SSAP carries an altitude, so the vertical "
        "test is skipped once the footprint test passes: a Prism is a "
        "Polygon plus a vertical extent that changes nothing about which "
        "candidates are returned on this data. Expected: 200, 54 "
        "candidates, all contained=True — the same set "
        "REV-CONTAINED-POLYGON-ENH-001 returns, down from the 154 the flat "
        "GCS_REVERSE_SEARCH_RADIUS_M alone would retrieve.",
        prism_doc,
    )
    _narrowing_demonstrated("REV-PRISM-ENH-001", prism_chunk_, prism_doc)

    arcband_chunk_ = arcband_chunk(lat, lon, 50.0, 200.0, 0.0, 90.0)
    arcband_doc = presence(_tuple(arcband_chunk_))
    _write(
        "REV-ARCBAND-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A gs:ArcBand — inner "
        f"radius 50 m, outer radius 200 m, a 90° arc from due north — "
        f"centred on {hno} {street} {postyp}, {city}'s own SSAP point. The "
        "inner radius puts that centre point, and every real address within "
        "50 m of it in any direction, inside the annulus's hole, so they "
        "are NOT contained; real address points 50-200 m out within the "
        "quarter-annulus are. This is the one shape that excludes "
        "candidates nearer the query origin than ones it keeps — the "
        "nearest contained candidate sits 51.6 m out. Expected: 200, 59 "
        "candidates, all contained=True, down from the 202 the flat "
        "GCS_REVERSE_SEARCH_RADIUS_M alone would retrieve.",
        arcband_doc,
    )
    _narrowing_demonstrated("REV-ARCBAND-ENH-001", arcband_chunk_, arcband_doc)

    written = {p.stem for p in INPUTS_DIR.glob("*.xml")}
    missing = {c.id for c in CASES} - written
    if missing:
        raise AssertionError(f"manifest.py declares cases build() never wrote: {sorted(missing)}")
    print(f"Wrote {len(written)} fixture(s) to {INPUTS_DIR}")


if __name__ == "__main__":
    build()
