"""Deployment-measured discriminative weight per civic element (spec §6.5, §10.6).

WHY THIS EXISTS

§6.5 withholds the scoring formula deliberately (Appendix C item (d)) because a
fixed weight table is a guess no available data justifies. But one part of the
problem does not need tuning against match/non-match pairs at all — it needs
only the provisioned data itself: how much can this FIELD possibly tell us
apart, in THIS deployment?

A statewide ND deployment's Country column is "US" on every row. Weighting it
alongside Street Name would let two candidates disagree on nothing and still
be scored as if Country were doing work. A2 (county) is almost never supplied
by a caller, so it drops out of scoring by simple absence (CivicAddress reads
only what was populated) — no special case needed there. A1 (state)
illustrates the general case this measurement handles: a deployment where the
field is mostly one value but genuinely varies on border parcels should
weight state disagreement more than one where the field is perfectly uniform,
and a fixed weight cannot tell those two deployments apart from a look at the
code alone. (Checked directly against the currently loaded ND export: A1 is
uniformly "ND" with zero border-parcel variation, so it reads
discriminative_factor 0.0 exactly like Country — this deployment turned out
to be the uniform case, not the mixed one the general argument describes.
Confirm whether that reflects the true deployment scope or an export that
excludes adjoining counties before relying on the mixed-case argument as a
reason this mechanism matters in practice for THIS deployment; it may still
matter for other fields or other deployments.)

THE MEASURE

discriminative_factor(field) = 1 - max_frequency(field)

max_frequency is the share of populated values held by that field's single
most common value, across the currently loaded layer. A field with one value
everywhere scores 0 (contributes nothing no matter how it's weighted
editorially). A field with many roughly-equally-common values approaches 1.
This is not a similarity measure and not a substitute for the base editorial
weights in src/engine/scoring.py (Street Name matters more than Place_Type
even in a deployment where both are highly variable) — it is a multiplier on
top of them, and the one part of the weight that is read off the data rather
than guessed.

WHEN IT IS COMPUTED

Recomputed by src/gis/provisioning.py immediately after each (re)load,
population from source or from cache alike, so a hot GIS reload picks up
new distributions without a restart. Between the process starting and the
first successful load, every factor reads as 1.0 (see UNLOADED AND
THIN-SAMPLE DEFAULT below).

RCL SIDEDNESS

RoadCenterLine carries administrative and postal elements once per side
(Country_L/Country_R, A1_L/A1_R, ...). For statistics purposes the two sides
are pooled into one distribution per logical element name: a deployment's
Country column being uniform does not depend on which side of the street a
match happens to land on, and pooling gives every sided element the same
population size as an unsided one, rather than an arbitrarily halved sample.

UNLOADED AND THIN-SAMPLE DEFAULT

A field reads discriminative_factor 1.0 — fully discriminative, i.e.
behaves like an un-adjusted fixed weight — in two cases: no observations
at all (nothing loaded yet, or this deployment's export omits the field
entirely), and fewer than _MIN_POPULATION populated observations (a
sample too thin for max_frequency to mean anything). Defaulting either
case to 0 would silently zero out scoring on thin evidence; defaulting to
1 fails toward "trust the editorial weight", which is the safer direction
for a service that must not silently degrade on sparse data.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Iterable

from src.gis.records import RCLRecord, SSAPRecord

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RCL sided -> logical element name
# ---------------------------------------------------------------------------

#: Column-name suffix pairs that pool into one logical element for statistics.
#: Kept local to this module rather than imported from src/engine/models.py:
#: that module's _RCL_SIDED_ELEMENTS maps logical name -> "{Col}_{s}" template
#: for a different purpose (reading one side's value out of a matched record),
#: and importing engine/ from gis/ would invert the layering
#: src/gis/provisioning.py's docstring already establishes (gis/ knows columns,
#: engine/ knows algorithm). The pairs themselves are the same STA-006.3 names.
_RCL_SIDED_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("Country", "Country_L", "Country_R"),
    ("A1", "A1_L", "A1_R"),
    ("A2", "A2_L", "A2_R"),
    ("A3", "A3_L", "A3_R"),
    ("A4", "A4_L", "A4_R"),
    ("A5", "A5_L", "A5_R"),
    ("AddCode", "AddCode_L", "AddCode_R"),
    ("MSAGComm", "MSAGComm_L", "MSAGComm_R"),
    ("Post_Code", "PostCode_L", "PostCode_R"),
    ("Post_Comm", "PostComm_L", "PostComm_R"),
)

#: RCL columns carrying one value for the whole segment — used as-is.
_RCL_SHARED: tuple[str, ...] = (
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
    "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod",
)

#: SSAP civic elements worth measuring. Excludes sub-address/interior fields
#: (Site, Unit, Floor, ...) — §7.5's future concern, and near-universally
#: absent in the provisioned data today, which would make every one of them
#: read as a spuriously high discriminative_factor (few observations, each
#: distinct) rather than a meaningful measurement. Revisit alongside §7.5.
_SSAP_ELEMENTS: tuple[str, ...] = (
    "Country", "A1", "A2", "A3", "A4", "A5", "AddCode",
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep",
    "St_Name", "St_PosTyp", "St_PosDir", "St_PosMod",
    "MSAGComm", "Post_Comm", "Post_Code", "PostCodeEx",
    "Place_Type",
)

#: Below this many populated observations, a field reads as unmeasured
#: (factor 1.0) rather than computing max_frequency against a sample too
#: thin to mean anything. This is a sample-size floor, defensible from
#: first principles rather than tuned against data — unlike _BASE_WEIGHTS
#: in src/engine/scoring.py, this number does not need data.gpkg to
#: justify it, only ordinary statistical judgment. 30 is a standard
#: rule-of-thumb minimum sample size; revisit if it proves too strict or
#: too loose once real deployments are observed.
_MIN_POPULATION = 30


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

def _max_frequency(values: Iterable[object]) -> tuple[float, int]:
    """max_frequency and the population size it was measured against.

    Populated values only — a null civic element is absence, not a value the
    field "has", and mixing the two would understate max_frequency for every
    mostly-populated field in proportion to how often SIs leave it blank.
    """
    counts = Counter(v for v in values if v is not None)
    n = sum(counts.values())
    if n == 0:
        return 1.0, 0  # no observations: see UNLOADED DEFAULT above
    return max(counts.values()) / n, n


def _factor(values: Iterable[object]) -> tuple[float, int]:
    max_freq, n = _max_frequency(values)
    if n < _MIN_POPULATION:
        return 1.0, n
    return 1.0 - max_freq, n


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_ssap_factors: dict[str, float] = {}
_rcl_factors: dict[str, float] = {}
_ssap_populations: dict[str, int] = {}
_rcl_populations: dict[str, int] = {}


def recompute(ssap: list[SSAPRecord], rcl: list[RCLRecord]) -> None:
    """Recompute every factor from the currently loaded layers.

    Called by src/gis/provisioning.py immediately after _ssap/_rcl are
    (re)bound — from source or from cache, the same either way, since the
    measurement only reads the resulting records and has no opinion on how
    they got there.
    """
    global _ssap_factors, _rcl_factors, _ssap_populations, _rcl_populations

    ssap_factors: dict[str, float] = {}
    ssap_pops: dict[str, int] = {}
    for element in _SSAP_ELEMENTS:
        values = (getattr(r, element, None) for r in ssap)
        factor, n = _factor(values)
        ssap_factors[element] = factor
        ssap_pops[element] = n

    rcl_factors: dict[str, float] = {}
    rcl_pops: dict[str, int] = {}
    for element, left_col, right_col in _RCL_SIDED_PAIRS:
        pooled = [
            v
            for r in rcl
            for v in (getattr(r, left_col, None), getattr(r, right_col, None))
        ]
        factor, n = _factor(pooled)
        rcl_factors[element] = factor
        rcl_pops[element] = n
    for element in _RCL_SHARED:
        values = (getattr(r, element, None) for r in rcl)
        factor, n = _factor(values)
        rcl_factors[element] = factor
        rcl_pops[element] = n

    _ssap_factors = ssap_factors
    _ssap_populations = ssap_pops
    _rcl_factors = rcl_factors
    _rcl_populations = rcl_pops

    log.info(
        "Field statistics recomputed: %d SSAP elements, %d RCL elements",
        len(ssap_factors),
        len(rcl_factors),
    )


def ssap_factor(element: str) -> float:
    """Discriminative factor for an SSAP civic element. 1.0 if unmeasured."""
    return _ssap_factors.get(element, 1.0)


def rcl_factor(element: str) -> float:
    """Discriminative factor for an RCL civic element (pooled across sides
    where the element is sided). 1.0 if unmeasured."""
    return _rcl_factors.get(element, 1.0)


def ssap_population(element: str) -> int:
    """The populated-observation count backing ssap_factor(element). 0 if
    unmeasured. Decision 90's slot-selection tie-break reads this directly —
    when two record slots compare equally well, the slot with the larger
    measured population is the more meaningful measurement of the two."""
    return _ssap_populations.get(element, 0)


def rcl_population(element: str) -> int:
    """The populated-observation count backing rcl_factor(element) (pooled
    across sides where the element is sided). 0 if unmeasured. See
    ssap_population — same role, RCL side."""
    return _rcl_populations.get(element, 0)


def report() -> dict[str, dict[str, tuple[float, int]]]:
    """Human-readable snapshot for the field-stats report tool and for logging
    at reload time — factor and population size together, since a factor
    measured against 40 records means something different from one measured
    against 400,000."""
    return {
        "ssap": {k: (v, _ssap_populations.get(k, 0)) for k, v in _ssap_factors.items()},
        "rcl": {k: (v, _rcl_populations.get(k, 0)) for k, v in _rcl_factors.items()},
    }
