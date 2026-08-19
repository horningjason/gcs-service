"""Generates tests/regression/inputs/*.xml from data/data.gpkg.

This script is committed; its OUTPUT is not (tests/regression/inputs/ is
gitignored — "may contain real address data"). The addresses and coordinates
below are never hardcoded here: every fixture is discovered at generation
time by querying whatever GeoPackage GCS_GPKG_PATH points at, by SHAPE of
condition (an exact address point, an ambiguous same-address pair, a rural
RCL segment far from any address point, ...) rather than by name. Point this
at a different jurisdiction's export and it produces a different, still
sensible, fixture set.

Run once after cloning (or whenever data.gpkg changes):

    python -m tests.regression.build_inputs

It is idempotent — re-running overwrites inputs/ with fresh discoveries from
whatever data is currently loaded. seed.py calls this automatically when
inputs/ is empty (mirroring how it auto-seeds golden/ on a first run), but
does not re-run it once files exist, for the same "don't silently reset the
baseline" reason golden files are never casually regenerated.
"""

from __future__ import annotations

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
    *, country="US", a1="ND", a2, a3, rd, sts, hno=None, pod=None, unit_value=None
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


# ---------------------------------------------------------------------------
# Discovery — find real records satisfying a condition, never by name
# ---------------------------------------------------------------------------

class Fixtures:
    """One load of data.gpkg, then a set of condition-based lookups."""

    def __init__(self, gpkg_path: str):
        self.ssap = gpd.read_file(gpkg_path, layer="SiteStructureAddressPoint")
        self.rcl = gpd.read_file(gpkg_path, layer="RoadCenterLine")
        self.ssap = self.ssap[self.ssap["Add_Number"].notna() & (self.ssap["Add_Number"] > 0)]
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
    #    Only a street genuinely absent from the SSAP layer forces rung-3. --
    def rcl_only_street(self):
        city = self.home_city()
        ssap_names = set(self.ssap["St_Name"])
        segs = self.rcl[
            (self.rcl["A3_L"] == city) & ~self.rcl["St_Name"].isin(ssap_names)
            & self.rcl["St_Name"].notna()
        ]
        if len(segs) == 0:
            raise LookupError(f"no SSAP-free RCL street found in {city!r}")
        return segs.sort_values("NGUID").iloc[0]

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
    quiet_pod = _pos_direction(quiet)

    def quiet_civic(**overrides) -> str:
        fields = dict(a2=quiet_county, a3=quiet_city, rd=quiet_street, sts=quiet_postyp,
                      pod=quiet_pod)
        fields.update(overrides)
        return civic_chunk(**fields)

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
        f"{hno} {street} {postyp}, {city}, {county} with one bogus element "
        f"the schema does not declare -> 454 schema validation failure, "
        f"not 468 (§4.1: 468 asserts a search was performed).",
        presence(_tuple(exact_civic().replace(
            "</ca:civicAddress>", "<ca:BOGUS>x</ca:BOGUS></ca:civicAddress>"
        ))),
    )
    _write(
        "ADM-WRONG-PROFILE-GEO-001",
        "POST to /Gcs/v1/Geocode with a geodetic chunk instead of a civic "
        "one. Schema-valid PIDF-LO, wrong profile for this operation -> 468, "
        "not 454 (§4.3 — no separate profile gate; the elected location just "
        "fails the chunk check).",
        presence(_tuple(point_chunk(lat, lon))),
    )
    _write(
        "ADM-WRONG-PROFILE-CIVIC-001",
        "POST to /Gcs/v1/ReverseGeocode with a civic chunk instead of a "
        f"geodetic one ({hno} {street} {postyp}, {city}). -> 468 (§4.3).",
        presence(_tuple(exact_civic())),
    )
    _write(
        "ADM-NO-LOCATION-001",
        "POST to /Gcs/v1/Geocode. A well-formed, schema-valid presence "
        "document whose tuple carries <status> with no <gp:geopriv> at all "
        "-> 468, not 454 (decision 102 — nothing convertible, but the "
        "request is not malformed).",
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
        f"{city}. RFC 5491 Rule #8 elects the device location regardless of "
        "document order (§4.2) -> locationCount=2, candidates reflect the "
        "device's address.",
        multi_doc,
    )
    _write(
        "ADM-MULTI-LOC-STRICT-001",
        "The same two-location document as ADM-MULTI-LOC-ENH-001, POSTed to "
        "the strict /Gcs/v1/Geocode instead. i3 gives no field for the "
        "discard -> no locationCount in the body, only the elected device's "
        "converted result (§4.2, decision 50).",
        multi_doc,
    )
    _write(
        "ADM-NONNUMERIC-COORD-001",
        "POST to /Gcs/v1/ReverseGeocode. gml:pos is a doubleList; "
        '"north west" fails the XSD before the wire layer ever reads it '
        "-> 454 (§4.1).",
        presence(_tuple(
            '<gml:Point xmlns:gml="http://www.opengis.net/gml">'
            "<gml:pos>north west</gml:pos></gml:Point>"
        )),
    )
    _write(
        "ADM-SPHERE-UNREADABLE-001",
        "POST to /Gcs/v1/ReverseGeocode. A gs:Sphere with a 2D centre passes "
        "the XSD (gml:pos does not constrain ordinate count) but is not a "
        "readable solid -> 454, 'could not be read' (§4.1, decision 55).",
        presence(_tuple(sphere_chunk(lat, lon, 50))),
    )
    _write(
        "ADM-JSON-BODY-001",
        "POST to /Gcs/v1/Geocode with Content-Type: application/json, body "
        "the XML quoted as a JSON string (the normative YAML's other "
        f"declared body shape, §4.1). Same {hno} {street} {postyp}, {city} "
        "address as FWD-SSAP-EXACT-001 -> 200.",
        presence(_tuple(exact_civic())),
    )

    # -- FWD -------------------------------------------------------------
    exact_doc = presence(_tuple(exact_civic()))
    exact_comment = (
        f"POST to {{TARGET}}. {hno} {street} {postyp}, {city}, {county} is a "
        "real SiteStructureAddressPoint -> rung-1 exact address-point match."
    )
    _write("FWD-SSAP-EXACT-001", exact_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Strict interface: 200, gml:Point.", exact_doc)
    _write("FWD-SSAP-EXACT-ENH-001", exact_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Enhanced interface: 200, matchScore/locationType/confidence/matchType "
           "on the ranked candidate.", exact_doc)

    interp_doc = presence(_tuple(civic_chunk(
        a2=county, a3=city, rd=interp_street, sts=postyp, hno=interp_hno,
    )))
    interp_comment = (
        f"POST to {{TARGET}}. {interp_hno} {interp_street} {postyp}, {city} is "
        "NOT a SiteStructureAddressPoint but falls inside a RoadCenterLine "
        "segment's address range -> rung-2 interpolation (§7.2)."
    )
    _write("FWD-RCL-INTERP-001", interp_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Strict: 200, gml:Point.", interp_doc)
    _write("FWD-RCL-INTERP-ENH-001", interp_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Enhanced: 200, locationType=INTERPOLATED_POINT.", interp_doc)

    _write(
        "FWD-STREET-ONLY-001",
        f"POST to /Gcs/v1/Geocode. {quiet_street} {quiet_postyp}, {quiet_city} "
        "with no house number -> rung-3 street-level match, gml:LineString "
        "not a Point (§7.4, decision 30). There is no Gate 1 (§5): a "
        "street-level query is accepted and answered, not rejected. This "
        "street carries no SiteStructureAddressPoint at all — deliberately: "
        "§6.2 has no progressive filter, so on a street that DOES have "
        "address points, dropping HNO doesn't narrow anything and every "
        "point on it still scores 100 (Add_Number isn't even a compared "
        "term once unpopulated — decision 66), which beats rung-3 outright "
        "(decision 70) and usually spans past GCS_AMBIGUITY_TOLERANCE_M into "
        "468 instead. Only a street absent from the SSAP layer forces a "
        "clean rung-3 answer on real data.",
        presence(_tuple(quiet_civic(hno=None))),
    )
    _write(
        "FWD-NOMATCH-001",
        "POST to /Gcs/v1/Geocode. A street name that does not exist "
        f"anywhere in the loaded GIS data, in the real jurisdiction {city}, "
        "{county} -> no candidate clears GCS_MIN_MATCH_SCORE -> 468 "
        "(§6.4).".format(city=city, county=county),
        presence(_tuple(civic_chunk(
            a2=county, a3=city, rd="Nonexistent Fictional", sts="Trail", hno=1,
        ))),
    )
    _write(
        "FWD-GAP-HNO-001",
        f"POST to /Gcs/v1/Geocode. {gap_hno} {street} {postyp}, {city} names "
        "a real street, but that specific house number falls between two "
        "RoadCenterLine segments' address ranges — covered by neither, so "
        "rung-2 interpolation cannot place it. On real data this degrades "
        "gracefully to the rung-3 street-level LineString (§5's 'adjacent "
        "case' — an HNO submitted, no address-level match, but the street "
        "matches), the same outcome as an unparseable HNO (decision 63) — "
        "not the harder 468 §6.4 describes for a street with no candidate "
        "at all. Distinct from FWD-NOMATCH-001, where the street itself "
        "doesn't exist.",
        presence(_tuple(civic_chunk(
            a2=county, a3=city, rd=street, sts=postyp, hno=gap_hno,
        ))),
    )

    ambig_doc = presence(_tuple(pair_civic(pair0_a, with_unit=False)))
    ambig_comment = (
        f"POST to {{TARGET}}. {int(pair0_a['Add_Number'])} {pair0_a['St_Name']} "
        f"{pair0_a['St_PosTyp']}, {pair0_a['A3']} resolves to two distinct "
        "SSAP candidates (different UnitValue) sharing one parcel — the "
        "legitimate multi-candidate case §6.3 (Session 2) exists for, not a "
        "data-hygiene duplicate. On real statewide data, §6.2's no-progressive-"
        f"filter rule (decision 82 — no A1/Country gate) also lets other "
        f"'{pair0_a['Add_Number']} {pair0_a['St_Name']} *' addresses "
        "elsewhere in the state (different STS/A3, same house number, "
        "fuzzy-similar street name) clear GCS_MIN_MATCH_SCORE and join the "
        "candidate set too."
    )
    _write("FWD-AMBIG-MERGE-001", ambig_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Strict interface: with the surviving candidates spanning far "
           "beyond GCS_AMBIGUITY_TOLERANCE_M, this is 468 (§6.3), not a "
           "centroid merge — the honest outcome once the candidate set isn't "
           "just the two intended units.", ambig_doc)
    _write("FWD-AMBIG-CANDIDATES-ENH-001",
           ambig_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Enhanced interface: 200, every surviving candidate ranked and "
           "scored on its merits — no merge, no averaging, no tolerance gate "
           "(decision 27) — so the far-flung matches are visible rather than "
           "collapsed away.", ambig_doc)
    _write(
        "FWD-UNIT-DISAMBIG-001",
        f"POST to /Gcs/v1/Geocode. The same address as FWD-AMBIG-MERGE-001, "
        f"but with UnitValue={pair0_a['UnitValue']!r} supplied. Decision 75 "
        "gates out the OTHER unit at this same parcel (differing UnitValue), "
        "but not the far-flung same-house-number candidates elsewhere in the "
        "state that carry no UnitValue at all to differ on — so this still "
        "lands on 468, not a clean single-record resolution. A real "
        "regression pin on that interaction, not the tidy disambiguation the "
        "name suggests in isolation.",
        presence(_tuple(pair_civic(pair0_a, with_unit=True))),
    )
    _write(
        "FWD-AMBIG-BISMARCK-ENH-001",
        f"POST to /Gcs/v1/GeocodeEnhanced. A second, independent ambiguous "
        f"pair — {int(pair1_a['Add_Number'])} {pair1_a['St_Name']} "
        f"{pair1_a['St_PosTyp']}, {pair1_a['A3']} — queried without a unit, "
        "for a second real-data instance of §6.3's merge case distinct from "
        "FWD-AMBIG-*-001's address.",
        presence(_tuple(pair_civic(pair1_a, with_unit=False))),
    )

    dropped_doc = presence(_tuple(quiet_civic(hno="not-a-number")))
    dropped_comment = (
        f"POST to {{TARGET}}. {quiet_street} {quiet_postyp}, {quiet_city} with "
        "an HNO that will not reduce to a non-negative integer (decision 63) "
        "— the element is dropped, not rejected; the request degrades to a "
        "rung-3 street-level match."
    )
    _write("FWD-DROPPED-HNO-ENH-001",
           dropped_comment.format(TARGET="/Gcs/v1/GeocodeEnhanced") +
           " Enhanced: 200, droppedElements reports ca:HNO.", dropped_doc)
    _write("FWD-DROPPED-HNO-STRICT-001",
           dropped_comment.format(TARGET="/Gcs/v1/Geocode") +
           " Strict: 200, gml:LineString, no field to report the drop.", dropped_doc)

    _write(
        "FWD-GEOCODED-PLACEMENT-ENH-001",
        f"POST to /Gcs/v1/GeocodeEnhanced. {int(placement['Add_Number'])} "
        f"{placement['St_Name']} {placement['St_PosTyp']}, {placement['A3']} "
        "is a real SSAP whose Placement is 'Geocoding' rather than "
        "'Structure'/'Parcel' — exercises decision 83's "
        "GCS_GEOCODED_PLACEMENT_PENALTY path on real data.",
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
        f"{street} {postyp}, {city} (see FWD-SSAP-EXACT-001) — reversing it "
        "should hand that same address back."
    )
    _write("REV-POINT-SSAP-001", point_comment.format(TARGET="/Gcs/v1/ReverseGeocode") +
           " Strict: 200, civicAddress.", point_doc)
    _write("REV-POINT-SSAP-ENH-001",
           point_comment.format(TARGET="/Gcs/v1/ReverseGeocodeEnhanced") +
           " Enhanced: 200, distanceMeters~=0, houseNumberSynthesised=False.", point_doc)

    iso_doc = presence(_tuple(point_chunk(iso_lat, iso_lon)))
    iso_comment = (
        "POST to {TARGET}. A point on a RoadCenterLine segment farther from "
        "any SiteStructureAddressPoint than 1.5x GCS_REVERSE_SEARCH_RADIUS_M "
        "— no address point can win on tier+distance (§10.3), so the house "
        "number must be synthesised by inverting §7.2's interpolation (§11.2)."
    )
    _write("REV-RCL-SYNTH-HNO-001", iso_comment.format(TARGET="/Gcs/v1/ReverseGeocode") +
           " Strict: 200, civicAddress with a synthesised HNO.", iso_doc)
    _write("REV-RCL-SYNTH-HNO-ENH-001",
           iso_comment.format(TARGET="/Gcs/v1/ReverseGeocodeEnhanced") +
           " Enhanced: 200, houseNumberSynthesised=True.", iso_doc)

    _write(
        "REV-CIRCLE-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A 100 m gs:Circle around "
        f"{hno} {street} {postyp}, {city} instead of a bare gml:Point — "
        "§9's non-Point shapes and §10.6's extent-damping term.",
        presence(_tuple(circle_chunk(lat, lon, 100))),
    )
    _write(
        "REV-POLYGON-001",
        f"POST to /Gcs/v1/ReverseGeocode. A small gml:Polygon around {hno} "
        f"{street} {postyp}, {city} — §9's Polygon shape on the strict "
        "interface.",
        presence(_tuple(polygon_chunk(lat, lon, half_deg=0.0004))),
    )
    _write(
        "REV-ELLIPSE-001",
        f"POST to /Gcs/v1/ReverseGeocode. A gs:Ellipse around {hno} {street} "
        f"{postyp}, {city} — one of the less-common RFC 5491 §5 shapes "
        "(§9, decision 37).",
        presence(_tuple(ellipse_chunk(lat, lon, 150, 80, 30))),
    )
    _write(
        "REV-SPHERE-VALID-001",
        f"POST to /Gcs/v1/ReverseGeocode. A gs:Sphere with a 3D centre "
        f"(readable, unlike ADM-SPHERE-UNREADABLE-001's 2D one) around {hno} "
        f"{street} {postyp}, {city} -> 200.",
        presence(_tuple(sphere_chunk(lat, lon, 50, z=500))),
    )
    _write(
        "REV-NOMATCH-OPENWATER-001",
        "POST to /Gcs/v1/ReverseGeocode. A point well outside this dataset's "
        "coverage entirely -> nothing falls within "
        "GCS_REVERSE_SEARCH_RADIUS_M -> 468, not a distant address (§12.3).",
        presence(_tuple(point_chunk(far_lat, far_lon))),
    )
    _write(
        "REV-CROSSCOUNTY-001",
        f"POST to /Gcs/v1/ReverseGeocode. The coordinate of a real SSAP in "
        f"{cross['A2']} ({cross['A3']}), a different jurisdiction than "
        f"{county} ({city}) where FWD-SSAP-EXACT-001 and most other "
        "fixtures sit — admin elements (A2/A3) must be sourced from the "
        "matched record's own fields, not a boundary polygon (§11.3), so "
        "this must come back correctly attributed to its own county.",
        presence(_tuple(point_chunk(float(cross["Latitude"]), float(cross["Longitude"])))),
    )
    _write(
        "REV-DUPLICATE-TIEBREAK-001",
        f"POST to /Gcs/v1/ReverseGeocode. The coordinate of "
        f"{int(dup['Add_Number'])} {dup['St_Name']} {dup['St_PosTyp']}, "
        f"{dup['A3']}, where the source data carries several SSAP records "
        "with identical attributes but distinct NGUIDs — a data-hygiene "
        "defect out of scope for merging (§6.3, Session 2), but the "
        "response must still be a single, deterministic civic answer.",
        presence(_tuple(point_chunk(float(dup["Latitude"]), float(dup["Longitude"])))),
    )
    _write(
        "REV-CONTAINED-POLYGON-ENH-001",
        f"POST to /Gcs/v1/ReverseGeocodeEnhanced. A gml:Polygon clearly "
        f"enclosing {hno} {street} {postyp}, {city}'s SSAP point -> "
        "contained=True, in contrast to REV-POINT-SSAP-ENH-001's Point query "
        "(a Point has no area, so contained=False there) (§10.3).",
        presence(_tuple(polygon_chunk(lat, lon, half_deg=0.001))),
    )

    written = {p.stem for p in INPUTS_DIR.glob("*.xml")}
    missing = {c.id for c in CASES} - written
    if missing:
        raise AssertionError(f"manifest.py declares cases build() never wrote: {sorted(missing)}")
    print(f"Wrote {len(written)} fixture(s) to {INPUTS_DIR}")


if __name__ == "__main__":
    build()
