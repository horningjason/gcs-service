"""Where the injected scorers are held. NOT where they are written.

§6.5 settles the SHAPE of the forward scoring function and deliberately
withholds the formula; §10.6 does the same for the reverse spatial fit. The
formulas are now written — src/engine/scoring.py, closed out by decisions 89
(forward weights) and 83 (reverse penalty) — but the seam remains:
src/geocode/candidates.py and src/reverse/search.py take a `score` callable
and have no default, and src/app/lifecycle.py registers scoring's functions
here at startup. That is the decision rather than a placeholder for one — the
engine stays testable with any scorer, and nothing deep in the pipeline
hard-codes the one formula the spec deliberately left injectable.

This module is the seam that lets the HTTP layer honour the same rule. A route
handler cannot take a scorer as an argument — it is called by the framework —
so it reads one from here, and something outside the request path put it here.
Tests inject trivial scorers; a deployment injects the real one.

WHAT HAPPENS WHEN NOTHING IS REGISTERED

`ScorerUnavailable`, which the handlers turn into 454 with a reason. That is not
a new status code: §8.4 assigns 454 to "schema validation failure and residual
internal errors", and a service asked to convert before its scoring function was
installed is squarely the second. It is emphatically not 468 — 468 asserts that
a search was performed and found nothing, and no search was performed here.

Nothing in this module scores anything, and nothing in it supplies a default. A
default would be a formula, and writing a formula here would be authoring the
part of the specification §6.5 and §10.6 left open.
"""

from __future__ import annotations

from typing import Optional

from src.geocode.candidates import Scorer
from src.reverse.search import SpatialScorer


class ScorerUnavailable(RuntimeError):
    """No scoring function has been registered for a direction."""

    def __init__(self, direction: str, section: str) -> None:
        super().__init__(
            f"No {direction} scoring function is registered. Spec {section} "
            f"settles the shape of this function and withholds the formula "
            f"(Appendix C item (d)); it is injected rather than defaulted, and "
            f"nothing has injected one."
        )
        self.direction = direction


_forward: Optional[Scorer] = None
_reverse: Optional[SpatialScorer] = None


def set_forward_scorer(score: Optional[Scorer]) -> None:
    """Install §6.5's per-field similarity function."""
    global _forward
    _forward = score


def set_reverse_scorer(score: Optional[SpatialScorer]) -> None:
    """Install §10.6's spatial-fit function."""
    global _reverse
    _reverse = score


def forward_scorer() -> Scorer:
    if _forward is None:
        raise ScorerUnavailable("forward", "§6.5")
    return _forward


def reverse_scorer() -> SpatialScorer:
    if _reverse is None:
        raise ScorerUnavailable("reverse", "§10.6")
    return _reverse
