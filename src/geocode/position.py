"""§7 — position derivation from a matched GIS feature.

Three rungs, and the rung determines the shape of the answer as much as its
precision (§3.3):

    rung 1  SSAP           the address point's own position
    rung 2  RCL + HNO      interpolated along the segment, set back off it
    rung 3  RCL, no HNO    no position at all — §7.4 returns the line itself

Rung 3 is why this module returns positions and not answers. Collapsing a
street-level match to a point would invent precision the match does not have,
so the whole-segment case has nothing for this module to compute and is handled
in response_assembly.py, which returns the geometry as the answer.

WHAT THIS MODULE DOES NOT DECIDE

Which record matched, and how well, is §6's job. This module is handed a record
and derives a position from it; it never re-scores, re-ranks, or reconsiders.
The one thing it can refuse is a record it cannot derive a position from at
all, which it does by returning None rather than raising — a candidate that
cannot be located is a candidate the caller drops, not an error condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.engine import geometry
from src.engine.models import (
    LocationType,
    Position,
    RclGisRecord,
    Side,
    SsapGisRecord,
)

# ---------------------------------------------------------------------------
# Rung 1 — SSAP
# ---------------------------------------------------------------------------

def ssap_position(record: SsapGisRecord) -> Optional[Position]:
    """The address point's position (§7.1, decision 55).

    Delegates to the record itself, which resolved this when the row became a
    candidate. Position comes from the shape geometry on every axis: X and Y
    from the geometry, Z from the geometry where it survives the non-zero test
    and from nowhere else. A zero geometry Z leaves the answer 2D at EPSG:4326;
    the Altitude and Elevation columns are not consulted.

    None where the record has no usable geometry — decision 55 makes that a
    record that cannot be returned as a located match, not one to repair from
    the attribute columns.
    """
    return record.position


# ---------------------------------------------------------------------------
# Rung 2 — RCL interpolation
# ---------------------------------------------------------------------------

#: Parity tokens as the provisioned RoadCenterLine layer spells them, counted
#: across data/data.gpkg: E 12,044 / O 6,453 / Z 1,196 / B 10 on the left,
#: near-mirrored on the right. Z means the side carries no addresses at all,
#: which is a stronger statement than an absent value and is honoured as one.
PARITY_EVEN = "E"
PARITY_ODD = "O"
PARITY_BOTH = "B"
PARITY_NONE = "Z"


@dataclass(frozen=True, slots=True)
class SideRange:
    """One side's asserted address range."""

    side: Side
    low: int
    high: int
    parity: Optional[str]

    @property
    def is_zero_length(self) -> bool:
        """From equals To — the side asserts exactly one address and says
        nothing about where along the block it sits (decision 48)."""
        return self.low == self.high

    def contains(self, house_number: int) -> bool:
        return self.low <= house_number <= self.high

    def parity_admits(self, house_number: int) -> bool:
        """Whether this side's parity field is consistent with a number.

        Consulted only to choose between two sides that both assert the number
        (decision 49). It never blocks a match on its own: a side marked even
        whose range is 100-101 is a GIS data-quality defect for the SI to fix,
        and the asserted range governs.
        """
        token = (self.parity or "").strip().upper()[:1]
        if token == PARITY_EVEN:
            return house_number % 2 == 0
        if token == PARITY_ODD:
            return house_number % 2 == 1
        return True


def side_ranges(record: RclGisRecord) -> list[SideRange]:
    """Both sides' ranges, skipping sides that assert nothing.

    A side is skipped when either endpoint is null (there is no range to
    interpolate across) or when its parity is Z, which the provisioned data
    uses to say the side carries no addresses.
    """
    source = record.source
    out: list[SideRange] = []
    for side, low, high, parity in (
        (Side.LEFT, source.FromAddr_L, source.ToAddr_L, source.Parity_L),
        (Side.RIGHT, source.FromAddr_R, source.ToAddr_R, source.Parity_R),
    ):
        if low is None or high is None:
            continue
        if (parity or "").strip().upper()[:1] == PARITY_NONE:
            continue
        out.append(SideRange(side, min(int(low), int(high)), max(int(low), int(high)), parity))
    return out


def select_side(record: RclGisRecord, house_number: int) -> Optional[SideRange]:
    """Which side of the segment a house number belongs to (§7.2, decision 49).

    The asserted range decides membership; parity decides only between two
    sides that both claim the number. A number no side asserts returns None,
    which drops the match to rung 3 rather than forcing it onto a side.
    """
    claiming = [r for r in side_ranges(record) if r.contains(house_number)]
    if not claiming:
        return None
    if len(claiming) == 1:
        return claiming[0]

    by_parity = [r for r in claiming if r.parity_admits(house_number)]
    if len(by_parity) == 1:
        return by_parity[0]

    # Both sides assert the number and parity does not separate them. The data
    # is self-contradictory; the left side is taken so the result is at least
    # deterministic, and §14.1's round trip stays stable across calls.
    return claiming[0]


@dataclass(frozen=True, slots=True)
class PathFrame:
    """The along-track frame a segment's address range is laid out on.

    This exists so that §7.2's forward interpolation and §11.2's reverse
    inversion cannot drift apart. Both directions obtain the frame from this
    one function and do arithmetic inside it; §14.1's round-trip consistency
    then holds by construction rather than by two implementations agreeing.

    `start_m` is where the range's low address sits along the path and
    `usable_m` is the length the range compresses onto. Where the margin does
    not participate — a zero-length range (decision 48) or a segment shorter
    than twice the margin (decision 56) — `margin_applied` is False and the
    answer is the midpoint in both directions.
    """

    vertices: list
    total_m: float
    start_m: float
    usable_m: float
    margin_applied: bool

    @property
    def midpoint_m(self) -> float:
        return self.total_m / 2.0


def path_frame(
    record: RclGisRecord,
    side: "SideRange",
    *,
    endpoint_margin_m: float,
) -> Optional[PathFrame]:
    """Build the shared along-track frame, or None where the segment is unusable.

    Refuses a multi-part segment (decision 53) and a segment with no length.
    The margin (decision 30) trims GCS_RCL_ENDPOINT_MARGIN_M off each end so
    the range compresses onto the shortened path, except in the two cases
    decisions 48 and 56 exclude.
    """
    if record.is_multipart or record.geometry is None:
        return None
    try:
        vertices = geometry.vertices_of(record.geometry)
    except ValueError:
        return None

    total_m = geometry.length_m(vertices)
    if total_m <= 0:
        return None

    usable_m = total_m - 2 * endpoint_margin_m
    margin_applied = not side.is_zero_length and usable_m > 0

    return PathFrame(
        vertices=vertices,
        total_m=total_m,
        start_m=endpoint_margin_m if margin_applied else 0.0,
        usable_m=usable_m if margin_applied else 0.0,
        margin_applied=margin_applied,
    )


@dataclass(frozen=True, slots=True)
class InterpolatedPosition:
    """A rung-2 result, with the working shown.

    `fraction` and `distance_along_m` are kept because §11.2 inverts exactly
    this walk, and §14.1 requires the two directions traverse the same path.
    """

    position: Position
    side: SideRange
    fraction: float
    distance_along_m: float
    margin_applied: bool
    location_type: LocationType = LocationType.INTERPOLATED_POINT


def interpolate(
    record: RclGisRecord,
    house_number: int,
    *,
    offset_m: float,
    endpoint_margin_m: float,
) -> Optional[InterpolatedPosition]:
    """Interpolate a house number onto a centerline segment (§7.2, §7.3).

    Proportional to address number, walked along the segment's actual vertex
    geometry, then set back perpendicular off the centerline on the matched
    side. Returns None where the segment cannot carry the number — no side
    asserts it, the geometry is unusable, or the segment is multi-part
    (decision 53, which declines to guess a traversal order).

    The endpoint margin (decision 30) trims GCS_RCL_ENDPOINT_MARGIN_M off each
    end before interpolating, so the full range compresses onto the shortened
    path: the first address lands at the margin-in point rather than at the
    true segment start. It exists because §7.3's perpendicular direction is
    unstable near a joint, and excluding that geometry avoids ever deriving an
    offset from it.

    Two cases bypass the margin, both because the position they produce is
    nowhere near an endpoint:

      * a zero-length range (From equals To), which returns the segment
        midpoint (decision 48);
      * a segment shorter than twice the margin, where trimming would leave no
        usable path at all (decision 56). The midpoint is returned for the same
        reason decision 48 gives — it bounds the worst-case error at half the
        segment, which is small precisely because the segment is short. No
        proportional shrink and no untrimmed interpolation is attempted: the
        first would invent a second rule with its own constant, the second
        would reintroduce the unstable-perpendicular-offset problem near joints
        that the margin exists to avoid.
    """
    side = select_side(record, house_number)
    if side is None:
        return None

    frame = path_frame(record, side, endpoint_margin_m=endpoint_margin_m)
    if frame is None:
        return None

    if frame.margin_applied:
        fraction = (house_number - side.low) / (side.high - side.low)
        fraction = min(1.0, max(0.0, fraction))
        distance_along_m = frame.start_m + fraction * frame.usable_m
    else:
        fraction = 0.5
        distance_along_m = frame.midpoint_m

    vertices = frame.vertices
    margin_applied = frame.margin_applied
    lon, lat, _ = geometry.interpolate_m(vertices, distance_along_m)
    azimuth = geometry.azimuth_at_m(vertices, distance_along_m)
    offset_lon, offset_lat = geometry.offset_perpendicular(
        lon, lat, azimuth, offset_m, to_left=side.side is Side.LEFT
    )

    # No Z, deliberately, and not because the geometry lacks one. The only Z
    # available here is road-surface elevation, and the offset above has just
    # moved the position horizontally off the road onto a parcel, where that
    # value is no longer the height of anything. Spec Appendix C.4 R1.
    return InterpolatedPosition(
        position=Position(longitude=offset_lon, latitude=offset_lat, altitude=None),
        side=side,
        fraction=fraction,
        distance_along_m=distance_along_m,
        margin_applied=margin_applied,
    )


# ---------------------------------------------------------------------------
# Rung 3 — the whole segment
# ---------------------------------------------------------------------------

def segment_geometry(record: RclGisRecord):
    """The segment's own line geometry — the rung-3 answer (§7.4, decision 30).

    Returned rather than collapsed to a point. There is no house number to
    interpolate, so there is no basis to choose a position along the line, and
    the line is itself the honest representation of what is known. Multi-part
    segments are refused here too: returning one would hand the wire layer a
    geometry whose traversal order decision 53 declines to define.
    """
    if record.geometry is None or record.is_multipart:
        return None
    return record.geometry
