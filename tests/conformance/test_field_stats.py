"""§6.5/§10.6 deployment-measured discriminative weight (src/gis/field_stats.py).

Covers the minimum-population floor (decision 68): a field measured against
too thin a sample must read as unmeasured (factor 1.0) rather than trusting a
computed max_frequency that a handful of observations cannot support.
"""

from __future__ import annotations

from src.gis import field_stats
from src.gis.records import RCLRecord, SSAPRecord


def _ssap(**kwargs) -> SSAPRecord:
    kwargs.setdefault("fid", 1)
    return SSAPRecord(**kwargs)


def _rcl(**kwargs) -> RCLRecord:
    kwargs.setdefault("fid", 1)
    return RCLRecord(**kwargs)


def test_below_floor_reads_unmeasured_regardless_of_skew():
    """5 identical values is a real 0% max_frequency complement, but the
    sample is far below _MIN_POPULATION — it must read 1.0, not 0.0."""
    ssap = [_ssap(fid=i, St_Name="MAIN ST") for i in range(5)]
    field_stats.recompute(ssap, [])

    assert field_stats.ssap_factor("St_Name") == 1.0
    factor, n = field_stats.report()["ssap"]["St_Name"]
    assert factor == 1.0
    assert n == 5


def test_at_or_above_floor_computes_the_real_factor():
    """30+ populated observations with a genuine skew is unaffected by the
    floor: the computed 1 - max_frequency value is used as-is."""
    ssap = [_ssap(fid=i, St_Name="MAIN ST") for i in range(25)]
    ssap += [_ssap(fid=100 + i, St_Name="ELM ST") for i in range(5)]
    field_stats.recompute(ssap, [])

    factor, n = field_stats.report()["ssap"]["St_Name"]
    assert n == 30
    assert factor == 1.0 - (25 / 30)
    assert field_stats.ssap_factor("St_Name") == factor


def test_report_population_is_the_true_count_when_floor_fires():
    """A thin field's reported n must be its real small count, not 0 and not
    the threshold value — the report tool needs the true number to tell
    "thin" apart from "zero" apart from "measured"."""
    ssap = [_ssap(fid=i, Place_Type="RESIDENCE") for i in range(7)]
    field_stats.recompute(ssap, [])

    factor, n = field_stats.report()["ssap"]["Place_Type"]
    assert n == 7
    assert factor == 1.0


def test_zero_observations_still_reads_unmeasured():
    """The n == 0 case is the floor's smallest case, not a separate branch —
    confirm it still behaves as before."""
    field_stats.recompute([], [])

    assert field_stats.ssap_factor("St_Name") == 1.0
    factor, n = field_stats.report()["ssap"]["St_Name"]
    assert factor == 1.0
    assert n == 0


def test_rcl_pooled_field_below_floor_reads_unmeasured():
    """RCL A4 pooled across L/R sides: a handful of populated sides is still
    below the floor even though two columns feed the same logical element."""
    rcl = [_rcl(fid=i, A4_L="RURAL", A4_R=None) for i in range(3)]
    field_stats.recompute([], rcl)

    factor, n = field_stats.report()["rcl"]["A4"]
    assert n == 3
    assert factor == 1.0
    assert field_stats.rcl_factor("A4") == 1.0


def test_rcl_pooled_field_at_floor_computes_the_real_factor():
    rcl = [_rcl(fid=i, A4_L="RURAL", A4_R="RURAL") for i in range(20)]
    rcl += [_rcl(fid=100 + i, A4_L="URBAN", A4_R="URBAN") for i in range(5)]
    field_stats.recompute([], rcl)

    factor, n = field_stats.report()["rcl"]["A4"]
    assert n == 50  # two sides per record
    assert factor == 1.0 - (40 / 50)
    assert field_stats.rcl_factor("A4") == factor


# ---------------------------------------------------------------------------
# ssap_population / rcl_population (decision 90) — the raw counts backing
# each factor, exposed directly so scoring.py's slot-selection tie-break
# doesn't have to go through report()'s bundled (factor, n) tuple.
# ---------------------------------------------------------------------------

def test_ssap_population_matches_the_count_report_already_exposes():
    ssap = [_ssap(fid=i, St_Name="MAIN ST") for i in range(25)]
    ssap += [_ssap(fid=100 + i, St_Name="ELM ST") for i in range(5)]
    field_stats.recompute(ssap, [])

    _factor, n = field_stats.report()["ssap"]["St_Name"]
    assert field_stats.ssap_population("St_Name") == n == 30


def test_rcl_population_is_pooled_across_sides_like_the_factor():
    rcl = [_rcl(fid=i, A4_L="RURAL", A4_R="RURAL") for i in range(20)]
    rcl += [_rcl(fid=100 + i, A4_L="URBAN", A4_R="URBAN") for i in range(5)]
    field_stats.recompute([], rcl)

    assert field_stats.rcl_population("A4") == 50  # two sides per record


def test_unmeasured_population_reads_zero_not_one():
    """Unlike the factor (which defaults to 1.0 -- "trust the editorial
    weight" per the UNLOADED AND THIN-SAMPLE DEFAULT policy), an unmeasured
    population has no meaningful nonzero default: 0 is the honest count."""
    field_stats.recompute([], [])

    assert field_stats.ssap_population("St_Name") == 0
    assert field_stats.rcl_population("A4") == 0
