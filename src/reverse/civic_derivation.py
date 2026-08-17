"""§11 — turning a matched feature into a civic address.

TWO RUNGS, TWO DIFFERENT ACTS

At an address point the GCS reports; at a centerline it computes. §11.1 reads
the civic address straight off the matched SSAP record's fields — no
derivation, no inference, no synthesis, because the record already holds a
civic address. §11.2 has no address to read and synthesises a house number by
inverting §7.2's interpolation.

THE INVERSION WALKS THE SAME PATH THE FORWARD DIRECTION WALKS

Not an equivalent path — the same one. src/geocode/position.py's `path_frame`
builds the along-track frame, and both directions do their arithmetic inside
it. §11.2 is explicit that if the two traverse different paths, §14.1's
round-trip consistency "breaks by construction rather than by data quality",
which is the kind of defect that looks like bad GIS data forever. Importing the
frame rather than rebuilding it is what makes that impossible instead of
merely unlikely.

WHAT THE SYNTHESISED NUMBER IS AND IS NOT

The inverse almost never lands on an integer. A projection at 47.3% of a
100-200 range yields 147.3, which is rounded, and rounded to the parity of the
side the origin fell on — so 147 or 149, never 148. Two guardrails apply: the
result is clamped to the segment's asserted range so it can never fall outside
what the data claims, and the parity forcing keeps it on the right side of the
street.

The result is a syntactically valid civic address that may correspond to no
structure, no parcel, and no record anywhere in the provisioned data. It is
returned anyway, tagged INTERPOLATED_POINT with a confidence ceiling of 75 and
a raw distance, because the three-field model exists precisely so a computed
answer can be labelled rather than withheld — and because "approximately 1470
Highway 83" is actionable to a dispatcher where "Highway 83, Burleigh County"
is nearly useless.

RFC 5139 gives HNO no way to mark itself approximate, so on the strict
interface a synthesised number and a validated one serialise identically. That
is a limitation of the civic schema itself rather than of i3's silence, and it
is a §16 row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.engine import geometry
from src.engine.models import (
    CivicAddress,
    LocationType,
    RclGisRecord,
    Side,
    SsapGisRecord,
)
from src.geocode import position as forward
from src.reverse.search import Hit


@dataclass(frozen=True, slots=True)
class DerivedCivic:
    """A civic address and how it was arrived at."""

    civic: CivicAddress
    tier: LocationType

    #: Set where the house number was synthesised rather than read. The
    #: enhanced interface surfaces this; the strict interface cannot (§12.1).
    house_number_synthesised: bool = False
    side: Optional[Side] = None


# ---------------------------------------------------------------------------
# §11.1 — SSAP
# ---------------------------------------------------------------------------

def from_ssap(record: SsapGisRecord) -> DerivedCivic:
    """Read the civic address off the matched record (§11.1).

    Administrative elements come from the record's own fields and the
    provisioned boundary layers are not consulted (§11.3). Point-in-polygon has
    a real claim to authority — it is how the ECRF decides jurisdiction — and is
    declined here for a reason specific to this document: a forward geocode
    matched the query against the record's own fields, so reversing must hand
    those same fields back, or a coordinate that geocoded from an address will
    not reverse to it. A record whose attribution disagrees with the polygon
    containing it is a GIS data-quality problem for the SI, not something the
    GCS corrects on the wire.

    Sparse records are returned rather than skipped (§11.4). The alternative —
    treating a record too thin to form a usable address as no answer — would
    have the GCS invent a completeness standard i3 never gave it.
    """
    return DerivedCivic(civic=record.civic(), tier=LocationType.ADDRESS_POINT)


# ---------------------------------------------------------------------------
# §11.2 — RCL
# ---------------------------------------------------------------------------

def _round_to_parity(value: float, parity_token: Optional[str], low: int, high: int) -> int:
    """Round a fractional address to the side's parity, then clamp (§11.2).

    Parity first, clamp second: forcing parity can push a value one step past
    an endpoint, and the clamp is the guardrail that must hold. Where clamping
    lands on a number of the wrong parity — a range whose endpoints contradict
    its own parity field — the asserted range wins, consistent with decision
    49's position that the range governs and a contradictory parity field is
    the SI's defect to fix.
    """
    token = (parity_token or "").strip().upper()[:1]
    nearest = int(round(value))

    if token in (forward.PARITY_EVEN, forward.PARITY_ODD):
        want_even = token == forward.PARITY_EVEN
        if (nearest % 2 == 0) != want_even:
            # Step to the nearer neighbour of the right parity.
            down, up = nearest - 1, nearest + 1
            nearest = down if abs(value - down) <= abs(value - up) else up

    return min(high, max(low, nearest))


def from_rcl(
    record: RclGisRecord,
    projection: geometry.Projection,
    *,
    endpoint_margin_m: float,
) -> Optional[DerivedCivic]:
    """Synthesise a civic address from a centerline match (§11.2, §11.3).

    The origin has already been projected onto the segment by §10.5; that
    projection carries the along-track distance and the side, so nothing is
    recomputed here. The side selects the attribute set — administrative
    elements as well as street names (§11.3) — and the along-track distance
    inverts through the shared path frame into a house number.

    Returns a street-level address with no house number where the segment
    asserts no range on the projected side. That is the reverse-side analogue
    of rung 3, and it is tiered STREET_SEGMENT so the confidence ceiling says
    so rather than the address quietly omitting a number it might have had.
    """
    side = Side.LEFT if projection.to_left else Side.RIGHT
    civic = record.civic_for_side(side)

    ranges = {r.side: r for r in forward.side_ranges(record)}
    asserted = ranges.get(side)
    if asserted is None:
        return DerivedCivic(civic=civic, tier=LocationType.STREET_SEGMENT, side=side)

    frame = forward.path_frame(record, asserted, endpoint_margin_m=endpoint_margin_m)
    if frame is None:
        return DerivedCivic(civic=civic, tier=LocationType.STREET_SEGMENT, side=side)

    if frame.margin_applied:
        fraction = (projection.distance_along_m - frame.start_m) / frame.usable_m
        fraction = min(1.0, max(0.0, fraction))
    else:
        # The forward direction returns the midpoint for any number here
        # (decisions 48 and 56), so the inverse returns the single asserted
        # number for any position — which is exactly the round-trip symmetry
        # §7.2 notes: the direction that breaks forward is the trustworthy one
        # in reverse.
        fraction = 0.0

    raw = asserted.low + fraction * (asserted.high - asserted.low)
    number = _round_to_parity(raw, asserted.parity, asserted.low, asserted.high)

    return DerivedCivic(
        civic=_with_house_number(civic, number),
        tier=LocationType.INTERPOLATED_POINT,
        house_number_synthesised=True,
        side=side,
    )


def _with_house_number(civic: CivicAddress, number: int) -> CivicAddress:
    populated = civic.populated()
    populated["Add_Number"] = number
    return CivicAddress(**populated)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def derive(hit: Hit, *, endpoint_margin_m: float) -> Optional[DerivedCivic]:
    """Derive the civic address for one ordered hit."""
    if isinstance(hit.record, SsapGisRecord):
        return from_ssap(hit.record)
    if isinstance(hit.record, RclGisRecord) and hit.projection is not None:
        return from_rcl(hit.record, hit.projection, endpoint_margin_m=endpoint_margin_m)
    return None
