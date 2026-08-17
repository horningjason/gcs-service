#!/usr/bin/env python3
"""Session 9 — does _BASE_WEIGHTS' RATIO order two already-qualifying
candidates correctly, independent of the absolute-score dilution question
Sessions 6-8 already closed?

WHAT THIS TESTS, AND WHY IT IS A DIFFERENT QUESTION FROM SESSIONS 6-8

Appendix C item (d) flags _BASE_WEIGHTS (src/engine/scoring.py) as guesses.
Sessions 6-8 asked whether reweighting could push a mismatched candidate's
ABSOLUTE matchScore below GCS_MIN_MATCH_SCORE, and kept finding it could not:
one disagreeing term sits inside a ~7-term average dominated by six
near-1.0 terms, so no weight redistribution moves the average far enough —
dilution, not a weight problem.

This script asks a narrower question the dilution finding does not answer:
given two candidates that both already clear the floor, do the current
weight RATIOS rank them correctly relative to EACH OTHER? For one query
scored against two records built from the same base address (so both share
the query-populated field set and therefore the same weighted-average
denominator), ranking reduces to the sign of
sum(w_i * (sim_i^A - sim_i^B)) — a comparison where the weight ratios do
real, undiluted work, unlike the absolute-floor question.

SCOPE — SIX FIELDS, NOT SEVEN

St_Name is excluded. decision 71/73's _street_name_qualifies gate forces
score_value to 0.0 for a record whose street name fails the
Soundex/edit-similarity threshold BEFORE the weighted average runs, so a
"confidently wrong" St_Name donor (similarity <= 0.15 to the true value)
would just re-trigger the gate rather than test the weight=30 value inside
the average. St_Name's practical role in the live weighted average is
therefore limited to near-miss typos that already survive the gate, where
similarity is already high and the term is nowhere near "confidently
wrong" — testing it with a near-miss donor would test decision 71's
qualification threshold instead, a separate settled question.

The six fields in scope, by base weight: Community (15), St_Type (12),
A2 (10), St_Dir (8), A1 (5), Country (2).

DONOR AVAILABILITY IS ITSELF A FINDING FOR A1 AND COUNTRY

A donor only qualifies if _normalized_similarity(true_value, donor_value)
— using the exact comparison the field uses in score_ssap (binary=True for
St_Dir/A1/Country) — reads <= 0.15. Checked directly against this
deployment's data.gpkg: A1 is "ND" on all 78,237 SSAP rows and Country is
"US" on all of them — zero variation, so NO in-layer donor can ever clear
the threshold for either field. Every A1 and Country decoy attempt fails
by construction here, which the report below shows rather than hides. That
is a property of this single-state export, not a bug in the donor search —
see field_stats.py's own docstring, which independently measured
discriminative_factor 0.0 for both.

METHOD

Standalone, same conventions as tools/field_stats_report.py: reads
data.gpkg directly via geopandas/pyogrio using src.gis.records.row_to_ssap,
calls src.gis.field_stats.recompute(ssap, rcl) so score_ssap's f() factors
are real measurements, never touches runtime_state or the ASGI app.

1. Sample ~250 SSAP records (seeded RNG) that have all six in-scope concept
   fields populated (community via the A3->A4->Post_Comm cascade, a street
   type slot, a street direction slot, A2, A1, Country).
2. For each sampled record R, the query is CivicAddress.from_record(R) — an
   exact copy of R's own values, so the experiment isolates "which single
   wrong field hurts more" without any query-side typo-tolerance question.
3. For each of the six fields, build ONE decoy: R with that field (or, for
   Community/St_Type/St_Dir, whichever sub-field(s) the scorer actually
   compares the query's single asserted value against) replaced by a donor
   pulled from elsewhere in the loaded layer, filtered to <= 0.15 similarity
   under the field's own comparison.
4. Score every decoy with score_ssap(query, decoy). For each of the 15
   field pairs (a, b) with base_weight(a) > base_weight(b), record whether
   decoy_b outscored decoy_a (the correct ordering — wrongness in the
   higher-weight field should cost more, i.e. score lower).

A2 SUFFIX DIAGNOSTIC (--a2-suffix-diagnostic) — A MEASUREMENT, NOT A FIX

A2's donor search fails 100% of the time here, and the reason is worth
separating from sample size: every ND county name carries the literal
suffix "County", so "Burleigh County" vs "Morton County" scores 0.267 on
edit distance for the shared suffix alone, above the 0.15 threshold, no
matter how many counties the export contains. --a2-suffix-diagnostic
re-runs the A2 donor search against values with a trailing "COUNTY" token
stripped, and reports what the failure rate and similarity distribution
would look like under that comparison.

This is EVIDENCE FOR A POSSIBLE FUTURE NORMALIZATION DECISION AND NOTHING
MORE. It does not modify _normalize_token, _normalized_similarity, or any
production path; it does not feed the pairwise ranking results above it;
and the stripping happens inside this tool's own local function. Nothing
about running it changes how the service scores anything. Do not read a
low failure rate here as "A2 is fixed" — it is "A2 WOULD become testable
IF a normalization decision were taken", which is a separate question this
tool does not answer.

NON-GOALS

No changes to src/engine/scoring.py, _BASE_WEIGHTS, src/gis/field_stats.py's
formula, or _normalize_token. No new candidate-set gates. No new tests.
Evidence-gathering only.

Usage:
    python tools/weight_ranking_sweep.py data/data.gpkg
    python tools/weight_ranking_sweep.py data/data.gpkg --seed 42 --sample-size 250
    python tools/weight_ranking_sweep.py data/data.gpkg --a2-suffix-diagnostic
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics
import sys
from collections import Counter
from pathlib import Path
from random import Random
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import scoring as scoring_mod  # noqa: E402
from src.engine.models import CivicAddress  # noqa: E402
from src.gis import field_stats  # noqa: E402
from src.gis import records as gis_records  # noqa: E402
from src.gis.records import SSAPRecord  # noqa: E402

DEFAULT_SEED = 42
DEFAULT_SAMPLE_SIZE = 250
DONOR_SIMILARITY_THRESHOLD = 0.15
TIE_EPSILON = 1e-9

#: The six in-scope fields, St_Name excluded (see module docstring).
FIELDS: tuple[str, ...] = ("Community", "St_Type", "A2", "St_Dir", "A1", "Country")


# ---------------------------------------------------------------------------
# Layer loading (mirrors tools/field_stats_report.py)
# ---------------------------------------------------------------------------

def _read_layer(gpkg_path: str, layer_name: str, converter):
    import geopandas as gpd

    gdf = gpd.read_file(gpkg_path, layer=layer_name, engine="pyogrio")
    geom_col = gdf.geometry.name
    return [converter(row, fid, geom_col) for fid, row in gdf.iterrows()]


def _distinct(records: list, column: str) -> list:
    return sorted(
        {getattr(r, column) for r in records if getattr(r, column, None) is not None}
    )


def _qualifies(r: SSAPRecord) -> bool:
    """All six in-scope concept fields resolvable."""
    comm = r.A3 or r.A4 or r.Post_Comm
    styp = r.St_PosTyp or r.St_PreTyp
    sdir = r.St_PreDir or r.St_PosDir
    return bool(comm and styp and sdir and r.A2 and r.A1 and r.Country)


# ---------------------------------------------------------------------------
# Donor selection — "confidently wrong" per the field's own comparison
# ---------------------------------------------------------------------------

SimFn = Callable[[object, object], Optional[float]]


def _sim_plain(a, b) -> Optional[float]:
    return scoring_mod._normalized_similarity(a, b)


def _sim_binary(a, b) -> Optional[float]:
    return scoring_mod._normalized_similarity(a, b, binary=True)


def _sim_type(a, b) -> Optional[float]:
    return scoring_mod._normalized_similarity(a, b, expansions=scoring_mod._TYPE_EXPANSIONS)


def _sim_dir(a, b) -> Optional[float]:
    return scoring_mod._normalized_similarity(
        a, b, expansions=scoring_mod._DIRECTIONAL_EXPANSIONS, binary=True
    )


def _strip_county_suffix(value: object) -> object:
    """DIAGNOSTIC ONLY (--a2-suffix-diagnostic). Drop a trailing "COUNTY"
    token so two ND county names compare on the part that distinguishes
    them. Deliberately a private function of this tool and NOT a change to
    src/engine/scoring.py's _normalize_token — whether the production
    normalization should learn this is an open decision, and this function
    exists to measure what it would buy, not to take it.
    """
    if not isinstance(value, str):
        return value
    token = value.strip().upper()
    if token.endswith(" COUNTY"):
        return token[: -len(" COUNTY")].strip()
    return token


def _sim_a2_suffix_stripped(a, b) -> Optional[float]:
    """DIAGNOSTIC ONLY — _sim_plain over suffix-stripped values."""
    return _sim_plain(_strip_county_suffix(a), _strip_county_suffix(b))


def _pick_donor(
    rng: Random, pool: list, true_value: object, sim_fn: SimFn
) -> tuple[Optional[object], Optional[float]]:
    """Shuffle the whole pool (this IS the resample loop — every candidate in
    the loaded layer is tried before giving up, not a fixed attempt count)
    and return the first value whose similarity to true_value, under the
    SAME comparison the field uses in scoring, is <= DONOR_SIMILARITY_THRESHOLD.

    (None, None) if nothing clears the bar — including the structural case
    where the pool has no variation at all (A1, Country in this deployment).
    """
    candidates = [v for v in pool if v != true_value]
    rng.shuffle(candidates)
    for candidate in candidates:
        sim = sim_fn(true_value, candidate)
        if sim is not None and sim <= DONOR_SIMILARITY_THRESHOLD:
            return candidate, sim
    return None, None


# ---------------------------------------------------------------------------
# Decoy construction — one per field, mirroring exactly what score_ssap
# compares for that concept
# ---------------------------------------------------------------------------

class DecoyResult:
    __slots__ = ("record", "true_repr", "decoy_repr", "sims")

    def __init__(self, record, true_repr, decoy_repr, sims):
        self.record = record
        self.true_repr = true_repr
        self.decoy_repr = decoy_repr
        self.sims = sims


def _build_community_decoy(rng: Random, record: SSAPRecord, pools: dict) -> Optional[DecoyResult]:
    value, cfield = scoring_mod._community_ssap(record)
    if cfield is None:
        return None
    donor, sim = _pick_donor(rng, pools[f"community_{cfield}"], value, _sim_plain)
    if donor is None:
        return None
    decoy = dataclasses.replace(record, **{cfield: donor})
    return DecoyResult(decoy, f"{cfield}={value!r}", f"{cfield}={donor!r}", [sim])


def _build_two_slot_decoy(
    rng: Random,
    record: SSAPRecord,
    slots: tuple[str, str],
    query_val: Optional[str],
    pool: list,
    sim_fn: SimFn,
) -> Optional[DecoyResult]:
    """St_Type and St_Dir share this shape: the query supplies ONE value
    (preferring one slot over the other), and score_ssap's _best_of_sides
    compares it against BOTH record slots that are populated, keeping the
    max. To guarantee "confidently wrong" for the whole concept, every
    populated slot must get a donor that is <=0.15 similar to the SAME
    query_val best_of_sides actually compares against — not to that slot's
    own original value, which would under-test a record where both slots
    are populated with different text.
    """
    if query_val is None:
        return None
    kwargs: dict[str, str] = {}
    true_parts: list[str] = []
    decoy_parts: list[str] = []
    sims: list[float] = []
    for slot in slots:
        slot_val = getattr(record, slot)
        if slot_val is None:
            continue
        donor, sim = _pick_donor(rng, pool, query_val, sim_fn)
        if donor is None:
            return None
        kwargs[slot] = donor
        true_parts.append(f"{slot}={slot_val!r}")
        decoy_parts.append(f"{slot}={donor!r}")
        sims.append(sim)
    if not kwargs:
        return None
    decoy = dataclasses.replace(record, **kwargs)
    return DecoyResult(decoy, ", ".join(true_parts), ", ".join(decoy_parts), sims)


def _build_single_field_decoy(
    rng: Random, record: SSAPRecord, column: str, pool: list, sim_fn: SimFn
) -> Optional[DecoyResult]:
    true_val = getattr(record, column)
    donor, sim = _pick_donor(rng, pool, true_val, sim_fn)
    if donor is None:
        return None
    decoy = dataclasses.replace(record, **{column: donor})
    return DecoyResult(decoy, f"{column}={true_val!r}", f"{column}={donor!r}", [sim])


def _build_decoy(rng: Random, record: SSAPRecord, field: str, pools: dict) -> Optional[DecoyResult]:
    if field == "Community":
        return _build_community_decoy(rng, record, pools)
    if field == "St_Type":
        query_val = record.St_PosTyp or record.St_PreTyp
        return _build_two_slot_decoy(
            rng, record, ("St_PosTyp", "St_PreTyp"), query_val, pools["st_type"], _sim_type
        )
    if field == "St_Dir":
        query_val = record.St_PreDir or record.St_PosDir
        return _build_two_slot_decoy(
            rng, record, ("St_PreDir", "St_PosDir"), query_val, pools["st_dir"], _sim_dir
        )
    if field == "A2":
        return _build_single_field_decoy(rng, record, "A2", pools["a2"], _sim_plain)
    if field == "A1":
        return _build_single_field_decoy(rng, record, "A1", pools["a1"], _sim_binary)
    if field == "Country":
        return _build_single_field_decoy(rng, record, "Country", pools["country"], _sim_binary)
    raise ValueError(field)


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gpkg_path")
    parser.add_argument("--ssap-layer", default="SiteStructureAddressPoint")
    parser.add_argument("--rcl-layer", default="RoadCenterLine")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument(
        "--a2-suffix-diagnostic",
        action="store_true",
        help="DIAGNOSTIC ONLY: also report A2 donor availability under a "
        "trailing-'County'-stripped comparison. Measures what a future "
        "normalization decision would buy; changes no production path and "
        "does not affect the ranking results.",
    )
    args = parser.parse_args()

    print(f"Reading {args.ssap_layer!r} from {args.gpkg_path} ...")
    ssap = _read_layer(args.gpkg_path, args.ssap_layer, gis_records.row_to_ssap)
    print(f"  {len(ssap)} SSAP records")

    print(f"Reading {args.rcl_layer!r} from {args.gpkg_path} ...")
    rcl = _read_layer(args.gpkg_path, args.rcl_layer, gis_records.row_to_rcl)
    print(f"  {len(rcl)} RCL records")

    field_stats.recompute(ssap, rcl)

    qualifying = [r for r in ssap if _qualifies(r)]
    frac = len(qualifying) / len(ssap) if ssap else 0.0
    print(
        f"\n{len(qualifying)} / {len(ssap)} SSAP records ({frac:.1%}) have all six "
        f"in-scope fields populated (community, street type, street direction, "
        f"A2, A1, Country)."
    )

    rng = Random(args.seed)
    sample_size = min(args.sample_size, len(qualifying))
    sample = rng.sample(qualifying, sample_size)
    print(f"Sampling {sample_size} records, seed={args.seed}.")

    pools = {
        "community_A3": _distinct(ssap, "A3"),
        "community_A4": _distinct(ssap, "A4"),
        "community_Post_Comm": _distinct(ssap, "Post_Comm"),
        "st_type": sorted(set(_distinct(ssap, "St_PosTyp")) | set(_distinct(ssap, "St_PreTyp"))),
        "st_dir": sorted(set(_distinct(ssap, "St_PreDir")) | set(_distinct(ssap, "St_PosDir"))),
        "a2": _distinct(ssap, "A2"),
        "a1": _distinct(ssap, "A1"),
        "country": _distinct(ssap, "Country"),
    }
    print("\nDonor pool sizes (distinct populated values across the full layer):")
    for key in ("community_A3", "community_A4", "community_Post_Comm", "st_type", "st_dir", "a2", "a1", "country"):
        print(f"  {key:<22} {len(pools[key])}")

    # --- score every decoy -------------------------------------------------
    achieved_sims: dict[str, list[float]] = {f: [] for f in FIELDS}
    failures: Counter[str] = Counter()
    sample_results: list[dict] = []

    for record in sample:
        query = CivicAddress.from_record(record)
        scores: dict[str, float] = {}
        meta: dict[str, DecoyResult] = {}
        for field in FIELDS:
            outcome = _build_decoy(rng, record, field, pools)
            if outcome is None:
                failures[field] += 1
                continue
            score_value, _breakdown = scoring_mod.score_ssap(query, outcome.record)
            scores[field] = score_value
            meta[field] = outcome
            achieved_sims[field].extend(outcome.sims)
        sample_results.append({"record": record, "scores": scores, "meta": meta})

    # --- donor availability --------------------------------------------------
    print("\nDonor availability (fraction of the sample where no in-layer value "
          f"cleared the <= {DONOR_SIMILARITY_THRESHOLD} threshold):")
    for field in FIELDS:
        fail_n = failures[field]
        print(f"  {field:<10} {fail_n}/{sample_size} failed ({fail_n / sample_size:.1%})")

    print("\nAchieved donor similarity distribution (should cluster near 0):")
    for field in FIELDS:
        sims = achieved_sims[field]
        if not sims:
            print(f"  {field:<10} no successful donors")
            continue
        print(
            f"  {field:<10} n={len(sims):<5} min={min(sims):.3f} "
            f"mean={statistics.mean(sims):.3f} median={statistics.median(sims):.3f} "
            f"max={max(sims):.3f}"
        )

    # --- pairwise ranking ------------------------------------------------
    fields_by_weight = sorted(FIELDS, key=lambda f: -scoring_mod._BASE_WEIGHTS[f])
    print("\nWeight order (base editorial weight, _BASE_WEIGHTS):")
    for f in fields_by_weight:
        print(f"  {f:<10} {scoring_mod._BASE_WEIGHTS[f]}")

    pairs = [
        (a, b)
        for i, a in enumerate(fields_by_weight)
        for b in fields_by_weight[i + 1 :]
    ]

    print(
        "\n"
        + "=" * 100
        + "\nPer field-pair results (a = higher weight, b = lower weight; "
        "'correct' means decoy_b outscored decoy_a)\n"
        + "=" * 100
    )

    for a, b in pairs:
        gaps: list[float] = []
        correct = tie = reversal = 0
        examples: list[tuple[dict, float, float]] = []
        for entry in sample_results:
            sa = entry["scores"].get(a)
            sb = entry["scores"].get(b)
            if sa is None or sb is None:
                continue
            gap = sb - sa  # positive = correct direction
            gaps.append(gap)
            if gap > TIE_EPSILON:
                correct += 1
            elif gap < -TIE_EPSILON:
                reversal += 1
                if len(examples) < 3:
                    examples.append((entry, sa, sb))
            else:
                tie += 1

        n = correct + tie + reversal
        header = f"\n{a} (w={scoring_mod._BASE_WEIGHTS[a]}) vs {b} (w={scoring_mod._BASE_WEIGHTS[b]})  [n={n}]"
        print(header)
        if n == 0:
            print(
                "  NO DATA — donor selection failed for at least one field on every "
                "sampled record (see donor-availability table above)."
            )
            continue
        print(
            f"  correct: {correct}/{n} ({correct / n:.1%})   "
            f"tie: {tie}/{n} ({tie / n:.1%})   "
            f"reversal: {reversal}/{n} ({reversal / n:.1%})"
        )
        print(
            f"  gap (decoy_b score - decoy_a score): mean={statistics.mean(gaps):+.2f}  "
            f"median={statistics.median(gaps):+.2f}"
        )
        for entry, sa, sb in examples:
            record = entry["record"]
            meta_a, meta_b = entry["meta"][a], entry["meta"][b]
            print(
                f"    REVERSAL example NGUID={record.NGUID}:\n"
                f"      {a}: true[{meta_a.true_repr}] -> decoy[{meta_a.decoy_repr}] "
                f"(sim={meta_a.sims}) => score={sa:.2f}\n"
                f"      {b}: true[{meta_b.true_repr}] -> decoy[{meta_b.decoy_repr}] "
                f"(sim={meta_b.sims}) => score={sb:.2f}\n"
                f"      expected score({a} wrong) < score({b} wrong); got "
                f"{sa:.2f} >= {sb:.2f}"
            )

    if args.a2_suffix_diagnostic:
        _report_a2_suffix_diagnostic(args.seed, sample, pools["a2"])

    print("\n" + "=" * 100)
    print("Done.")


def _report_a2_suffix_diagnostic(seed: int, sample: list, a2_pool: list) -> None:
    """Part 3 — is A2's 100% donor failure a normalization artifact or a
    sample-size one? Reported side by side under the production comparison
    and under a suffix-stripped one.

    Uses its OWN Random instance, seeded separately, so the main sweep's RNG
    stream above is untouched and its results stay bit-for-bit comparable to
    a run without this flag.
    """
    diag_rng = Random(seed + 1)

    print("\n" + "=" * 100)
    print("PART 3 — A2 SUFFIX DIAGNOSTIC  ***MEASUREMENT ONLY, NOT AN IMPLEMENTED CHANGE***")
    print("=" * 100)
    print(
        "  Nothing below affects the ranking results above, src/engine/scoring.py,\n"
        "  _normalize_token, or any production path. It measures what a trailing-\n"
        "  'County' normalization WOULD buy, to inform a decision not yet taken."
    )

    print(f"\n  A2 pool ({len(a2_pool)} distinct values): {', '.join(map(str, a2_pool))}")

    for label, sim_fn in (
        ("production (_normalized_similarity)", _sim_plain),
        ("DIAGNOSTIC (trailing 'County' stripped)", _sim_a2_suffix_stripped),
    ):
        failures = 0
        achieved: list[float] = []
        for record in sample:
            donor, sim = _pick_donor(diag_rng, a2_pool, record.A2, sim_fn)
            if donor is None:
                failures += 1
            else:
                achieved.append(sim)
        n = len(sample)
        print(f"\n  {label}:")
        print(f"    donor failure: {failures}/{n} ({failures / n:.1%})")
        if achieved:
            print(
                f"    achieved similarity: n={len(achieved)} min={min(achieved):.3f} "
                f"mean={statistics.mean(achieved):.3f} "
                f"median={statistics.median(achieved):.3f} max={max(achieved):.3f}"
            )
        else:
            print("    achieved similarity: no successful donors")

    print("\n  Full pairwise A2 similarity matrix (every distinct pair, both comparisons):")
    print(f"    {'value A':<20} {'value B':<20} {'production':>11} {'stripped':>10}")
    for i, a in enumerate(a2_pool):
        for b in a2_pool[i + 1 :]:
            prod = _sim_plain(a, b)
            strip = _sim_a2_suffix_stripped(a, b)
            print(
                f"    {str(a):<20} {str(b):<20} "
                f"{(prod if prod is not None else float('nan')):>11.3f} "
                f"{(strip if strip is not None else float('nan')):>10.3f}"
            )
    print(
        f"\n  Threshold is <= {DONOR_SIMILARITY_THRESHOLD}. A pair above it on the "
        "'production' column\n  cannot supply a 'confidently wrong' donor for this sweep."
    )


if __name__ == "__main__":
    main()
