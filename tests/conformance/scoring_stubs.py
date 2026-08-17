"""Trivial scorers for tests, and the fixture plumbing to install them.

§6.5 and §10.6 settle the SHAPE of the two scoring functions and deliberately
withhold the formulas as proprietary tuning (Appendix C item (d)). The engine
therefore takes them by injection with no default, and so does the HTTP layer,
via src/engine/scoring_registry.py.

Everything in tests/ that drives a request end to end needs something in that
registry, and what it needs is something DELIBERATELY trivial: a test asserting
§8's response assembly must not also depend on a similarity measure nobody has
written. These stand in for the real functions and stand for nothing else.
"""

from __future__ import annotations

from typing import Mapping


def perfect(query, record) -> tuple[float, Mapping[str, float]]:
    """§6.5's slot, filled with the ceiling. Everything matches."""
    return 100.0, {}


def by_street(query, record) -> tuple[float, Mapping[str, float]]:
    """Exact street name scores 100, anything else 40.

    Enough to separate a match from a non-match without standing in for §6.5's
    actual per-field similarity.
    """
    same = (query.St_Name or "").upper() == (record.St_Name or "").upper()
    value = 100.0 if same else 40.0
    return value, {"St_Name": value}


def spatial_perfect(origin, hit) -> tuple[float, Mapping[str, float]]:
    """§10.6's slot, filled with the ceiling."""
    return 100.0, {}


def by_distance(origin, hit) -> tuple[float, Mapping[str, float]]:
    """A spatial fit that falls off with distance, bounded to 0-100.

    Not §10.6 — that has component weights and an extent-damping term this
    deliberately does not model. It exists so a test can tell two candidates
    apart by their scores.
    """
    value = max(0.0, 100.0 - hit.distance_m)
    return value, {"distance": value}


def install(monkeypatch, *, forward=perfect, reverse=spatial_perfect) -> None:
    """Register scorers for the duration of a test.

    Patched onto the registry's globals rather than set through its setters, so
    monkeypatch restores them and one test cannot leak a scorer into the next.
    """
    from src.engine import scoring_registry

    monkeypatch.setattr(scoring_registry, "_forward", forward)
    monkeypatch.setattr(scoring_registry, "_reverse", reverse)
