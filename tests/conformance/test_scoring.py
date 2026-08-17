"""§6.5 forward scoring (src/engine/scoring.py) — decision 69's Add_Number
treatment specifically. Field weighting and the community cascade are
exercised indirectly through candidates.py's tests; this file covers what
score_ssap does with a house number now that it is no longer a weighted term.
"""

from __future__ import annotations

from src.engine import scoring
from src.engine.models import CivicAddress
from src.gis import field_stats
from src.gis.records import SSAPRecord


def setup_function(_):
    """Every field reads as unmeasured (factor 1.0) — decision 69's Add_Number
    behaviour does not depend on field_stats, but resetting keeps this file
    independent of whatever another test module last loaded into the shared
    module-level store."""
    field_stats.recompute([], [])


def _ssap(fid=1, **kwargs) -> SSAPRecord:
    kwargs.setdefault("NGUID", f"{{SSAP-{fid}}}")
    return SSAPRecord(fid=fid, **kwargs)


def test_add_number_is_not_a_weighted_term():
    """Every SSAP candidate reaching score_ssap has already matched exactly
    (decision 69's gate lives in candidates.py), so Add_Number must not move
    the score — it is reported, not weighed. Compare a query supplying
    Add_Number against one that does not, same on every other field: the
    scores are identical because Add_Number never entered the average either
    way."""
    query_with = CivicAddress(Add_Number=415, St_Name="16th")
    query_without = CivicAddress(St_Name="16th")
    record = _ssap(1, Add_Number=415, St_Name="16th")

    value_with, _ = scoring.score_ssap(query_with, record)
    value_without, _ = scoring.score_ssap(query_without, record)

    assert value_with == value_without


def test_add_number_breakdown_is_a_fixed_100_when_the_query_supplied_one():
    """Transparency, not scoring: the breakdown still names Add_Number so a
    consumer reading matchScoreBreakdown (decision 92 — the enhanced-wire
    name for this breakdown) sees it accounted for, but at a fixed value
    rather than a computed similarity."""
    query = CivicAddress(Add_Number=415, St_Name="16th")
    record = _ssap(1, Add_Number=415, St_Name="16th")

    _, breakdown = scoring.score_ssap(query, record)

    assert breakdown["Add_Number"] == 100.0


def test_add_number_is_absent_from_the_breakdown_when_the_query_omitted_it():
    """No house number to report on — a rung-1-shaped query with no HNO (the
    candidate set still reached SSAP because decision 69's gate only fires
    when the query supplies one) gets no synthesised Add_Number entry."""
    query = CivicAddress(St_Name="16th")
    record = _ssap(1, Add_Number=415, St_Name="16th")

    _, breakdown = scoring.score_ssap(query, record)

    assert "Add_Number" not in breakdown


def test_base_weights_do_not_carry_an_add_number_key():
    """decision 69 removed Add_Number from the weighted average entirely,
    not just from score_ssap's output — confirms it is gone from the table
    that drives every other field's weight."""
    assert "Add_Number" not in scoring._BASE_WEIGHTS


# ---------------------------------------------------------------------------
# Decision 71 — street name qualifies candidacy
# ---------------------------------------------------------------------------

def test_an_unrelated_street_name_disqualifies_the_candidate():
    """"El Paso" is not a typo of "Del Rio": Soundex disagrees (E412 vs D460)
    and edit similarity is 0.429, below the 0.5 floor. matchScore is forced
    to 0 so the candidate falls below any positive GCS_MIN_MATCH_SCORE, no
    matter how well the town-constant fields (type, community, county) score."""
    query = CivicAddress(Add_Number=2800, St_Name="Del Rio", St_PosTyp="Drive", A3="Bismarck")
    record = _ssap(1, Add_Number=2800, St_Name="El Paso", St_PosTyp="Drive", A3="Bismarck")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 0.0
    assert breakdown["St_Name"] < 50.0  # still reported, for a floor-0 view


def test_a_sound_preserving_misspelling_still_qualifies():
    """"Del Reo" Soundex-matches "Del Rio" (both D460) — a phonetic
    misspelling is a typo of the right street, not a different street."""
    query = CivicAddress(St_Name="Del Rio")
    record = _ssap(1, St_Name="Del Reo")

    score, _ = scoring.score_ssap(query, record)

    assert score > 0.0


def test_a_sound_breaking_typo_still_qualifies_on_edit_similarity():
    """A wrong first letter breaks Soundex entirely (Soundex codes the first
    letter literally), which is exactly the case the edit-similarity arm
    exists for: "Fel Rio" is 0.857 similar to "Del Rio"."""
    query = CivicAddress(St_Name="Del Rio")
    record = _ssap(1, St_Name="Fel Rio")

    score, _ = scoring.score_ssap(query, record)

    assert score > 0.0


def test_a_record_with_no_street_name_is_not_disqualified():
    """Decision 61's posture: sparseness costs score, not candidacy. The gate
    only fires when both sides assert a name."""
    query = CivicAddress(St_Name="Del Rio", A3="Bismarck")
    record = _ssap(1, A3="Bismarck")  # no St_Name provisioned

    score, _ = scoring.score_ssap(query, record)

    assert score > 0.0


def test_a_query_with_no_street_name_gates_nothing():
    query = CivicAddress(A3="Bismarck")
    record = _ssap(1, St_Name="El Paso", A3="Bismarck")

    score, _ = scoring.score_ssap(query, record)

    assert score > 0.0


def test_the_gate_applies_to_rcl_records_too():
    from src.gis.records import RCLRecord

    query = CivicAddress(Add_Number=2800, St_Name="Del Rio", St_PosTyp="Drive")
    record = RCLRecord(
        fid=1, NGUID="{RCL-1}", St_Name="El Paso", St_PosTyp="Drive",
        FromAddr_L=2700, ToAddr_L=2898, Parity_L="E",
        geometry_wkt="LINESTRING (-100.800 46.810, -100.780 46.810)",
    )

    score, _ = scoring.score_rcl(query, record)

    assert score == 0.0


# ---------------------------------------------------------------------------
# Decision 73 — digit-leading street names split into an exact-match digit
# gate plus a fuzzy letter suffix (resolves Appendix C.4 Q32, pair 1078)
# ---------------------------------------------------------------------------

def test_differing_digit_runs_disqualify_even_though_edit_similarity_clears_the_floor():
    """Pair 1078 from the decision 71-80 sample set (Q32; the generator was
    scaffolding and is gone, the case it surfaced is pinned here instead):
    "1st" vs "12th" sits exactly at
    the OLD edit-similarity floor (0.5) with mismatched Soundex (S300 vs
    T000) — before decision 73 this qualified and leaked a matchScore of
    56.5 for what is unambiguously a different street. The digit run ("1"
    vs "12") disagreeing now disqualifies outright, independent of the old
    edit-similarity/Soundex measures entirely."""
    query = CivicAddress(Add_Number=802, St_Name="1st", St_PosTyp="Avenue")
    record = _ssap(1, Add_Number=802, St_Name="12th", St_PosTyp="Avenue")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 0.0
    assert breakdown["St_Name"] == 0.0


def test_soundex_colliding_digit_runs_disqualify_the_more_severe_leak_case():
    """"2nd" and "22nd" strip to the same Soundex code (both "N300") because
    Soundex ignores digits entirely — before decision 73 this qualified via
    the PHONETIC branch and scored St_Name at 87.5, a worse leak than pair
    1078 because it carried full (rather than partial) phonetic credit for
    two different streets. The digit run disagreeing disqualifies regardless
    of the Soundex collision."""
    query = CivicAddress(St_Name="2nd")
    record = _ssap(1, St_Name="22nd")

    score, _ = scoring.score_ssap(query, record)

    assert score == 0.0


def test_a_single_letter_typo_in_the_ordinal_suffix_still_qualifies():
    """Why decision 73 splits digit-leading tokens instead of gating on a
    flat exact-match: the digit run ("3") is an identity, but the letter
    suffix is still human-typed text a caller can mistype. "3rf" for "3rd"
    is a single-substitution typo (D -> F) in the 2-character suffix,
    landing exactly at _STREET_QUALIFY_MIN_EDIT_SIM's inclusive floor."""
    query = CivicAddress(St_Name="3rd")
    record = _ssap(1, St_Name="3rf")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 50.0
    assert breakdown["St_Name"] == 50.0


def test_a_full_two_letter_suffix_transposition_now_qualifies():
    """Decision 73's own motivating case, and the reason decision 74 exists:
    "1st" mistyped as "1ts" is an adjacent-character transposition ("st" ->
    "ts") in the 2-character suffix. Under plain (pre-decision-74)
    Levenshtein distance this cost 2 edits (both characters "change"),
    giving 0.0 suffix similarity and disqualifying a legitimate typo of
    decision 73's own worked example. _edit_distance now prices an adjacent
    swap as 1 edit, so suffix similarity is 0.5 — exactly
    _STREET_QUALIFY_MIN_EDIT_SIM's inclusive floor — and the candidate
    qualifies."""
    query = CivicAddress(St_Name="1st")
    record = _ssap(1, St_Name="1ts")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 50.0
    assert breakdown["St_Name"] == 50.0


def test_identical_digit_leading_names_score_the_ceiling():
    query = CivicAddress(St_Name="22nd")
    record = _ssap(1, St_Name="22nd")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 100.0
    assert breakdown["St_Name"] == 100.0


def test_a_digit_leading_name_against_a_purely_alphabetic_one_disqualifies():
    """Confirmed with the user rather than assumed — decision 73's text
    doesn't walk through this mixed case explicitly. A numbered street and a
    named street can never be the same identity, so the alphabetic side's
    absent digit run fails the gate the same as two disagreeing digit runs
    would, rather than falling back to the old Soundex/edit-distance blend."""
    query = CivicAddress(St_Name="12th")
    record = _ssap(1, St_Name="Interstate")

    score, _ = scoring.score_ssap(query, record)

    assert score == 0.0


def test_a_bare_number_street_name_against_its_own_ordinal_form_is_not_disqualified():
    """"10" (a bare-number road name — common in the provisioned data.gpkg,
    e.g. rural section-line roads) has no letter suffix to compare against
    "10th"'s "TH". Once the digit runs agree there is nothing left to
    compare — decision 61's posture applies here too: sparseness costs
    score (the St_Name term drops out of the weighted average entirely), not
    candidacy. Other fields populated on both sides so the test isolates
    that behaviour from the unrelated "nothing in the query was comparable
    at all" zero (§6.4) that would otherwise mask it."""
    query = CivicAddress(Add_Number=100, St_Name="10", St_PosTyp="Avenue", A3="Mandan")
    record = _ssap(1, Add_Number=100, St_Name="10th", St_PosTyp="Avenue", A3="Mandan")

    score, breakdown = scoring.score_ssap(query, record)

    assert score > 0.0
    assert "St_Name" not in breakdown


def test_pure_alphabetic_street_names_are_unaffected_by_decision_73():
    """"Third" vs "Thirteenth" — neither side begins with a digit, so this
    falls straight through to the pre-existing Soundex/edit-distance blend,
    unchanged: Soundex disagrees and edit similarity (0.2) is well below the
    floor, same disqualifying outcome as before this change."""
    query = CivicAddress(St_Name="Third")
    record = _ssap(1, St_Name="Thirteenth")

    score, _ = scoring.score_ssap(query, record)

    assert score == 0.0


def test_elm_vs_elk_behaviour_is_unchanged_by_decision_73():
    """Confirms decision 73 does not touch the general, still-open
    Soundex-mismatch/edit-similarity divergence for purely alphabetic names
    (Q32's writeup) — only digit-leading tokens get the new treatment.
    "Elm" vs "Elk" still qualifies and scores exactly as it did before this
    change (0.667 edit similarity blended 50/50 with a Soundex mismatch)."""
    query = CivicAddress(St_Name="Elm")
    record = _ssap(1, St_Name="Elk")

    score, breakdown = scoring.score_ssap(query, record)

    assert score > 0.0
    assert breakdown["St_Name"] == 33.33


# ---------------------------------------------------------------------------
# Decision 74 — edit distance is transposition-aware everywhere it's used
# ---------------------------------------------------------------------------

def test_a_plain_alphabetic_transposition_scores_higher_than_an_unrelated_substitution_pair():
    """Not digit-leading at all — decision 74 is a primitive-level change,
    not a St_Name-specific one, so a purely alphabetic free-text pair
    exercises it too. "Maple" mistyped as "Mapel" is a single adjacent
    transposition ("le" -> "el"); "Mably" is a genuinely different street
    that happens to sit the SAME plain-Levenshtein distance (2) from
    "Maple" via two ordinary substitutions that are not adjacent-swappable.
    Before decision 74 both scored identically (distance 2 either way);
    after it, only the transposition gets the 2-edits-to-1 discount, so
    "Mapel" now scores measurably higher than "Mably" despite both being
    "2 edits away" under the old metric."""
    query = CivicAddress(St_Name="Maple")
    transposed = _ssap(1, St_Name="Mapel")
    unrelated_substitution = _ssap(2, St_Name="Mably")

    transposed_score, transposed_breakdown = scoring.score_ssap(query, transposed)
    substitution_score, substitution_breakdown = scoring.score_ssap(query, unrelated_substitution)

    assert transposed_breakdown["St_Name"] > substitution_breakdown["St_Name"]
    assert transposed_score > substitution_score


def test_an_exact_match_still_scores_the_ceiling_after_decision_74():
    """Transposition tolerance must not touch decision 28's exact-is-the-
    ceiling short-circuit, which runs before _edit_distance is ever called."""
    query = CivicAddress(St_Name="Maple")
    record = _ssap(1, St_Name="Maple")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 100.0
    assert breakdown["St_Name"] == 100.0


def test_completely_unrelated_tokens_still_score_near_zero_after_decision_74():
    """Transposition tolerance is narrow (one adjacent swap = one edit); it
    must not inflate a pair that shares nothing structurally. "Maple" vs
    "Grove" share no adjacent-swappable characters, so this is unaffected by
    decision 74 and stays near zero, same as under plain Levenshtein."""
    query = CivicAddress(St_Name="Maple")
    record = _ssap(1, St_Name="Grove")

    score, breakdown = scoring.score_ssap(query, record)

    assert score < 15.0
    assert breakdown["St_Name"] < 15.0


# ---------------------------------------------------------------------------
# _TYPE_EXPANSIONS widened against data.gpkg + USPS Pub 28 (§6.5)
# ---------------------------------------------------------------------------

def test_a_usps_pub_28_abbreviation_added_by_widening_now_scores_the_ceiling():
    """"Trl" for "Trail" — the worked example from the widening pass.
    Verified against USPS Publication 28 Appendix C1 (the Postal Service
    Standard Suffix Abbreviation for primary name "Trail")."""
    query = CivicAddress(St_Name="Fox", St_PosTyp="Trl")
    record = _ssap(1, St_Name="Fox", St_PosTyp="Trail")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 100.0
    assert breakdown["St_Type"] == 100.0


def test_another_usps_pub_28_abbreviation_added_by_widening_now_scores_the_ceiling():
    """"Expy" for "Expressway" — the second-worst gap found in the original
    investigation (matchScore 77.14 before this pass)."""
    query = CivicAddress(St_Name="River", St_PosTyp="Expy")
    record = _ssap(1, St_Name="River", St_PosTyp="Expressway")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 100.0
    assert breakdown["St_Type"] == 100.0


def test_county_road_is_deliberately_not_covered_and_remains_penalized():
    """The worst gap the original investigation found (matchScore 9.09) is
    UNCHANGED by this widening pass, on purpose: "County Road" is a
    St_PreTyp route/jurisdiction designator, not a USPS Pub 28 mail-delivery
    suffix. The NENA Street Name Pre/Post Types registry confirms it as a
    recognized domain value sourced from "State of NY", not "USPS Pub 28" —
    there is no standard abbreviation to cite, so none was invented. See
    _TYPE_EXPANSIONS's docstring for County Road, Interstate, and BIA Route,
    all left out on the same evidentiary basis."""
    query = CivicAddress(St_PreTyp="Cr")
    record = _ssap(1, St_PreTyp="County Road")

    score, breakdown = scoring.score_ssap(query, record)

    assert breakdown["St_Type"] < 15.0


# ---------------------------------------------------------------------------
# Decision 76 — Community cascade shortened, discriminative factor follows
# the resolved field (amends 66)
# ---------------------------------------------------------------------------

def test_community_ssap_reports_which_field_resolved_the_value():
    """_community_ssap now returns (value, field) so the caller can weight by
    the field that actually produced it. Three tiers, three record shapes."""
    via_a3 = _ssap(1, A3="Bismarck", A4="Ignored", Post_Comm="Ignored")
    via_a4 = _ssap(2, A4="Turtle Lake", Post_Comm="Ignored")
    via_post_comm = _ssap(3, Post_Comm="Beulah")
    nothing = _ssap(4)

    assert scoring._community_ssap(via_a3) == ("Bismarck", "A3")
    assert scoring._community_ssap(via_a4) == ("Turtle Lake", "A4")
    assert scoring._community_ssap(via_post_comm) == ("Beulah", "Post_Comm")
    assert scoring._community_ssap(nothing) == (None, None)


def test_msagcomm_is_no_longer_part_of_the_cascade():
    """The real case the investigation found: NGUID
    {C492152E-3D9D-482B-BA3C-6B1C0F4994DC}, 3806 Prairie Pines Loop — A3,
    A4, and Post_Comm are all empty, only MSAGComm="BISMARCK" is populated.
    Before decision 76 this record resolved its Community value from
    MSAGComm; now the cascade doesn't look at it at all, so this record has
    NO Community value -- not a MSAGComm comparison, not an error."""
    record = _ssap(
        1, NGUID="{C492152E-3D9D-482B-BA3C-6B1C0F4994DC}",
        Add_Number=3806, St_Name="Prairie Pines", St_PosTyp="Loop",
        MSAGComm="BISMARCK",
    )

    assert scoring._community_ssap(record) == (None, None)

    query = CivicAddress(Add_Number=3806, St_Name="Prairie Pines", St_PosTyp="Loop", A3="Bismarck")
    score, breakdown = scoring.score_ssap(query, record)

    # Excluded from the weighted average entirely (decision 61's sparseness
    # posture) -- not compared against MSAGComm, and not a mismatch either.
    assert "Community" not in breakdown
    assert score == 100.0


def test_community_weight_follows_the_resolved_field_not_a_fixed_one_ssap():
    """The actual regression this decision fixes. Two records assert the
    SAME mismatched community VALUE ("Bismark", a typo of the query's
    "Bismarck" -- identical Community similarity either way, and one that
    QUALIFIES under decision 77's gate so the weight comparison below has
    a nonzero score to compare), but one resolves via A3 and the other via
    Post_Comm. field_stats is seeded so A3 is highly discriminative
    (factor 0.95, 20 distinct values) and Post_Comm is nearly uniform
    (factor 0.05, one dominant value) -- if the weight correctly follows
    the resolved field, the A3 case should score noticeably lower
    (Community carries much more weight there) than the Post_Comm case
    (Community is almost weightless there). Before decision 76,
    score_ssap always used f("A3") regardless, so these two records would
    have scored identically -- that is exactly the bug this proves is
    fixed."""
    synthetic_ssap = [
        SSAPRecord(
            fid=i, NGUID=f"{{X-{i}}}",
            A3=f"Town{i % 20}",  # 20 distinct values, twice each -> factor 0.95
            Post_Comm=("Bismarck" if i < 38 else "Mandan"),  # near-uniform -> factor 0.05
        )
        for i in range(40)
    ]
    field_stats.recompute(synthetic_ssap, [])

    query = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Bismarck")
    record_via_a3 = _ssap(1, Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Bismark")
    record_via_post_comm = _ssap(2, Add_Number=100, St_Name="Main", St_PosTyp="Street", Post_Comm="Bismark")

    score_a3, breakdown_a3 = scoring.score_ssap(query, record_via_a3)
    score_pc, breakdown_pc = scoring.score_ssap(query, record_via_post_comm)

    # Same Community similarity both times -- the only thing that differs
    # is which field's factor weighted it.
    assert breakdown_a3["Community"] == breakdown_pc["Community"]
    assert score_a3 < score_pc


def test_community_weight_follows_the_resolved_field_independently_per_rcl_side():
    """RCL is sided -- confirm the fix applies independently per side, not
    just once for the whole record. Same setup as the SSAP test, but one
    side resolves via A3_L and the other via PostComm_R, and the query's
    Add_Number parity (matched against Parity_L/R) picks which side scores.
    Both sides compare against the identical mismatched-but-qualifying
    value "Bismark" (typo of "Bismarck"), so any score difference is
    attributable only to which side's factor won."""
    from src.gis.records import RCLRecord

    synthetic_rcl = [
        RCLRecord(
            fid=i, NGUID=f"{{X-{i}}}",
            A3_L=f"Town{i % 20}", A3_R=f"Town{i % 20}",
            PostComm_L=("Bismarck" if i < 38 else "Mandan"),
            PostComm_R=("Bismarck" if i < 38 else "Mandan"),
        )
        for i in range(40)
    ]
    field_stats.recompute([], synthetic_rcl)

    record = RCLRecord(
        fid=1, NGUID="{RCL-1}", St_Name="Main", St_PosTyp="Street",
        FromAddr_L=100, ToAddr_L=198, Parity_L="E",
        FromAddr_R=101, ToAddr_R=199, Parity_R="O",
        A3_L="Bismark",              # left resolves via A3 (high factor)
        PostComm_R="Bismark",        # right resolves via Post_Comm (low factor), A3_R empty
        geometry_wkt="LINESTRING (-100.800 46.810, -100.780 46.810)",
    )
    query_picks_left = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Bismarck")
    query_picks_right = CivicAddress(Add_Number=101, St_Name="Main", St_PosTyp="Street", A3="Bismarck")

    score_left, breakdown_left = scoring.score_rcl(query_picks_left, record)
    score_right, breakdown_right = scoring.score_rcl(query_picks_right, record)

    assert breakdown_left["Community"] == breakdown_right["Community"]
    assert score_left < score_right


# ---------------------------------------------------------------------------
# Community mismatch caps the term rather than disqualifying the candidate
# (decision 80, supersedes 77, which made it a candidacy gate in decision 71's shape)
#
# The qualification TEST decision 77 authored is unchanged and still lives in
# _community_qualifies; only its consequence moved. These tests are therefore
# written against the two observable behaviours — a qualifying Community is
# scored by decision 72's blend untouched, a non-qualifying one is clamped to
# _COMMUNITY_MISMATCH_SIMILARITY_CAP — and never against the cap's literal
# value, which decision 80's sweep found no reason to prefer over its
# neighbours. Writing them against the behaviour rather than the number is what
# lets the constant move without these tests needing to.
# ---------------------------------------------------------------------------

def test_a_sound_preserving_community_typo_still_qualifies():
    """"Btn" Soundex-matches "Bottineau" (both B350) despite low edit
    similarity (0.333, well under the floor) — the phonetic key alone is
    enough, same shape as decision 71's "Del Reo"/"Del Rio" case. A
    qualifying Community is scored by decision 72's blend untouched: the cap
    applies to non-qualifying values only, so the reported term is exactly
    what _normalized_similarity produced with no clamp in the path."""
    query = CivicAddress(Add_Number=100, St_Name="Main", A3="Bottineau")
    record = _ssap(1, Add_Number=100, St_Name="Main", A3="Btn")

    score, breakdown = scoring.score_ssap(query, record)

    assert score > 0.0
    uncapped = scoring._normalized_similarity("Bottineau", "Btn")
    assert breakdown["Community"] == round(uncapped * 100.0, 2)
    assert breakdown["Community"] > scoring._COMMUNITY_MISMATCH_SIMILARITY_CAP * 100.0


def test_a_sound_breaking_community_typo_still_qualifies_on_edit_similarity():
    """"Karington" breaks Soundex against "Carrington" (K652 vs C652 — a
    wrong first letter, which Soundex weights heavily) but is 0.8 edit
    similar — the edit-similarity key alone is enough, same shape as
    decision 71's "Fel Rio"/"Del Rio" case. Qualifying, so uncapped."""
    query = CivicAddress(Add_Number=100, St_Name="Main", A3="Carrington")
    record = _ssap(1, Add_Number=100, St_Name="Main", A3="Karington")

    score, breakdown = scoring.score_ssap(query, record)

    assert score > 0.0
    uncapped = scoring._normalized_similarity("Carrington", "Karington")
    assert breakdown["Community"] == round(uncapped * 100.0, 2)


def test_a_genuinely_different_community_no_longer_disqualifies_the_candidate():
    """"Bismarck" and "Turtle Lake" are both real A3 values in data.gpkg
    (41,083 and 399 records respectively) and share neither a Soundex code
    (B256 vs T634) nor meaningful edit similarity (0.091) — a different
    town, not a typo of this one. Under decision 77 this forced matchScore
    to 0. It no longer does: everything else about the candidate (street
    name, house number, street type) still agrees, and the disagreement is
    priced into the Community term rather than thrown at the whole
    candidate. The term itself lands at or below the cap, so the wrong town
    is still visibly costed."""
    query = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Bismarck")
    record = _ssap(1, Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Turtle Lake")

    score, breakdown = scoring.score_ssap(query, record)

    assert score > 0.0
    assert breakdown["Community"] <= scoring._COMMUNITY_MISMATCH_SIMILARITY_CAP * 100.0


def test_a_non_qualifying_community_is_clamped_to_the_cap(monkeypatch):
    """"Turtle Lake" and "Tuttle" are two different real ND towns that look
    alike enough to collect 0.227 from decision 72's blend — well above a
    near-zero — while failing the qualification test on both keys (T634 vs
    T340, edit similarity 0.455 under the 0.5 floor). That gap is exactly
    what the cap exists to close: without it, how much a wrong town costs
    depends on how many letters the two names happen to share.

    The cap is monkeypatched to a known value rather than read from the
    module, because this test asserts an exact clamped number and the
    committed constant is an unchosen strawman that the sweep is expected to
    move."""
    monkeypatch.setattr(scoring, "_COMMUNITY_MISMATCH_SIMILARITY_CAP", 0.15)

    query = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Turtle Lake")
    record = _ssap(1, Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Tuttle")

    _, breakdown = scoring.score_ssap(query, record)

    # 22.73 uncapped; the cap overrides whatever the blend computed.
    assert scoring._normalized_similarity("Turtle Lake", "Tuttle") > 0.15
    assert breakdown["Community"] == 15.0


def test_the_community_cap_is_a_ceiling_not_an_assignment(monkeypatch):
    """The cap lowers a similarity and never raises one. "Bismarck" against
    "Turtle Lake" blends to 0.045 — already far below the cap — and keeps
    its own lower score rather than being lifted to the cap, which would
    make an unrelated town score BETTER than it does on the evidence."""
    monkeypatch.setattr(scoring, "_COMMUNITY_MISMATCH_SIMILARITY_CAP", 0.15)

    query = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Bismarck")
    record = _ssap(1, Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Turtle Lake")

    _, breakdown = scoring.score_ssap(query, record)

    assert breakdown["Community"] == 4.55


def test_a_query_with_no_community_caps_nothing():
    """The cap only fires when the query supplies a Community value. A
    query that names no community at all is not asserting anything to
    disagree with, so the term drops out of the weighted average entirely
    rather than being scored — and certainly rather than being capped."""
    query = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street")
    record = _ssap(1, Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Turtle Lake")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 100.0
    assert "Community" not in breakdown


def test_a_record_with_no_resolvable_community_is_neither_capped_nor_scored():
    """The real case decision 76's tests already use: NGUID
    {C492152E-3D9D-482B-BA3C-6B1C0F4994DC}, 3806 Prairie Pines Loop — A3,
    A4, and Post_Comm are all empty (MSAGComm is no longer in the cascade
    at all, decision 76). Decision 61's sparseness posture: a record with
    nothing to compare is not disqualified, Community simply drops out of
    the weighted average."""
    record = _ssap(
        1, NGUID="{C492152E-3D9D-482B-BA3C-6B1C0F4994DC}",
        Add_Number=3806, St_Name="Prairie Pines", St_PosTyp="Loop",
        MSAGComm="BISMARCK",
    )
    query = CivicAddress(Add_Number=3806, St_Name="Prairie Pines", St_PosTyp="Loop", A3="Bismarck")

    score, breakdown = scoring.score_ssap(query, record)

    assert score == 100.0
    assert "Community" not in breakdown


def test_community_and_street_name_qualification_thresholds_are_independent(monkeypatch):
    """_COMMUNITY_QUALIFY_MIN_EDIT_SIM and _STREET_QUALIFY_MIN_EDIT_SIM are
    separate constants, not a shared reference — raising one to exclude a
    pair that currently qualifies must not touch the other's behaviour."""
    # "Karington"/"Carrington" qualifies today at 0.8 edit similarity
    # (see the test above). Raise ONLY the community threshold past that.
    monkeypatch.setattr(scoring, "_COMMUNITY_QUALIFY_MIN_EDIT_SIM", 0.95)

    assert scoring._community_qualifies("Carrington", "Karington") is False
    # The street-name gate, using the untouched _STREET_QUALIFY_MIN_EDIT_SIM
    # (0.5), still qualifies the analogous street-name case.
    assert scoring._street_name_qualifies("Del Rio", "Fel Rio") is True
    assert scoring._STREET_QUALIFY_MIN_EDIT_SIM == 0.5


def test_the_rcl_community_cap_is_evaluated_against_the_correct_side():
    """Mirrors decision 76's own side-consistency test: side L resolves
    "Turtle Lake" (genuinely different from the query's "Bismarck" — should
    be capped when LEFT is the side in play), side R resolves "Bismarck"
    itself (should score 100 uncapped when RIGHT is in play). Add_Number
    parity picks the side, same as decision 76's RCL test. The cap is
    applied after the side is settled, so the side whose value was compared
    is the side whose qualification decides the clamp — getting that wrong
    would cap a candidate on the strength of the side it was never scored
    against."""
    from src.gis.records import RCLRecord

    record = RCLRecord(
        fid=1, NGUID="{RCL-1}", St_Name="Main", St_PosTyp="Street",
        FromAddr_L=100, ToAddr_L=198, Parity_L="E",
        FromAddr_R=101, ToAddr_R=199, Parity_R="O",
        A3_L="Turtle Lake",
        A3_R="Bismarck",
        geometry_wkt="LINESTRING (-100.800 46.810, -100.780 46.810)",
    )
    query_picks_left = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A3="Bismarck")
    query_picks_right = CivicAddress(Add_Number=101, St_Name="Main", St_PosTyp="Street", A3="Bismarck")

    score_left, breakdown_left = scoring.score_rcl(query_picks_left, record)
    score_right, breakdown_right = scoring.score_rcl(query_picks_right, record)

    assert breakdown_left["Community"] <= scoring._COMMUNITY_MISMATCH_SIMILARITY_CAP * 100.0
    assert breakdown_right["Community"] == 100.0
    assert 0.0 < score_left < score_right


# ---------------------------------------------------------------------------
# Decision 82 — controlled-vocabulary fields compare binary (supersedes 81)
# ---------------------------------------------------------------------------
# St_Dir, A1 and Country are class (2) in decision 82's taxonomy: exact match
# after normalization scores 1.0, anything else 0.0. They stay weighted terms —
# decision 81's brief A1/Country candidate-set gates were reverted in-spec
# before implementation, and the last test in this section is the property
# that revert exists to protect.

def test_opposite_quadrant_directionals_score_zero_not_near_full_credit():
    """The bug that motivated decision 82. "NE" and "NW" both expand to
    NORTHEAST/NORTHWEST, which are edit-similar AND share Soundex code N632,
    so decision 72's blend scored this pair 0.889 — near-full credit for
    opposite quadrants, worse than the "SD"/"ND" = 0.50 case Q30 originally
    complained about. A caller selecting from a closed set of eight
    directionals did not nearly say NW when they said NE."""
    similarity = scoring._normalized_similarity(
        "NE", "NW", expansions=scoring._DIRECTIONAL_EXPANSIONS, binary=True
    )

    assert similarity == 0.0


def test_an_abbreviated_directional_still_matches_its_expansion_exactly():
    """Binary is applied AFTER normalization, not instead of it — which is
    the whole point of keeping _DIRECTIONAL_EXPANSIONS. "N" and "NORTH" are
    the same value, not a near-miss bridged by edit distance, so the table
    now carries the comparison rather than merely helping it."""
    similarity = scoring._normalized_similarity(
        "N", "NORTH", expansions=scoring._DIRECTIONAL_EXPANSIONS, binary=True
    )

    assert similarity == 1.0


def test_a_directional_and_a_different_quadrant_containing_it_score_zero():
    """"N" expands to NORTH, which is a prefix of NORTHEAST — exactly the
    shape of overlap edit distance rewards and a closed vocabulary must not.
    North and northeast are two of eight distinct values, not 60% of the
    same one."""
    similarity = scoring._normalized_similarity(
        "N", "NE", expansions=scoring._DIRECTIONAL_EXPANSIONS, binary=True
    )

    assert similarity == 0.0


def test_two_state_codes_sharing_a_character_score_zero():
    """Appendix C.4 Q30's original complaint, now closed: "SD" against "ND"
    scored 0.50 under edit distance purely because both end in D. South
    Dakota is not half of North Dakota — it is a different jurisdiction."""
    assert scoring._normalized_similarity("SD", "ND", binary=True) == 0.0


def test_a_predir_postdir_position_swap_still_takes_full_credit():
    """Decision 82 keeps St_Dir as ONE term compared best-of-both-sides
    precisely so this caller is not penalized: "Main Street North" spoken for
    a street formally named "North Main Street" is the right street named in
    spoken order, and the TIGER normalizer itself reassigns pre/post freely
    during parsing. The query's directional lands in the post slot, the
    record carries it in the pre slot, and the binary comparison finds an
    exact match against the slot the record actually populated."""
    query = CivicAddress(St_Name="Main", St_PosTyp="Street", St_PosDir="N")
    record = _ssap(1, St_Name="Main", St_PosTyp="Street", St_PreDir="N", St_PosDir=None)

    _, breakdown = scoring.score_ssap(query, record)

    assert breakdown["St_Dir"] == 100.0


def test_a_wrong_directional_zeroes_the_term_without_excluding_the_candidate():
    """A genuinely wrong directional is a bounded ranking penalty, not a
    gate. The St_Dir term scores 0, which drops the candidate below any
    directional-correct competitor, but the street name, type and house
    number all still agree and still carry the candidate well clear of
    zero — decision 82 chose a weighted term over decision 81's gate shape
    for exactly this reason."""
    query = CivicAddress(St_Name="Main", St_PosTyp="Street", St_PreDir="N")
    record = _ssap(1, St_Name="Main", St_PosTyp="Street", St_PreDir="S")

    score, breakdown = scoring.score_ssap(query, record)

    assert breakdown["St_Dir"] == 0.0
    assert score > 50.0


def test_a_wrong_state_still_leaves_a_scorable_candidate():
    """The property decision 82 reverted decision 81's gate to protect. A
    caller who names the wrong state — Fargo mistaken for Moorhead MN across
    the river, Pembina at the Canadian line — would have had the candidate
    set emptied outright by a hard A1 gate against a single-state export,
    turning a query the remaining terms answer correctly into a 468. The
    binary term prices the mismatch honestly at 0 and leaves the candidate
    ranked, not excluded."""
    query = CivicAddress(Add_Number=100, St_Name="Main", St_PosTyp="Street", A1="MN")
    record = _ssap(1, Add_Number=100, St_Name="Main", St_PosTyp="Street", A1="ND")

    score, breakdown = scoring.score_ssap(query, record)

    assert breakdown["A1"] == 0.0
    assert score > 0.0


# ---------------------------------------------------------------------------
# Decision 90 — St_Type and St_Dir follow the slot that produced the
# compared value, extending decision 76's Community-cascade fix to the two
# terms that span a pre/post slot pair instead of a cascade
# ---------------------------------------------------------------------------

def test_best_of_sides_reports_the_winning_slots_field_name():
    """The core contract decision 90 adds: not just a similarity, but which
    of the two slots produced it, so the caller can weight by that field's
    own discriminative factor rather than one fixed in source."""
    similarity, field = scoring._best_of_sides(
        "Street", "Street", "Boulevard",
        left_field="St_PosTyp", right_field="St_PreTyp",
    )
    assert similarity == 1.0
    assert field == "St_PosTyp"

    similarity, field = scoring._best_of_sides(
        "Street", "Boulevard", "Street",
        left_field="St_PosTyp", right_field="St_PreTyp",
    )
    assert similarity == 1.0
    assert field == "St_PreTyp"


def test_best_of_sides_ties_broken_by_larger_measured_population():
    """Decision 90's tie rule: when both slots score EQUALLY well (here,
    both mismatch and score 0.0 under a binary comparison), the slot with
    the larger measured population wins — a larger sample is the more
    meaningful statistic of the two, and the choice must be deterministic
    rather than left to argument order."""
    similarity, field = scoring._best_of_sides(
        "North", "South", "South",
        left_field="St_PreDir", right_field="St_PosDir",
        left_population=100, right_population=50000,
        binary=True,
    )
    assert similarity == 0.0
    assert field == "St_PosDir"

    # Same tie, populations reversed — confirms it is the population being
    # read, not St_PosDir winning for some unrelated reason.
    similarity, field = scoring._best_of_sides(
        "North", "South", "South",
        left_field="St_PreDir", right_field="St_PosDir",
        left_population=50000, right_population=100,
        binary=True,
    )
    assert similarity == 0.0
    assert field == "St_PreDir"


def test_best_of_sides_equal_population_falls_back_to_the_fixed_left_order():
    """Both the similarity AND the population are tied — including the
    default 0/0 a caller passes when it does not care about the winning
    field at all (score_rcl's ambiguous-side A2/A1/Country lookup, which
    uses one pooled factor regardless of side). The fallback must be a
    fixed, documented order, not a data-dependent coin flip."""
    similarity, field = scoring._best_of_sides(
        "North", "South", "South",
        left_field="St_PreDir", right_field="St_PosDir",
        binary=True,
    )
    assert similarity == 0.0
    assert field == "St_PreDir"


def test_best_of_sides_returns_none_none_when_neither_slot_compares():
    """Decision 76's (None, None) contract, extended: nothing to compare
    means no winning field either, so the caller's weight lookup is moot the
    same way community_field being None makes Community's weight moot."""
    similarity, field = scoring._best_of_sides(
        None, None, None, left_field="St_PosTyp", right_field="St_PreTyp",
    )
    assert similarity is None
    assert field is None

    # The query asserted something but the record has no populated slot at
    # all — same (None, None) outcome, a different route to it.
    similarity, field = scoring._best_of_sides(
        "Street", None, None, left_field="St_PosTyp", right_field="St_PreTyp",
    )
    assert similarity is None
    assert field is None


def test_st_dir_weight_follows_the_slot_that_produced_the_value_ssap():
    """The real regression decision 90 fixes, same shape as decision 76's
    Community test: two records assert the SAME mismatched St_Dir value
    (query "North", record "South" — a binary mismatch, term scores 0.0
    either way), but one comes from St_PreDir and the other from St_PosDir.
    field_stats is seeded so St_PreDir is highly discriminative (4 distinct
    values, evenly split) and St_PosDir is uniform (1 value everywhere,
    factor exactly 0.0) — before decision 90, score_ssap always weighted
    St_Dir by f("St_PreDir") regardless of which slot produced the
    comparison, so these two records would have scored identically. With
    the fix, the St_PreDir case (nonzero weight, wrong) is reported and
    costs the candidate real score; the St_PosDir case has weight exactly
    0.0, so _weighted_average drops the term from the breakdown entirely
    (weight <= 0 is excluded the same way a None similarity is) — the wrong
    value costs nothing, same as the term never having existed."""
    directions = ["North", "South", "East", "West"]
    synthetic_ssap = [
        SSAPRecord(
            fid=i, NGUID=f"{{X-{i}}}",
            St_PreDir=directions[i % 4],  # 4 distinct values, evenly split -> high factor
            St_PosDir="North",            # one dominant value -> factor 0.0
        )
        for i in range(40)
    ]
    field_stats.recompute(synthetic_ssap, [])

    query = CivicAddress(Add_Number=100, St_Name="Main", St_PreDir="North")
    record_via_predir = _ssap(1, Add_Number=100, St_Name="Main", St_PreDir="South", St_PosDir=None)
    record_via_posdir = _ssap(2, Add_Number=100, St_Name="Main", St_PosDir="South", St_PreDir=None)

    score_predir, breakdown_predir = scoring.score_ssap(query, record_via_predir)
    score_posdir, breakdown_posdir = scoring.score_ssap(query, record_via_posdir)

    assert breakdown_predir["St_Dir"] == 0.0
    assert "St_Dir" not in breakdown_posdir  # weight 0.0 -> excluded, not just zeroed
    assert score_predir < score_posdir
    assert score_posdir == 100.0  # St_Dir contributed nothing; only St_Name remains


def test_st_type_weight_follows_the_slot_that_produced_the_value_ssap():
    """Same shape as the St_Dir test above, for St_Type's PreTyp/PosTyp
    pair. Decision 90 covers both terms deliberately: St_PosTyp happens to
    be the dominant slot in the real statewide deployment, so this is not
    currently a live bug there — but the lookup must follow the resolved
    slot rather than trusting which one usually wins, and this seeds the
    opposite skew to prove it does."""
    types = ["Street", "Avenue", "Drive", "Court"]
    synthetic_ssap = [
        SSAPRecord(
            fid=i, NGUID=f"{{Y-{i}}}",
            St_PreTyp=types[i % 4],  # 4 distinct values, evenly split -> high factor
            St_PosTyp="Street",      # one dominant value -> factor 0.0
        )
        for i in range(40)
    ]
    field_stats.recompute(synthetic_ssap, [])

    query = CivicAddress(Add_Number=100, St_Name="Main", St_PreTyp="Street")
    record_via_pretyp = _ssap(1, Add_Number=100, St_Name="Main", St_PreTyp="Avenue", St_PosTyp=None)
    record_via_postyp = _ssap(2, Add_Number=100, St_Name="Main", St_PosTyp="Avenue", St_PreTyp=None)

    score_pretyp, breakdown_pretyp = scoring.score_ssap(query, record_via_pretyp)
    score_postyp, breakdown_postyp = scoring.score_ssap(query, record_via_postyp)

    # St_PreTyp carries real weight (factor 0.75) so the imperfect
    # "Street"/"Avenue" similarity is reported and costs the candidate;
    # St_PosTyp's weight is exactly 0.0 (uniform field), so the same
    # mismatch is excluded from the breakdown entirely and costs nothing.
    assert "St_Type" in breakdown_pretyp
    assert "St_Type" not in breakdown_postyp
    assert score_pretyp < score_postyp
    assert score_postyp == 100.0  # St_Type contributed nothing; only St_Name remains


def test_st_dir_drops_from_the_breakdown_when_the_record_has_neither_slot():
    """Decision 61's sparseness posture, same as Community's no-value case:
    a record with no directional at all is not compared against a default
    and does not gate anything — it simply has nothing to compare, and the
    term drops out of the weighted average entirely."""
    query = CivicAddress(Add_Number=100, St_Name="Main", St_PreDir="North")
    record = _ssap(1, Add_Number=100, St_Name="Main")  # no St_PreDir/St_PosDir

    score, breakdown = scoring.score_ssap(query, record)

    assert "St_Dir" not in breakdown
    assert score == 100.0


def test_st_dir_weight_follows_the_slot_that_produced_the_value_rcl():
    """The score_rcl mirror of the SSAP test above — St_PreDir/St_PosDir are
    RCL's UNSIDED shared columns (field_stats._RCL_SHARED: one value per
    segment, never an _L/_R pair), so this exercises the same decision-90
    fix at the OTHER call site entirely, independent of score_ssap's."""
    from src.gis.records import RCLRecord

    directions = ["North", "South", "East", "West"]
    synthetic_rcl = [
        RCLRecord(
            fid=i, NGUID=f"{{Z-{i}}}",
            St_PreDir=directions[i % 4],
            St_PosDir="North",
        )
        for i in range(40)
    ]
    field_stats.recompute([], synthetic_rcl)

    query = CivicAddress(Add_Number=100, St_Name="Main", St_PreDir="North")
    record_via_predir = RCLRecord(
        fid=1, NGUID="{RCL-1}", St_Name="Main", St_PreDir="South", St_PosDir=None,
        FromAddr_L=100, ToAddr_L=198, Parity_L="E",
        geometry_wkt="LINESTRING (-100.800 46.810, -100.780 46.810)",
    )
    record_via_posdir = RCLRecord(
        fid=2, NGUID="{RCL-2}", St_Name="Main", St_PosDir="South", St_PreDir=None,
        FromAddr_L=100, ToAddr_L=198, Parity_L="E",
        geometry_wkt="LINESTRING (-100.800 46.810, -100.780 46.810)",
    )

    score_predir, breakdown_predir = scoring.score_rcl(query, record_via_predir)
    score_posdir, breakdown_posdir = scoring.score_rcl(query, record_via_posdir)

    # Same shape as the SSAP test: St_PreDir carries real weight and reports
    # the mismatch; St_PosDir's weight is exactly 0.0 (uniform field), so
    # score_rcl excludes the term from the breakdown entirely.
    assert breakdown_predir["St_Dir"] == 0.0
    assert "St_Dir" not in breakdown_posdir
    assert score_predir < score_posdir
    assert score_posdir == 100.0


def test_rcl_st_dir_weight_is_independent_of_which_side_wins():
    """St_PreDir/St_PosDir are RCL's unsided shared columns, so decision 90's
    slot lookup must not be affected by `side` — the L/R selection §11.3
    makes for administrative/postal attribution. Two queries pick opposite
    sides (via Add_Number parity) on the SAME record; the St_Dir term must
    score identically either way, because St_PreDir/St_PosDir have no side
    to pick in the first place. This is the check the task asked for: that
    the slot-name plumbing does not cross the L/R side boundary."""
    from src.gis.records import RCLRecord

    record = RCLRecord(
        fid=1, NGUID="{RCL-1}", St_Name="Main",
        FromAddr_L=100, ToAddr_L=198, Parity_L="E",
        FromAddr_R=101, ToAddr_R=199, Parity_R="O",
        St_PreDir="South", St_PosDir=None,
        geometry_wkt="LINESTRING (-100.800 46.810, -100.780 46.810)",
    )
    query_picks_left = CivicAddress(Add_Number=100, St_Name="Main", St_PreDir="North")
    query_picks_right = CivicAddress(Add_Number=101, St_Name="Main", St_PreDir="North")

    score_left, breakdown_left = scoring.score_rcl(query_picks_left, record)
    score_right, breakdown_right = scoring.score_rcl(query_picks_right, record)

    assert breakdown_left["St_Dir"] == breakdown_right["St_Dir"] == 0.0
    assert score_left == score_right


# ---------------------------------------------------------------------------
# §10.6 reverse spatial-fit — the Geocoding-placement damping
# ---------------------------------------------------------------------------
# GCS_GEOCODED_PLACEMENT_PENALTY (decision 66). A record whose own position was
# derived by geocoding, then reverse-geocoded back to an address, is a round
# trip through two approximations and the score is meant to say so. The penalty
# is bound at scorer registration by src/app/lifecycle.py; make_reverse_scorer
# keeps a default so it stays usable without the environment.

from src.engine.models import LocationType, SsapGisRecord
from src.reverse import origin as shapes
from src.reverse.search import Hit


def _placed_hit(placement, distance=0.0, contained=True):
    record = SsapGisRecord.from_record(
        SSAPRecord(
            fid=1,
            NGUID="{SSAP-1}",
            Placement=placement,
            geometry_wkt="POINT (-100.8022 46.8357)",
        )
    )
    return Hit(
        record=record,
        distance_m=distance,
        contained=contained,
        tier=LocationType.ADDRESS_POINT,
    )


def _point_origin():
    return shapes.Point(-100.8022, 46.8357).origin()


def test_geocoding_placement_damps_the_spatial_fit_score():
    """The whole point of the constant: a Geocoding-placed record scores below
    an otherwise identical record placed any other way."""
    score = scoring.make_reverse_scorer(250.0, geocoded_penalty=0.9)
    origin = _point_origin()

    geocoded, _ = score(origin, _placed_hit("Geocoding"))
    parcel, _ = score(origin, _placed_hit("Parcel"))

    assert geocoded < parcel
    assert geocoded == parcel * 0.9


def test_the_penalty_is_reported_in_the_breakdown_only_when_it_fires():
    """Transparency, as elsewhere in §6.5/§10.6: a consumer reading
    matchScoreBreakdown (decision 92) can see the damping was applied, and
    sees no entry when it was not."""
    score = scoring.make_reverse_scorer(250.0, geocoded_penalty=0.9)
    origin = _point_origin()

    _, geocoded = score(origin, _placed_hit("Geocoding"))
    _, parcel = score(origin, _placed_hit("Parcel"))

    assert geocoded["geocoded_placement_penalty"] == 0.9
    assert "geocoded_placement_penalty" not in parcel


def test_the_placement_comparison_is_case_insensitive():
    """STA-006.3 §6.1 registry tokens arrive as provisioned text, so the match
    must not depend on the export's capitalisation."""
    score = scoring.make_reverse_scorer(250.0, geocoded_penalty=0.9)
    origin = _point_origin()

    for token in ("Geocoding", "geocoding", "GEOCODING", "  Geocoding  "):
        _, breakdown = score(origin, _placed_hit(token))
        assert "geocoded_placement_penalty" in breakdown, token


def test_an_unprovisioned_placement_is_not_damped():
    """Absence is not evidence of geocoding — a record with no Placement is
    left alone rather than assumed to be the worst case."""
    score = scoring.make_reverse_scorer(250.0, geocoded_penalty=0.9)

    _, breakdown = score(_point_origin(), _placed_hit(None))

    assert "geocoded_placement_penalty" not in breakdown


def test_the_penalty_is_configurable_and_1_0_disables_it():
    """What wiring GCS_GEOCODED_PLACEMENT_PENALTY buys: a deployment that does
    not want the damping sets 1.0 and the score is untouched."""
    origin = _point_origin()

    damped, _ = scoring.make_reverse_scorer(250.0, geocoded_penalty=0.5)(
        origin, _placed_hit("Geocoding")
    )
    disabled, _ = scoring.make_reverse_scorer(250.0, geocoded_penalty=1.0)(
        origin, _placed_hit("Geocoding")
    )
    baseline, _ = scoring.make_reverse_scorer(250.0)(origin, _placed_hit("Parcel"))

    assert damped == baseline * 0.5
    assert disabled == baseline


def test_lifecycle_binds_the_configured_penalty():
    """The wiring itself: runtime_state's value reaches the registered scorer,
    rather than make_reverse_scorer's default silently winning."""
    from src import runtime_state

    assert scoring.make_reverse_scorer(
        250.0, geocoded_penalty=runtime_state._geocoded_placement_penalty
    )(_point_origin(), _placed_hit("Geocoding"))[1][
        "geocoded_placement_penalty"
    ] == runtime_state._geocoded_placement_penalty
