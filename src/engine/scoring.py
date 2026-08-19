"""§6.5 forward scoring and §10.6 reverse spatial-fit — the formulas Appendix C
item (d) withheld, now written, plus the one refinement this module adds on
top of what the spec settled: a per-field weight that is MEASURED from the
deployment rather than guessed (src/gis/field_stats.py).

WHAT IS STILL A GUESS AND WHAT IS NOT

The base editorial weights (_BASE_WEIGHTS below) are this module's own guess
at which civic elements matter most when they disagree, and are exactly the
kind of number Appendix C item (d) says needs real match/non-match pairs
against data.gpkg to tune properly. Nothing here pretends otherwise — they are
named constants, not derived, and are the first thing to revisit once real
scored pairs exist.

What is NOT a guess: whether a given field is worth comparing at all in THIS
deployment. field_stats.py measures that directly off the loaded layer (1 -
the share of records holding that field's most common value), so a
statewide-ND deployment's Country="US" column contributes near nothing no
matter what _BASE_WEIGHTS says, without this module needing to know it is
looking at a single-state deployment.

THE FORMULA

    matchScore = 100 * sum(weight_i * similarity_i) / sum(weight_i)
                 for i in fields the QUERY populated

weight_i = _BASE_WEIGHTS[i] * field_stats.ssap_factor(i)  (or rcl_factor)

Restricting the sum to query-populated fields and renormalizing is what makes
an unsupplied County (or Country, or A1) cost nothing: CivicAddress.populated()
already exists to say what the caller actually asserted, and a field the
caller never mentioned is excluded from both the numerator and the
denominator rather than being scored as a mismatch or padded with a default.

ONE NORMALIZATION, THREE COMPARISON CLASSES (decision 28, closed by decision 82)

Every field is compared through the same primitive (_normalized_similarity
below) after the same normalization pass (_normalize_token). There is no
separate exact-match code path — an exact match is simply where that function
returns 1.0. What decision 82 settles is that one primitive answers three
different questions, and every civic element belongs to exactly one class:

  (1) IDENTITY GATES — Add_Number (decision 69) and UnitValue (decision 75).
      Not weighted terms at all: a differing value names a different
      building, so a disagreeing record never reaches this module.
      (Decision 71's street-name qualification and decision 73's digit-run
      identity test are gate-shaped too, but live inside the name
      comparison here rather than in candidates.py.)

  (2) CONTROLLED-VOCABULARY BINARY TERMS — St_Dir, A1, Country. Exact match
      after normalization scores 1.0, anything else 0.0
      (_normalized_similarity's binary=True). Ordinary weighted terms,
      never gates. See BINARY TERMS below.

  (3) HAND-TYPED NAME BLEND — St_Name, St_Type, Community, A2. Decision 72's
      Soundex/edit-distance blend, below, unchanged.

PHONETIC BLEND — hand-typed name fields only (decision 72)

Plain edit-distance similarity gives misleadingly high credit to short
strings that share characters and length but are different words —
"Del Rio" vs. "El Paso" scores 42.9% on edit distance alone, despite
sharing no meaningful sound. _normalized_similarity blends in a Soundex
comparison (_soundex below) for that reason: half edit-distance
similarity, half a binary phonetic match. A candidate that neither looks
nor sounds like the query should not score close to a real near-miss.

The blend is the default because most of what is compared here — Street
Name, Street Type, Community, County — is free text a human typed, so the
"does this plausibly sound like a typo of the right answer" question
applies to all of it. Class (2)'s three fields are the exception, and they
opt out with binary=True rather than with decision 72's original
phonetic=False: turning Soundex off but leaving edit distance on was itself
too generous, per decision 82 below.

BINARY TERMS — closed vocabularies (decision 82, supersedes 81)

St_Dir, A1 (state) and Country are not names a caller misspells; they are
short codes drawn from a closed set — eight directionals, a state
abbreviation, a country code — that a caller either states correctly or
does not. String similarity on a closed vocabulary is not merely unhelpful
but actively wrong, and the numbers are the argument: under decision 72's
treatment "NE" vs. "NW" scored 0.889 (NORTHEAST and NORTHWEST are
edit-similar AND share Soundex code N632 — near-full credit for opposite
quadrants), and "SD" vs. "ND" scored 0.50 on one shared character, which is
what Appendix C.4 Q30 originally complained about. Both are 0.0 under a
binary comparison, which is the honest answer.

Normalization still runs first — that is what the expansion tables are for,
so "N" and "NORTH" are the same value rather than a near-miss (see
_DIRECTIONAL_EXPANSIONS). Only the comparison after it is binary.

These are TERMS, NOT GATES, and that distinction is the whole of decision
82's revision of decision 81. Decision 81 briefly made A1 and Country
pre-scoring candidate-set gates; against a single-state export a hard A1
gate empties the candidate set outright for a caller who names the wrong
state — a live scenario here (Fargo across the river from Moorhead MN,
Pembina on the Canadian line), and the same confidently-wrong-about-
administrative-geography caller decision 80 protected at the community
level. A gate turns a query the remaining terms would have answered into a
468; a binary weighted term prices the mismatch honestly (0, not 50) and
leaves the candidate rankable. Those gates were reverted in-spec before
implementation, so no gate code was ever written and none belongs here.

St_Dir stays ONE term spanning both directional slots, compared
best-of-both-sides, so a pre/post swap ("Main Street North" for "North Main
Street") still takes full credit — the caller named the right street in
spoken order. A genuinely wrong directional zeroes the term: on weight 8 of
an ~82-weight denominator that is at most ~10 points off a perfect score,
enough to rank the candidate below a directional-correct competitor and not
enough to exclude it. A graduated swap penalty was considered and rejected
as invisible at that weight (decision 80's dilution lesson), as was
splitting St_Dir into two independent terms, which would double the
concept's denominator weight and re-create the cross-slot mismatch problem
best-of-sides exists to solve.

STREET NAME QUALIFIES CANDIDACY (decision 71)

Blending fixed the score but not the roster: a candidate on an unrelated
street ("El Paso" against a query for "Del Rio") still cleared a low
GCS_MIN_MATCH_SCORE, because the fields shared by every record in town
(street type, community, county) scored 100 and carried it. Live testing
showed those candidates are not merely low-ranked — they are misleading
to show at all, matching how production geocoders behave: the PostGIS
TIGER geocoder retrieves candidate streets through a Soundex-indexed
name lookup, so a name that does not phonetically match is never a
candidate, and edit distance only ranks the ones that qualified.

_street_name_qualifies below applies the same two-key test when both the
query and the record assert a street name: the candidate qualifies if the
names Soundex-match (catches misspellings that preserve the sound:
"Del Reo") OR reach _STREET_QUALIFY_MIN_EDIT_SIM edit similarity (catches
typos that break the sound, e.g. a wrong first letter, which Soundex
weights heavily). Failing both means the caller typed a different street,
not a typo of this one — the candidate's matchScore is forced to 0.0, so
it falls below any positive floor. The per-field breakdown is still
computed and reported, so a floor of 0 shows the disqualification rather
than hiding it. A record with no street name is NOT disqualified — data
sparseness costs score (the term drops out of the weighted average), not
candidacy, per decision 61's posture.

Street name only, for now. Community and county could in principle grow
the same gate, but street name is the primary retrieval key in every
production geocoder surveyed, and it is the field whose failure produced
visibly wrong results. Widen only on evidence.

DIGIT-LEADING STREET NAMES (decision 73, resolves Appendix C.4 Q32)

Soundex encodes letters only — a property of the algorithm itself, not this
implementation — so "2nd" and "22nd" strip to the same surviving letters
("ND") and share a Soundex code despite naming different streets. That is
invisible digit-blindness, not a tuning problem, and it produced two leak
patterns caught investigating an outlier (pair 1078, "1st" vs "12th") in the
labeled match/non-match sample set built for the decision 71-80 tuning work —
a since-removed scaffold; the finding stands, the generator does not. The two
patterns: a low-but-nonzero, non-gating score via the edit-similarity
key, and — more severely, because it grants full phonetic credit — a
Soundex-code collision via the phonetic key for pairs like "2nd"/"22nd".

_digit_leading_split below splits a normalized token into its leading digit
run and trailing suffix ("22ND" -> ("22", "ND")) whenever it begins with a
digit. _street_name_similarity then applies decision 73 wherever EITHER side
of a comparison is digit-leading: the digit runs (compared as integers, not
strings — deliberately mirroring decision 69's Add_Number gate, which
decision 73 draws its identity-gate framing from directly) must match
exactly or the pair is disqualified outright, the same shape as decision 69's
house-number gate and not a graded term — two differing digit runs are two
different streets, not a typo of one. Only once the digit runs agree does
edit-distance similarity run, and only against the letter suffix, with
Soundex never consulted anywhere in this path (the same reasoning decision
72 already applies to Country/A1: a 2-3 character ordinal suffix — ST, ND,
RD, TH — is too short for Soundex to say anything). A digit-leading side
paired with a purely alphabetic side (no digit run to compare) fails the
identity gate the same as two disagreeing digit runs — a numbered street and
a named one are never the same identity, confirmed rather than assumed
because it is not the case decision 73's own text works through.

This closes the SAME similarity value for both jobs decision 71 needs it
for: gating and the reported field score share one function
(_street_name_similarity) for a digit-leading pair, rather than the gate
testing raw edit similarity while the score separately blends in Soundex —
that divergence was the actual mechanism behind pair 1078's leak, not a
scale bug or a bypassed filter (see Q32). Neither side digit-leading falls
straight through to the pre-existing Soundex/edit-distance blend, completely
unaffected by any of this.

TRANSPOSITION-AWARE EDIT DISTANCE (decision 74)

Decision 73's own motivating example — "1st" mistyped as "1ts" — still
disqualified after decision 73 shipped: plain Levenshtein distance charges
an adjacent-character swap as two edits (delete+insert, or two
substitutions), not one, so "ST" -> "TS" scored 0% similarity on a
2-character suffix, below _STREET_QUALIFY_MIN_EDIT_SIM either way. That is
not a St_Name-specific problem — the same primitive underlies every
edit-distance comparison in this file — so decision 74 replaces
_edit_distance's algorithm rather than special-casing the suffix
comparison: it is Damerau-Levenshtein restricted to adjacent transpositions
only (the "optimal string alignment" form), never full unrestricted
Damerau-Levenshtein, which also prices non-adjacent transpositions as a
single edit and was ruled out of scope. One primitive, swapped once,
reused everywhere it already was: the free-text Soundex/edit-distance
blend, decision 73's digit-leading suffix comparison, and — as decision 74
was written — the then-pure-edit-distance categorical fields (Country, A1)
all see the new distance function automatically, with no per-field
branching. Decision 82 has since taken Country and A1 out of edit distance
entirely (see BINARY TERMS above), so that third case no longer exists;
decision 74's substitution stands unchanged for the two that remain.
Qualification
thresholds, blend weights, Soundex logic, and decision 73's digit-identity
gate are unchanged — a transposition still scores below an exact match, it
is priced more accurately, not forgiven.

COMMUNITY: ADMIN BEFORE POSTAL (decision 66, cascade shortened by decision 76)

Same shape as the Z-precedence chain (decision 51/55: geometry -> Altitude ->
Elevation) and the horizontal-position chain (decision 55: geometry over the
Longitude/Latitude columns) — a resolution cascade over which of several
candidate sources actually asserts the value, checked in a fixed order, first
populated wins. Here the concept is "what is this address's community" and
the order is A3 (incorporated municipality) -> A4 (unincorporated community)
-> Post_Comm (postal), reflecting where NENA/SI accuracy investment is
headed: as A3/A4 provisioning improves, matching shifts onto it automatically,
with no change needed here.

MSAGComm was originally a fourth tier here and is removed by decision 76: a
legacy pre-NG9-1-1 field this GCS does not rely on, and investigation found
it is reached by essentially no record in the provisioned data (1 of 78,237
SSAP records, where A3/A4/Post_Comm are all empty) — dropping it costs that
one record its Community comparison entirely, which falls through to the
same "sparseness costs score, not candidacy" handling as any other absent
field, not an error or a substitution.

THE DISCRIMINATIVE FACTOR NOW FOLLOWS THE RESOLVED FIELD (decision 76)

Before decision 76, the Community weight term's field_stats lookup was fixed
in code — f("A3") in score_ssap, f("Post_Comm") in score_rcl — regardless of
which cascade tier actually produced the value being compared. Investigation
found this mismatched a large share of records either way: 21.8% of SSAP
records resolve Community from Post_Comm, not A3, and were discounted
against A3's statistics instead of their own; RCL's mismatch was worse in
the other direction, since ~52.8% of RCL records per side resolve from A3
but were discounted against Post_Comm's statistics. field_stats measures
how discriminative a FIELD is in this deployment, so weighting a record's
Community term by the wrong field's factor is weighting it by a number that
has nothing to do with the value actually being compared.

_community_ssap and _community_rcl_side now return the resolved value
ALONGSIDE which field produced it (None, None where nothing in the cascade
is populated), so score_ssap and score_rcl can look up
field_stats.ssap_factor / rcl_factor for that specific field rather than a
name fixed in the source. For RCL's ambiguous-parity case (no side chosen,
both compared and the better similarity kept — see RCL SIDEDNESS below),
the factor follows whichever side's similarity won, the same side
_best_of_sides would have picked for the value itself.

THE SAME CORRECTION, EXTENDED TO THE TWO SLOT-SPANNING TERMS (decision 90)

St_Type and St_Dir have the identical shape as decision 76's Community bug,
in a different place: each spans a pair of record slots (St_PosTyp/St_PreTyp,
St_PreDir/St_PosDir) compared via _best_of_sides, which keeps whichever slot
scores better — but score_ssap and score_rcl weighted both terms by a slot
name fixed in source (f("St_PosTyp"), f("St_PreDir")), not by whichever slot
actually produced the winning similarity. Measured statewide: St_PosDir is
populated on 280,882 SSAP records against St_PreDir's 29,117 — roughly a
tenfold gap — with materially different factors (0.7465 against 0.6246), so
St_Dir's weight was following the statistics of the slot holding under a
tenth of the data.

_best_of_sides now returns (similarity, winning_field_name) instead of a bare
similarity, the same (value, field) shape decision 76 established for the
Community cascade, and score_ssap/score_rcl look up field_stats.ssap_factor /
rcl_factor against that name rather than one fixed in source. When both slots
score EQUALLY well the tie is broken by measured population — the larger
sample is the more meaningful statistic — and when populations tie too, the
fallback is the fixed order `left` (never a data-dependent coin flip); see
_best_of_sides's own docstring for the exact rule.

This does not change St_Type's behaviour today: St_PosTyp is the dominant
slot (409,234 populated SSAP records against St_PreTyp's 18,785), so the old
hardcoded f("St_PosTyp") was already reading the right statistics — by data
accident, not by construction. The correction is made anyway, because a
lookup that happens to be right only because of which slot a deployment's
data happens to favor is exactly the kind of assumption the measured-factor
design exists to avoid re-introducing; leaving St_Type alone would have kept
a second latent instance of the defect decision 90 fixes for St_Dir.

RCL's St_Type/St_Dir correction is entirely independent of `side` (RCL
SIDEDNESS, below): those two fields are RCL's UNSIDED "shared" columns (one
value per segment, never an _L/_R pair — see field_stats._RCL_SHARED), so
their slot-name lookup never crosses the L/R administrative-attribution
boundary `side` resolves. The two "which of two things produced this value"
questions are unrelated by construction, not merely by coincidence of this
implementation.

COMMUNITY MISMATCH CAPS THE TERM, IT DOES NOT DISQUALIFY (decision 80, supersedes 77)

Decision 77 made Community a candidacy gate in decision 71's exact shape: a
resolved Community value that neither sounds like nor closely resembles the
query's forced the whole matchScore to 0. That is reverted here. Community
returns to being an ordinary weighted-average term (decision 76's weight —
_BASE_WEIGHTS["Community"] times the discriminative factor of whichever
cascade field resolved the value), and the disqualification is replaced by a
CAP on what that one term may contribute.

The distinction being drawn is between the two fields' error modes, not a
retreat from decision 77's finding that reweighting alone was measurably
insufficient. A street name that neither sounds nor looks like the query is
positive evidence of a different address — decision 71's own PostGIS/TIGER
precedent is that such a record is never a candidate at all. A community name
that disagrees is weaker evidence than that: the query side is frequently
where the error is (a caller naming the nearby town they know rather than the
incorporated municipality the parcel is actually in, a mailing city that is
not the A3 value, an unincorporated place called by the name of the township
around it), and the record's own A3/A4/Post_Comm cascade can legitimately
resolve to a name the caller would never have said. Forcing the score to 0
throws away a candidate whose street name, house number, and county all
agree, on the strength of the one element most likely to be miscommunicated.

_community_qualifies is retained UNCHANGED — the same two-key Soundex-or-edit
-similarity test decision 77 authored, with the same
_COMMUNITY_QUALIFY_MIN_EDIT_SIM threshold and the same sparseness carve-out
(either side missing means no opinion). Only its consequence changes: failing
it now clamps the Community term's similarity to
_COMMUNITY_MISMATCH_SIMILARITY_CAP instead of zeroing the candidate. A
qualifying Community is untouched — the Soundex/edit-distance blend of
decision 72 reports it exactly as before, and the cap never raises a
similarity, only lowers one (it is a min, not an assignment), so a
non-qualifying pair that the blend already scored below the cap keeps its
lower value.

Why a cap rather than simply trusting the blend: the blend's floor for a
genuinely different town is not low enough to be self-suppressing. Two
unrelated ND town names still collect partial edit-distance credit for shared
letters and length, which is the same overcrediting decision 72's docstring
describes for "Del Rio"/"El Paso" — the phonetic half of the blend zeroes,
but the edit half does not, so a wrong town lands in the tens rather than
near zero. The cap is what makes "the caller named a different place" cost a
fixed, known amount instead of an amount that depends on how many letters two
unrelated names happen to share.

The cap VALUE has been swept, not merely placed — see
_COMMUNITY_MISMATCH_SIMILARITY_CAP's own comment for the result. It is a
negative one: a sweep of [0.0, 0.15, 0.3, 0.5] against 250 labeled
wrong_community pairs found the mean moves only from 91.63 (cap 0.0) to 92.18
(cap 0.5), with 100% of pairs still clearing GCS_MIN_MATCH_SCORE at every
value tried — Community is one term of a seven-term average, and the other six
score 100 in a wrong_community pair by construction, so no per-term clamp
dilutes the result far enough to matter. 0.15 is kept not because it
outperformed the alternatives (it did not, meaningfully) but because nothing
in the tested range did. (The sweep tooling and its pair set were scaffolding
for decisions 71-80 and have been removed now that those are settled; the
result is recorded in decision 80 itself, which is the durable record of it.)

The mechanism that could actually move this number — a penalty applied to the
whole matchScore after the average, rather than to one term inside it — was
considered and DECLINED by decision 86, not left open. The two populations it
would need to separate are identical in the data: a legitimately-confused
caller's true match and a genuine wrong-community false positive have the same
field-score shape by construction (same street, same house number,
non-matching community), so no scalar computed from those fields can tell them
apart. What separates them is ranking, which already does it — see decision 86
for the three cases that exhaust the space.

PERFORMANCE NOTE — decision 61 removed the §6.2 filter, so every temporally
valid record in the layer is scored on every request. _normalized_similarity
short-circuits on an exact string match (the dominant case for well-formed
data) before running the edit-distance DP, but a full statewide layer scored
field-by-field on every request has not been benchmarked against data.gpkg.
Worth an actual timing pass before this goes into a high-QPS deployment.
"""

from __future__ import annotations

from typing import Mapping, Optional

from src.engine.models import CivicAddress, Side
from src.gis import field_stats
from src.gis.records import RCLRecord, SSAPRecord
from src.reverse.origin import SearchOrigin
from src.reverse.search import Hit

# ---------------------------------------------------------------------------
# Base editorial weights — GUESSES pending real tuning (Appendix C item (d))
# ---------------------------------------------------------------------------

#: Forward (§6.5) concept weights. Keys are the *concept* names used below,
#: not raw column names — "Community" is the resolved cascade value, not any
#: one column.
_BASE_WEIGHTS: dict[str, float] = {
    # Add_Number is deliberately absent: decision 69 made it a hard
    # candidate-set gate in src/geocode/candidates.py's ssap_candidates(),
    # not a graded similarity term. Every SSAP candidate that reaches this
    # function already has an exact house-number match, so including it
    # here would only ever contribute a constant 1.0 — never discriminate
    # among survivors, only add dead weight to the denominator.
    "St_Name": 30.0,
    "St_Type": 12.0,      # St_PreTyp / St_PosTyp, compared as one concept
    "St_Dir": 8.0,        # St_PreDir / St_PosDir, compared as one concept
    "Community": 15.0,    # the A3->A4->Post_Comm cascade (decision 76)
    "A2": 10.0,           # county — rarely supplied, but counts when it is
    "A1": 5.0,            # state
    "Country": 2.0,
}

#: Default for GCS_GEOCODED_PLACEMENT_PENALTY, which src/app/lifecycle.py binds
#: at scorer registration. Kept here so make_reverse_scorer() is usable without
#: the environment (tests, tools).
#:
#: SETTLED EDITORIAL DEFAULT, NOT A STRAWMAN (decision 83) — unlike the
#: constants below it, this one is off Appendix C item (d)'s open list, and
#: two facts put it there. First, it cannot change any answer: §10.3 orders
#: lexicographically on containment, then tier, then distance, and spatial fit
#: is not a term in that ordering, so the penalty moves the reported
#: spatial-fit number (and confidence, which is that number scaled to the tier
#: ceiling) and nothing else — never the candidate order, never admission,
#: never a 200 into a 468. Second, and because of that, there is nothing to
#: sweep it against: the sweeps decisions 79 and 80 ran needed a labeled
#: outcome, and STA-006.3's Placement registry records only THAT a placement
#: was derived by geocoding, never the error magnitude of that derivation —
#: which is a property of whatever geocoder the SI ran against whatever
#: reference data it held. A future session should not re-open this looking
#: for a sweep; the sweep cannot be built, and its absence is not an oversight.
#:
#: What 0.9 says: a Geocoding-placement candidate reports roughly a tenth less
#: spatial fit than an otherwise identical candidate placed by survey,
#: structure, or parcel — visible in the number, deliberately short of
#: implying a known error magnitude. Since the honest value depends on the
#: quality of the SI's own geocoding rather than on anything the GCS can
#: observe, the env binding is the tuning mechanism, not a better default: a
#: deployment that knows its geocoded placements are poor lowers it, one that
#: knows they are good raises it toward 1.0, and the shipped value assumes
#: neither.
_GEOCODED_PLACEMENT_PENALTY = 0.9

#: Decision 71 — the edit-similarity floor a street name must reach to keep a
#: candidate alive when Soundex disagrees. 0.5 admits a wrong-first-letter
#: typo of a short name ("Fel Rio" for "Del Rio" is 0.857) while rejecting
#: unrelated names that coincidentally share letters ("El Paso" is 0.429,
#: "Domino" 0.286). A strawman like the other constants here — Appendix C
#: item (d) — pending real match/non-match pairs.
_STREET_QUALIFY_MIN_EDIT_SIM = 0.5

#: Decision 77 — the edit-similarity floor a Community value must reach to
#: keep a candidate alive when Soundex disagrees, mirroring decision 71's
#: street-name gate. Deliberately a SEPARATE constant from
#: _STREET_QUALIFY_MIN_EDIT_SIM, not a shared reference to it: street names
#: and community names have different typo/collision profiles, and no
#: evidence yet justifies assuming they share a threshold. Same strawman
#: starting value (0.5) for the same reason decision 71's is a strawman —
#: both are Appendix C item (d) placeholders pending real match/non-match
#: pairs, and this one is independently tunable from here on.
_COMMUNITY_QUALIFY_MIN_EDIT_SIM = 0.5

#: Decision 80 (supersedes 77) — the ceiling the Community term's similarity is clamped
#: to when _community_qualifies says no, replacing decision 77's outright
#: disqualification (see COMMUNITY MISMATCH CAPS THE TERM in the module
#: docstring). Applied as a min(), so it lowers a similarity and never raises
#: one.
#:
#: SWEPT, NOT TUNABLE INTO A WIN — a sweep across [0.0, 0.15, 0.3, 0.5]
#: against 250 labeled wrong_community pairs returned a negative result: mean
#: ranged only from 91.63 (cap 0.0) to 92.18 (cap 0.5), and 100% of pairs
#: still cleared GCS_MIN_MATCH_SCORE at every value tried, because Community
#: is one term of a seven-term average and the other six score 100 in a
#: wrong_community pair by construction — no cap value dilutes the average far
#: enough to matter. 0.15 is kept because nothing tested did meaningfully
#: better, not because it won. Decision 80 records the sweep in full; the
#: tooling that produced it was scaffolding and has been removed, so re-running
#: it is not a thing this repository can do (nor a thing worth doing).
#:
#: This cap structurally cannot move that number, and the mechanism that could
#: — a whole-score post-average penalty — is DECLINED by decision 86, not open.
#: Do not reintroduce it: it cannot separate the two populations, because they
#: are identical in the field scores it would compute from.
_COMMUNITY_MISMATCH_SIMILARITY_CAP = 0.15


# ---------------------------------------------------------------------------
# Similarity primitive (one mechanism, decision 28)
# ---------------------------------------------------------------------------

#: Directional normalization so "N" and "North" resolve to the SAME value.
#: Under decision 82 this table is no longer a convenience that saves edit
#: distance from bridging a gap that isn't a typo — it is the entire
#: vocabulary the St_Dir comparison has, because that comparison is now
#: binary (exact match after normalization, 1.0 or 0.0). A directional this
#: table fails to fold onto its canonical form scores 0, not "close"; there
#: is no fuzzy fallback behind it any more. Checked against
#: every St_PreDir/St_PosDir value actually populated in data.gpkg (SSAP and
#: RCL): NORTH, SOUTH, EAST, WEST, NORTHEAST, NORTHWEST, SOUTHEAST, SOUTHWEST
#: are the only eight values present, and all eight are covered below — no
#: gap found, so nothing was added here (widen only on evidence, same as
#: decision 73's posture).
_DIRECTIONAL_EXPANSIONS: dict[str, str] = {
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
    "NE": "NORTHEAST", "NW": "NORTHWEST", "SE": "SOUTHEAST", "SW": "SOUTHWEST",
}

#: Street-type normalization so "St" and "Street" compare as equal rather
#: than relying on edit distance to bridge a gap that isn't a typo. Every
#: entry is the USPS Publication 28 Appendix C1 "Postal Service Standard
#: Suffix Abbreviation" for that primary name, verified directly against
#: Postal Explorer (pe.usps.com/text/pub28/pub28apc_002.htm) and
#: cross-checked against the NENA Street Name Pre/Post Types registry
#: (technet.nena.org/nrs/registry/StreetNamePreTypesAndStreetNamePostTypes.xml),
#: which tags every one of these values with Source "USPS Pub 28".
#:
#: Widened against data.gpkg's actual St_PosTyp/St_PreTyp population (a
#: prior "starter set... worth widening" self-flag) — BEND -> BND and
#: ESTATE -> EST were added here specifically because that check turned out
#: to contradict an earlier assumption that neither had a standard
#: abbreviation; both do, confirmed against the primary source rather than
#: taken on faith.
#:
#: Deliberately NOT added, checked and rejected rather than overlooked:
#:   LOOP, RAMP, ROW — USPS Pub 28 lists these as valid primary suffix names,
#:     but the Postal Service Standard Suffix Abbreviation column is
#:     IDENTICAL to the primary name (no shorter form exists to add).
#:   COUNTY ROAD, INTERSTATE — St_PreTyp values in the provisioned data
#:     (115 and 204 records). These are route/jurisdiction designators, not
#:     USPS mail-delivery suffixes, and the NENA registry confirms it:
#:     both are registered values, but with Source "State of NY", not
#:     "USPS Pub 28" — there is no abbreviation table backing either one,
#:     so none is invented here.
#:   BIA ROUTE (80 records) — same reasoning. The NENA registry's canonical
#:     value is "Bureau of Indian Affairs Route" (Source "State of
#:     Montana"), not USPS Pub 28; "BIA" is common real-world usage but has
#:     no registry- or Pub-28-backed abbreviation entry to cite.
_TYPE_EXPANSIONS: dict[str, str] = {
    "ST": "STREET", "AVE": "AVENUE", "BLVD": "BOULEVARD", "DR": "DRIVE",
    "LN": "LANE", "RD": "ROAD", "CT": "COURT", "PL": "PLACE", "CIR": "CIRCLE",
    "TER": "TERRACE", "HWY": "HIGHWAY", "PKWY": "PARKWAY", "WAY": "WAY",
    "TRL": "TRAIL", "EXPY": "EXPRESSWAY", "BYP": "BYPASS", "CRES": "CRESCENT",
    "SQ": "SQUARE", "XING": "CROSSING", "RDG": "RIDGE", "JCT": "JUNCTION",
    "ALY": "ALLEY", "PT": "POINT", "BND": "BEND", "EST": "ESTATE",
}


def _normalize_token(value: Optional[str], expansions: Mapping[str, str] = {}) -> str:
    """Casefold, strip, and apply a domain expansion table where the whole
    token matches an abbreviation. Falls through unchanged otherwise —
    normalization closes a known vocabulary gap, it does not guess at one."""
    if value is None:
        return ""
    token = value.strip().upper()
    return expansions.get(token, token)


def _edit_distance(a: str, b: str) -> int:
    """Decision 74 — Damerau-Levenshtein restricted to adjacent transpositions
    only (the "optimal string alignment" form, NOT full unrestricted
    Damerau-Levenshtein, which also prices non-adjacent transpositions as one
    edit and is out of scope here). Swapping two adjacent characters costs 1
    edit instead of the 2 (delete+insert, or two substitutions) plain
    Levenshtein charges it — "1ST" -> "1TS" (decision 73's own motivating
    typo case) is 1 edit here, not 2.

    OSA is not a true metric (it can violate the triangle inequality on
    inputs that reuse a substring across a transposition and a later edit —
    a known, accepted limitation of the restricted form, and precisely why
    decision 74 scopes this to adjacent transpositions rather than full
    Damerau-Levenshtein), but nothing in this module relies on the triangle
    inequality: every caller just wants "how many edits apart are these two
    short tokens," and OSA answers that correctly for the adjacent-swap case
    this exists for.

    No new dependency pinned for this (requirements.txt carries none of
    rapidfuzz/python-Levenshtein/jellyfish today) — swapping in one of those
    is a cheap win if profiling against data.gpkg shows this loop matters,
    and worth doing before a large-layer deployment; this is
    correctness-first, not the fast path.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,       # deletion
                d[i][j - 1] + 1,       # insertion
                d[i - 1][j - 1] + cost,  # substitution (0 if equal)
            )
            if (
                i > 1 and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)  # adjacent transposition
    return d[la][lb]


_SOUNDEX_CODES: dict[str, str] = {
    "B": "1", "F": "1", "P": "1", "V": "1",
    "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
    "D": "3", "T": "3",
    "L": "4",
    "M": "5", "N": "5",
    "R": "6",
}


def _soundex(token: str) -> str:
    """Classic 4-character Soundex code, letters-only (digits and punctuation
    ignored — street names like "5TH" code on "TH"). Empty string if the
    token has no letters at all, signalling "no phonetic opinion" to the
    caller rather than a fabricated code."""
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return ""
    result = [letters[0]]
    prev_code = _SOUNDEX_CODES.get(letters[0], "")
    for c in letters[1:]:
        if c in ("H", "W"):
            # Transparent to the duplicate-code merge below, per the
            # standard algorithm: "Ashcraft" codes the two C-equivalents
            # as one because only H separates them.
            continue
        code = _SOUNDEX_CODES.get(c, "")
        if code and code != prev_code:
            result.append(code)
        prev_code = code
    return "".join(result)[:4].ljust(4, "0")


def _normalized_similarity(
    a: Optional[str], b: Optional[str], *, expansions: Mapping[str, str] = {},
    phonetic: bool = True, binary: bool = False,
) -> Optional[float]:
    """1.0 exact, 0.0 completely dissimilar, None if either side has nothing
    to compare (caller excludes None from the weighted sum rather than
    treating it as a mismatch).

    phonetic=True (the default) blends in a Soundex comparison so a
    candidate that neither looks nor sounds like the query cannot coast on
    edit distance's leniency toward short, coincidentally-similar strings —
    see PHONETIC BLEND in the module docstring.

    binary=True (decision 82) is the class-(2) comparison for closed
    vocabularies — St_Dir, A1, Country. Normalization still runs, including
    the expansion table, and the None contract is identical; only the
    comparison afterwards changes, to a plain equality test returning 1.0 or
    0.0 with no edit distance and no Soundex. It short-circuits ahead of both,
    so `phonetic` says nothing when binary=True — binary takes precedence,
    deliberately rather than by accident: there is no coherent reading of
    "blend a Soundex code into an identity test," and forbidding the
    combination at the signature would buy a caller error nobody is making at
    the cost of a keyword-argument dance in _best_of_sides.
    """
    if a is None or b is None:
        return None
    na, nb = _normalize_token(a, expansions), _normalize_token(b, expansions)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0
    if binary:
        # Decision 82 — a closed-vocabulary value that is not the value is not
        # a near-miss of it. "NE" vs "NW" is 0.0 here; the blend scored it
        # 0.889 (see BINARY TERMS in the module docstring).
        return 0.0
    distance = _edit_distance(na, nb)
    longest = max(len(na), len(nb))
    edit_similarity = max(0.0, 1.0 - distance / longest)
    if not phonetic:
        return edit_similarity
    sa, sb = _soundex(na), _soundex(nb)
    if not sa or not sb:
        return edit_similarity
    phonetic_match = 1.0 if sa == sb else 0.0
    return 0.5 * edit_similarity + 0.5 * phonetic_match


def _digit_leading_split(token: str) -> Optional[tuple[str, str]]:
    """Decision 73 — split an already-NORMALIZED token into (digit_run,
    suffix) when it begins with one or more digits: "22ND" -> ("22", "ND").
    None for a token that does not begin with a digit — a plain alphabetic
    token, unaffected by decision 73's path.

    The suffix is whatever follows the digit run, not necessarily
    letters-only — data.gpkg carries values like "10 1/2" — and that is fine:
    the suffix is compared by generic edit-distance similarity below, which
    has no letters-only requirement.
    """
    i = 0
    while i < len(token) and token[i].isdigit():
        i += 1
    if i == 0:
        return None
    return token[:i], token[i:]


def _street_name_similarity(query_name: Optional[str], record_name: Optional[str]) -> Optional[float]:
    """Decision 73 — the ONE street-name similarity value used for both the
    qualification gate and the reported field score when either side is
    digit-leading, closing the gate-vs-score divergence Q32 traces pair
    1078's leak to. Same None/0.0/1.0 contract as _normalized_similarity:
    None when there is nothing to compare, 0.0 for a decision-73 identity-gate
    failure (not a graded low score), 1.0 for a normalized exact match.

    Falls straight through to the existing Soundex/edit-distance blend,
    completely unchanged, when NEITHER side begins with a digit.
    """
    if query_name is None or record_name is None:
        return None
    na, nb = _normalize_token(query_name), _normalize_token(record_name)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0

    split_a, split_b = _digit_leading_split(na), _digit_leading_split(nb)
    if split_a is None and split_b is None:
        return _normalized_similarity(query_name, record_name)

    if split_a is None or split_b is None:
        # One side is digit-leading, the other purely alphabetic — no digit
        # run on that side to agree with, so the identity gate fails the same
        # as two disagreeing digit runs (confirmed rather than assumed; see
        # decision 73's docstring note above).
        return 0.0

    run_a, suffix_a = split_a
    run_b, suffix_b = split_b
    # Integer comparison, not string, deliberately mirroring decision 69's
    # own Add_Number gate. No leading-zero digit run exists anywhere in the
    # currently provisioned data.gpkg (checked directly), so this is
    # unexercised today, but it costs nothing and avoids a latent "02" != "2"
    # false disqualification without inventing a bespoke string-normalization
    # rule for a case the data does not present.
    if int(run_a) != int(run_b):
        return 0.0

    # Digit runs agree — decision 73: compare ONLY the suffix, by edit
    # distance alone, no Soundex (see DIGIT-LEADING STREET NAMES above).
    # None here (e.g. "10" vs "10TH", one side with no suffix at all) means
    # nothing left to compare once identity is confirmed — sparseness costs
    # score, not candidacy, same as everywhere else in this module.
    return _normalized_similarity(suffix_a, suffix_b, phonetic=False)


def _street_name_qualifies(query_name: Optional[str], record_name: Optional[str]) -> bool:
    """Decision 71 (amended by decision 73) — whether a record's street name
    keeps the candidate alive.

    False when BOTH sides assert a name and: neither is digit-leading and
    the record's name is neither phonetically equivalent (Soundex) nor
    within _STREET_QUALIFY_MIN_EDIT_SIM edit similarity of the query's; OR
    either side is digit-leading and _street_name_similarity's decision-73
    identity gate/suffix comparison falls below that same threshold. Either
    side missing means no opinion — sparseness costs score, not candidacy.
    """
    if query_name is None or record_name is None:
        return True
    na, nb = _normalize_token(query_name), _normalize_token(record_name)
    if not na or not nb or na == nb:
        return True

    if _digit_leading_split(na) is not None or _digit_leading_split(nb) is not None:
        similarity = _street_name_similarity(query_name, record_name)
        return similarity is None or similarity >= _STREET_QUALIFY_MIN_EDIT_SIM

    sa, sb = _soundex(na), _soundex(nb)
    if sa and sb and sa == sb:
        return True
    distance = _edit_distance(na, nb)
    longest = max(len(na), len(nb))
    return (1.0 - distance / longest) >= _STREET_QUALIFY_MIN_EDIT_SIM


# ---------------------------------------------------------------------------
# Community cascade — same shape as decision 51/55's Z and position chains
# ---------------------------------------------------------------------------

def _community_query(query: CivicAddress) -> Optional[str]:
    return query.A3 or query.A4 or query.Post_Comm


def _community_ssap(record: SSAPRecord) -> tuple[Optional[str], Optional[str]]:
    """Decision 76 — the resolved value AND which cascade field produced it,
    so the caller can weight by that field's own discriminative factor
    rather than one fixed in code. (None, None) when nothing in the
    cascade is populated."""
    if record.A3:
        return record.A3, "A3"
    if record.A4:
        return record.A4, "A4"
    if record.Post_Comm:
        return record.Post_Comm, "Post_Comm"
    return None, None


def _community_rcl_side(record: RCLRecord, side: Side) -> tuple[Optional[str], Optional[str]]:
    """Decision 76 — same contract as _community_ssap, one RCL side."""
    s = side.value  # "L" or "R"
    a3 = getattr(record, f"A3_{s}", None)
    if a3:
        return a3, "A3"
    a4 = getattr(record, f"A4_{s}", None)
    if a4:
        return a4, "A4"
    post_comm = getattr(record, f"PostComm_{s}", None)
    if post_comm:
        return post_comm, "Post_Comm"
    return None, None


def _community_qualifies(query_value: Optional[str], record_value: Optional[str]) -> bool:
    """Decision 77's qualification TEST, unchanged — but no longer decision
    77's qualification GATE. The test is the same two keys decision 77
    authored (Soundex equivalence OR _COMMUNITY_QUALIFY_MIN_EDIT_SIM edit
    similarity, mirroring decision 71's street-name test with its own
    independent threshold); what changed is the consequence of failing it.
    Failing no longer forces matchScore to 0 — it clamps the Community term's
    similarity contribution to _COMMUNITY_MISMATCH_SIMILARITY_CAP, via
    _capped_community_similarity below. See COMMUNITY MISMATCH CAPS THE TERM
    in the module docstring for why Community and street name are treated
    differently here despite decision 77 having deliberately made them alike.

    False only when BOTH sides assert a value and it is neither
    phonetically equivalent (Soundex) nor within
    _COMMUNITY_QUALIFY_MIN_EDIT_SIM edit similarity. Either side missing —
    the query didn't supply a community, or decision 76's cascade resolved
    to nothing for this record — means no opinion, and the Community term
    is neither capped nor scored: sparseness costs score, not candidacy,
    the same carve-out decision 71 and decision 75 already establish.

    No digit-leading branch here, unlike _street_name_qualifies: decision
    73's own investigation found zero digit-leading values across every
    Community field in the provisioned data (A3, A4, Post_Comm, MSAGComm,
    both SSAP and RCL, both sides) — that machinery has nothing to do for
    this field. Widen only on evidence, per decision 73's posture.
    """
    if query_value is None or record_value is None:
        return True
    na, nb = _normalize_token(query_value), _normalize_token(record_value)
    if not na or not nb or na == nb:
        return True
    sa, sb = _soundex(na), _soundex(nb)
    if sa and sb and sa == sb:
        return True
    distance = _edit_distance(na, nb)
    longest = max(len(na), len(nb))
    return (1.0 - distance / longest) >= _COMMUNITY_QUALIFY_MIN_EDIT_SIM


def _capped_community_similarity(
    similarity: Optional[float], query_value: Optional[str], record_value: Optional[str]
) -> Optional[float]:
    """The one place the Community mismatch cap is applied, shared by
    score_ssap and score_rcl so there is a single mechanism to reason about
    (decision 28's posture) rather than the rule being written out twice.

    Takes the similarity the caller ALREADY computed rather than computing it
    here, because the two callers arrive at it differently: score_ssap has one
    record-side value, while score_rcl may have compared both sides and kept
    the better one. Passing the winning similarity in — alongside the exact
    value it was measured against — keeps the cap decision and the reported
    score committed to the same side, which is the invariant decision 76 and
    decision 77 both already depend on.

    None passes straight through: nothing to compare means the term drops out
    of the weighted average entirely, and capping absence would silently
    convert decision 61's sparseness posture into a penalty.
    """
    if similarity is None:
        return None
    if _community_qualifies(query_value, record_value):
        return similarity
    # min, not assignment — the cap is a ceiling. A wrong town the blend
    # already scored below the cap keeps its own lower score rather than
    # being lifted up to the cap.
    return min(similarity, _COMMUNITY_MISMATCH_SIMILARITY_CAP)


# ---------------------------------------------------------------------------
# RCL sidedness at scoring time
# ---------------------------------------------------------------------------
#
# Scoring runs before position derivation — rcl_candidates() in
# src/geocode/candidates.py calls score(query, record) ahead of
# position_derivation.interpolate() — and needs a side for the administrative
# and postal comparisons. It resolves one the same way §7.2 does: from the
# query's Add_Number parity (odd/even) against the record's Parity_L/Parity_R.
#
# ONE RULE, CONSULTED TWICE (decision 67, adopted formally by decision 87)
#
# This is not a second mechanism racing §7.2's. Decision 87 read §7.2 and §7.3
# directly and found the premise of the conflict false: §7.3 applies the
# setback "on the side determined by the matched address parity" and §7.2 has
# Parity_L/R govern "which side of the segment a house number belongs to," so
# forward side selection was already parity-based at both ends. Decision 67
# independently reached the rule already in force, earlier in the pipeline,
# rather than inventing a rival to it. Two applications of one rule to one set
# of inputs cannot disagree, so there is no cross-check to build here.
#
# (The reverse direction resolves side by projecting the origin instead — §11.2
# and §11.3 — because a reverse request carries no house number to read parity
# from. That is a difference in available input, not a competing policy.)
#
# THE FALLBACKS DIVERGE, DELIBERATELY (decision 87)
#
# Where parity does NOT resolve a side (no Add_Number in the query, or a record
# whose Parity_L/R does not decide it), this module compares both sides per
# element and keeps the better similarity — never committing to a wrong side,
# because it does not commit at all. §7.2, needing a position rather than a
# comparison, lets the asserted range govern instead. The two can therefore
# land on different sides for one record, which decision 80's requirement that
# scoring commit to a side for reporting makes visible: the per-field breakdown
# would describe one side while the position derived from the other.
#
# Decision 87 accepts that divergence rather than reconciling it, on cost
# grounds. Reaching it at all requires a record whose parity field is null or
# contradicts its own address range — a GIS data-quality defect §7.2 already
# declines to repair, on the same grounds §11.3 and §11.4 decline to repair
# sparse attribution. Where the provisioned data is well-formed the two ends
# agree by construction, so importing a range-containment cascade into the
# scorer to align them would be dead code in every correct case. Do not "fix"
# this without reading decision 87 first.

def _rcl_side_hint(query: CivicAddress, record: RCLRecord) -> Optional[Side]:
    if query.Add_Number is None:
        return None
    parity = "E" if query.Add_Number % 2 == 0 else "O"
    left, right = record.Parity_L, record.Parity_R
    if left is not None and left.strip().upper().startswith(parity) and (
        right is None or not right.strip().upper().startswith(parity)
    ):
        return Side.LEFT
    if right is not None and right.strip().upper().startswith(parity) and (
        left is None or not left.strip().upper().startswith(parity)
    ):
        return Side.RIGHT
    return None


def _best_of_sides(
    a: Optional[str], left: Optional[str], right: Optional[str], *,
    left_field: str, right_field: str,
    left_population: int = 0, right_population: int = 0,
    expansions: Mapping[str, str] = {}, phonetic: bool = True, binary: bool = False,
) -> tuple[Optional[float], Optional[str]]:
    """Compare one query value against two record slots and keep the better
    result, reporting WHICH slot produced it. Used for two structurally
    different "two slots" cases: the RCL left/right sides, and the pre/post
    street-type and street-direction slots on either layer.

    `binary` threads through for decision 82's St_Dir term, where the
    best-of-both-sides structure is what gives a pre/post position swap
    ("Main Street North" for "North Main Street") full credit under an
    otherwise exact-match comparison — the query's one directional matches
    exactly against whichever slot the record actually populated.

    RETURNS (similarity, winning_field_name), (None, None) if neither slot
    yields a comparison. Decision 90 — this is decision 76's "report which
    field produced the value, so the caller can weight by THAT field's own
    discriminative factor" contract, extended from the Community cascade to
    the two terms that span a slot pair rather than a cascade. Callers that
    do not need the winning name (score_rcl's ambiguous-side A2/A1/Country
    lookup, which uses one pooled factor regardless of side) simply discard
    it.

    TIE RULE (decision 90): when both slots score EQUALLY well, the slot
    with the larger measured population wins — passed in by the caller as
    left_population/right_population (field_stats.ssap_population /
    rcl_population; this helper takes raw counts rather than looking them up
    itself, so it stays agnostic to which layer's population table applies).
    A larger population is the more meaningful measurement, and picking on
    that basis is deterministic rather than left to Python's iteration or
    dict order. When both populations are ALSO equal (including the default
    0/0 a caller passes when it doesn't care), the fixed, documented
    fallback is `left` — never a data-dependent coin flip.
    """
    left_sim = _normalized_similarity(a, left, expansions=expansions, phonetic=phonetic, binary=binary)
    right_sim = _normalized_similarity(a, right, expansions=expansions, phonetic=phonetic, binary=binary)

    if left_sim is None and right_sim is None:
        return None, None
    if right_sim is None or (left_sim is not None and left_sim > right_sim):
        return left_sim, left_field
    if left_sim is None or right_sim > left_sim:
        return right_sim, right_field
    # left_sim == right_sim — decision 90's tie rule.
    if left_population >= right_population:
        return left_sim, left_field
    return right_sim, right_field


# ---------------------------------------------------------------------------
# §6.5 forward scoring
# ---------------------------------------------------------------------------

def _weighted_average(
    terms: Mapping[str, tuple[Optional[float], float]]
) -> tuple[float, dict[str, float]]:
    """terms: concept -> (similarity_or_None, weight). Sums only the concepts
    with a similarity (i.e. the query populated something to compare), then
    renormalizes by the weight actually used."""
    breakdown: dict[str, float] = {}
    weighted_sum = 0.0
    weight_total = 0.0
    for concept, (similarity, weight) in terms.items():
        if similarity is None or weight <= 0:
            continue
        breakdown[concept] = round(similarity * 100.0, 2)
        weighted_sum += similarity * weight
        weight_total += weight
    if weight_total == 0.0:
        # Nothing comparable in the query. Stage 0 admission (§4.1) already
        # requires at least one civic location; a query that clears that but
        # supplies nothing this scorer recognises is a real edge case worth
        # surfacing rather than silently reporting a perfect or zero score.
        return 0.0, breakdown
    # Clamped, not just computed: 100.0 * weighted_sum / weight_total is
    # mathematically <= 100.0 whenever every similarity is, but float
    # summation across several weighted terms is not associative, so an
    # all-1.0 match can land a few ulps past 100.0 (found by the regression
    # suite's real-data rung-2 interpolation case, tests/regression/). That
    # overshoot would otherwise trip MatchQuality's strict range check
    # (models.py __post_init__) and crash the request with an uncaught
    # ValueError — a bare 500 outside §2.1's closed status set, on a request
    # that should cleanly answer 200. The similarity inputs are themselves
    # already clamped to [0, 1] upstream, so clamping only the float-noise
    # margin here changes no scoring decision.
    return min(100.0, max(0.0, 100.0 * weighted_sum / weight_total)), breakdown


def score_ssap(query: CivicAddress, record: SSAPRecord) -> tuple[float, Mapping[str, float]]:
    """§6.5 for an SSAPRecord (rung 1). Add_Number is not scored here — it
    is a hard gate in ssap_candidates() (decision 69), so every record
    reaching this function already matches exactly; reported in the
    breakdown as a fixed 100.0 for transparency, not included in the
    weighted average."""
    f = field_stats.ssap_factor
    pop = field_stats.ssap_population
    query_community = _community_query(query)
    community_value, community_field = _community_ssap(record)
    # Decision 90 — St_Type and St_Dir span a pre/post slot pair the same
    # way Community spans a cascade: the factor must follow whichever slot
    # actually produced the compared value, not a slot name fixed in
    # source. Resolved ahead of `terms` so the weight lookup below can use
    # the winning field, mirroring community_field's role just above.
    st_type_similarity, st_type_field = _best_of_sides(
        query.St_PosTyp or query.St_PreTyp,
        record.St_PosTyp, record.St_PreTyp,
        left_field="St_PosTyp", right_field="St_PreTyp",
        left_population=pop("St_PosTyp"), right_population=pop("St_PreTyp"),
        expansions=_TYPE_EXPANSIONS,
    )
    st_dir_similarity, st_dir_field = _best_of_sides(
        query.St_PreDir or query.St_PosDir,
        record.St_PreDir, record.St_PosDir,
        left_field="St_PreDir", right_field="St_PosDir",
        left_population=pop("St_PreDir"), right_population=pop("St_PosDir"),
        expansions=_DIRECTIONAL_EXPANSIONS,
        binary=True,
    )
    terms: dict[str, tuple[Optional[float], float]] = {
        "St_Name": (
            _street_name_similarity(query.St_Name, record.St_Name),
            _BASE_WEIGHTS["St_Name"] * f("St_Name"),
        ),
        "St_Type": (
            st_type_similarity,
            # Decision 90 — the factor of whichever slot (St_PosTyp or
            # St_PreTyp) actually produced the compared value.
            # st_type_field is None only when neither slot yielded a
            # comparison, in which case the weight is moot (similarity is
            # also None, so _weighted_average excludes the term regardless).
            _BASE_WEIGHTS["St_Type"] * (f(st_type_field) if st_type_field else 0.0),
        ),
        "St_Dir": (
            # Decision 82 class (2) — binary after normalization. The
            # best-of-both-sides structure is retained deliberately: it is what
            # gives a pre/post swap full credit under an exact-match
            # comparison.
            st_dir_similarity,
            # Decision 90 — see St_Type above; same shape, St_PreDir/St_PosDir.
            _BASE_WEIGHTS["St_Dir"] * (f(st_dir_field) if st_dir_field else 0.0),
        ),
        "Community": (
            # Ordinary weighted term (decision 76), with the mismatch cap
            # amending decision 77's disqualification — see
            # _capped_community_similarity.
            _capped_community_similarity(
                _normalized_similarity(query_community, community_value),
                query_community,
                community_value,
            ),
            # Decision 76 — weighted by whichever cascade field actually
            # resolved THIS record's value, not a field fixed in code.
            # community_field is None when the record has no community at
            # all; the weight is moot then (similarity is also None, so
            # _weighted_average excludes the term regardless).
            _BASE_WEIGHTS["Community"] * (f(community_field) if community_field else 0.0),
        ),
        "A2": (
            _normalized_similarity(query.A2, record.A2),
            _BASE_WEIGHTS["A2"] * f("A2"),
        ),
        # Decision 82 class (2) — binary, not decision 72's edit-distance-only
        # treatment: "SD" against "ND" is a different jurisdiction scoring 0.0,
        # not a 0.50 near-miss on one shared character (Q30). Still weighted
        # terms, never candidate-set gates — decision 81's gates were reverted
        # in-spec before implementation.
        "A1": (
            _normalized_similarity(query.A1, record.A1, binary=True),
            _BASE_WEIGHTS["A1"] * f("A1"),
        ),
        "Country": (
            _normalized_similarity(query.Country, record.Country, binary=True),
            _BASE_WEIGHTS["Country"] * f("Country"),
        ),
    }
    score_value, breakdown = _weighted_average(terms)
    if not _street_name_qualifies(query.St_Name, record.St_Name):
        # Decision 71 — the caller typed a different street, not a typo of
        # this one. Breakdown still reported so a floor of 0 shows why.
        score_value = 0.0
    # No Community disqualification here. Decision 77's gate is reverted; a
    # non-qualifying Community is already priced by the capped term above.
    if query.Add_Number is not None:
        breakdown["Add_Number"] = 100.0
    return score_value, breakdown


def score_rcl(query: CivicAddress, record: RCLRecord) -> tuple[float, Mapping[str, float]]:
    """§6.5 for an RCLRecord (rungs 2/3). See RCL SIDEDNESS above for the
    side-hint judgment call this makes ahead of §7.2's own side selection."""
    f = field_stats.rcl_factor
    pop = field_stats.rcl_population
    side = _rcl_side_hint(query, record)
    query_community = _community_query(query)

    def sided(col_prefix: str) -> tuple[Optional[str], Optional[str]]:
        return getattr(record, f"{col_prefix}_L", None), getattr(record, f"{col_prefix}_R", None)

    def community() -> tuple[Optional[float], Optional[str], Optional[str]]:
        """Decision 76 — similarity, which cascade field produced the
        record-side value it was measured against (so the caller can weight
        by that field's own discriminative factor), AND the resolved value
        itself (so the mismatch cap below can run against the exact same
        side's value the similarity and weight already committed to).
        Where no side is chosen and both are compared, all three follow
        whichever side's similarity won."""
        if query_community is None:
            return None, None, None
        if side is not None:
            rval, rfield = _community_rcl_side(record, side)
            return _normalized_similarity(query_community, rval), rfield, rval
        left_val, left_field = _community_rcl_side(record, Side.LEFT)
        right_val, right_field = _community_rcl_side(record, Side.RIGHT)
        candidates = [
            (sim, fld, val)
            for sim, fld, val in (
                (_normalized_similarity(query_community, left_val), left_field, left_val),
                (_normalized_similarity(query_community, right_val), right_field, right_val),
            )
            if sim is not None
        ]
        if not candidates:
            return None, None, None
        return max(candidates, key=lambda triple: triple[0])

    def sided_similarity(
        col_prefix: str, *, phonetic: bool = True, binary: bool = False
    ) -> Optional[float]:
        """A2/A1/Country's ambiguous-parity fallback. These fields use ONE
        pooled factor regardless of L/R side (field_stats pools sided pairs
        into a single logical element — see _RCL_SIDED_PAIRS), so unlike
        St_Type/St_Dir below there is no factor lookup that needs to follow
        the winning slot here; the field name _best_of_sides reports is
        simply discarded. left_field/right_field are still passed (the
        column's own L/R names) because the helper's contract requires them,
        not because this caller consults them.
        """
        qval = getattr(query, col_prefix, None)
        left, right = sided(col_prefix)
        if side is not None:
            chosen = left if side is Side.LEFT else right
            return _normalized_similarity(qval, chosen, phonetic=phonetic, binary=binary)
        similarity, _slot_field = _best_of_sides(
            qval, left, right,
            left_field=f"{col_prefix}_L", right_field=f"{col_prefix}_R",
            phonetic=phonetic, binary=binary,
        )
        return similarity

    # Decision 90 — St_Type and St_Dir are RCL's UNSIDED "shared" fields
    # (_RCL_SHARED in field_stats.py: one value per segment, not one per
    # L/R side), so this is the same pre/post slot-pair problem score_ssap
    # has, entirely independent of `side` above. The two pairings must not
    # be confused: `side` picks administrative/postal attribution by which
    # half of the street the origin/parity falls on; st_type_field and
    # st_dir_field pick which of the PRE/POST name slots produced the
    # compared value. Neither St_PreTyp/St_PosTyp nor St_PreDir/St_PosDir
    # ever carries an _L/_R suffix, so there is no side boundary for this
    # lookup to cross.
    st_type_similarity, st_type_field = _best_of_sides(
        query.St_PosTyp or query.St_PreTyp,
        record.St_PosTyp, record.St_PreTyp,
        left_field="St_PosTyp", right_field="St_PreTyp",
        left_population=pop("St_PosTyp"), right_population=pop("St_PreTyp"),
        expansions=_TYPE_EXPANSIONS,
    )
    st_dir_similarity, st_dir_field = _best_of_sides(
        query.St_PreDir or query.St_PosDir,
        record.St_PreDir, record.St_PosDir,
        left_field="St_PreDir", right_field="St_PosDir",
        left_population=pop("St_PreDir"), right_population=pop("St_PosDir"),
        expansions=_DIRECTIONAL_EXPANSIONS,
        binary=True,
    )

    community_similarity, community_field, community_value = community()
    # The cap is applied AFTER the side is settled, against the same side's
    # value the similarity, weight, and field lookup all committed to — see
    # _capped_community_similarity. Side selection itself still runs on the
    # uncapped blend, so which side wins is decided the same way it was
    # before the cap existed.
    community_similarity = _capped_community_similarity(
        community_similarity, query_community, community_value
    )
    terms: dict[str, tuple[Optional[float], float]] = {
        "St_Name": (
            _street_name_similarity(query.St_Name, record.St_Name),
            _BASE_WEIGHTS["St_Name"] * f("St_Name"),
        ),
        "St_Type": (
            st_type_similarity,
            # Decision 90 — see score_ssap; same factor-follows-the-slot
            # correction, RCL's unsided St_PosTyp/St_PreTyp.
            _BASE_WEIGHTS["St_Type"] * (f(st_type_field) if st_type_field else 0.0),
        ),
        "St_Dir": (
            # Decision 82 class (2) — see score_ssap.
            st_dir_similarity,
            # Decision 90 — see score_ssap.
            _BASE_WEIGHTS["St_Dir"] * (f(st_dir_field) if st_dir_field else 0.0),
        ),
        "Community": (
            community_similarity,
            _BASE_WEIGHTS["Community"] * (f(community_field) if community_field else 0.0),
        ),
        "A2": (sided_similarity("A2"), _BASE_WEIGHTS["A2"] * f("A2")),
        # Decision 82 class (2) — binary, no gate. See score_ssap.
        "A1": (sided_similarity("A1", binary=True), _BASE_WEIGHTS["A1"] * f("A1")),
        "Country": (sided_similarity("Country", binary=True), _BASE_WEIGHTS["Country"] * f("Country")),
    }
    score_value, breakdown = _weighted_average(terms)
    if not _street_name_qualifies(query.St_Name, record.St_Name):
        score_value = 0.0  # decision 71 — see score_ssap
    # No Community disqualification — see score_ssap.
    return score_value, breakdown


def score(query: CivicAddress, record: SSAPRecord | RCLRecord) -> tuple[float, Mapping[str, float]]:
    """§6.5's Scorer, dispatching on record type. Matches
    src.geocode.candidates.Scorer's protocol exactly."""
    if isinstance(record, SSAPRecord):
        return score_ssap(query, record)
    return score_rcl(query, record)


# ---------------------------------------------------------------------------
# §10.6 reverse spatial-fit
# ---------------------------------------------------------------------------

def make_reverse_scorer(
    radius_m: float,
    *,
    geocoded_penalty: float = _GEOCODED_PLACEMENT_PENALTY,
):
    """Build §10.6's SpatialScorer, closed over the deployment's
    GCS_REVERSE_SEARCH_RADIUS_M rather than reading it globally — the same
    constant the search itself already uses (§10.2), reused here for the
    extent-damping and distance terms rather than inventing a second scale.
    """

    def reverse_score(origin: SearchOrigin, hit: Hit) -> tuple[float, Mapping[str, float]]:
        breakdown: dict[str, float] = {}

        if hit.contained:
            base = 100.0
            breakdown["containment"] = 100.0
        else:
            base = 100.0 * (1.0 - min(hit.distance_m / radius_m, 1.0))
            breakdown["distance"] = round(base, 2)

        extent_damping = radius_m / (radius_m + origin.extent_m) if origin.extent_m > 0 else 1.0
        if origin.extent_m > 0:
            breakdown["extent_damping"] = round(extent_damping, 4)

        placement = getattr(hit.record.source, "Placement", None)
        geocoded = placement is not None and placement.strip().lower() == "geocoding"
        penalty = geocoded_penalty if geocoded else 1.0
        if geocoded:
            breakdown["geocoded_placement_penalty"] = penalty

        return base * extent_damping * penalty, breakdown

    return reverse_score
