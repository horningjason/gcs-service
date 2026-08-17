"""src/discrepancy/discrepancy_report.py — the GCS filing side (decision 99).

Exercises _submit()'s local-log/no-endpoint contract and file_gis_dr()'s
report construction against a stand-in for the shared DiscrepancyReporting
component rather than the real i3_fe_core one — what these tests own is
GCS's own wiring (which enums, which fields, when the network is touched),
not core's submission behaviour, which is core's own test suite's job.

fire_gis_dr()'s scheduling guard is exercised separately (it needs a running
event loop to test meaningfully) from the two call-site test files that
exercise it from candidates.py/search.py directly:
tests/conformance/test_candidates.py and tests/conformance/test_reverse_search.py.
"""

from __future__ import annotations

import asyncio
import logging

from src import runtime_state
from src.discrepancy import discrepancy_report
from src.discrepancy.discrepancy_report import (
    GISProblem,
    ProblemSeverity,
    file_gis_dr,
    fire_gis_dr,
)


class _FakeReport:
    def __init__(self, *, report_type, problem_severity, resolution_uri,
                 problem_service, report_specific):
        self.report_type = report_type
        self.problem_severity = problem_severity
        self.resolution_uri = resolution_uri
        self.problem_service = problem_service
        self.report_specific = report_specific


class _FakeDiscrepancyReporting:
    """Stands in for i3_fe_core.discrepancy.DiscrepancyReporting."""

    def __init__(self):
        self.built: list[_FakeReport] = []
        self.submitted: list[tuple[_FakeReport, str]] = []

    def build_report(self, **kwargs):
        report = _FakeReport(**kwargs)
        self.built.append(report)
        return report

    async def submit(self, report, responder_uri):
        self.submitted.append((report, responder_uri))


def _capture_logs(logger_name):
    """A minimal log-capture context that sidesteps caplog: runtime_state.py
    sets propagate=False on the "src" logger, so records from "src.*" loggers
    never reach root and caplog (which listens there by default) sees
    nothing. Attaching directly to the module logger avoids that entirely."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    return records, logger, handler


# ---------------------------------------------------------------------------
# GISProblem — decision 99's subset of i3 §3.7.11's full registry
# ---------------------------------------------------------------------------

def test_gis_problem_is_scoped_to_what_gcs_can_detect():
    """No Gap/Overlap/IncorrectLoST/DuplicateAttribute/etc — GCS has no
    detection path for any of i3's other §3.7.11 tokens."""
    assert {p.value for p in GISProblem} == {
        "GeneralProvisioning", "OmittedField", "BadGeometry",
    }


# ---------------------------------------------------------------------------
# file_gis_dr() / _submit()
# ---------------------------------------------------------------------------

def test_file_gis_dr_is_a_noop_when_the_dr_component_is_not_initialized(monkeypatch):
    monkeypatch.setattr(runtime_state, "discrepancy", None)

    # No exception is the assertion here — there is nothing else to observe.
    asyncio.run(file_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate))


def test_submit_logs_locally_and_makes_no_http_call_without_an_endpoint(monkeypatch):
    """The silent no-op contract this module carries from lvf-service's
    identically-shaped _submit(): filing always happens locally, and only
    reaches the network when GCS_DR_ENDPOINT names a target."""
    fake = _FakeDiscrepancyReporting()
    monkeypatch.setattr(runtime_state, "discrepancy", fake)
    monkeypatch.delenv("GCS_DR_ENDPOINT", raising=False)

    records, logger, handler = _capture_logs("src.discrepancy.discrepancy_report")
    try:
        asyncio.run(file_gis_dr(
            GISProblem.OmittedField, ProblemSeverity.Minor,
            detail="NGUID", layer_ids="SiteStructureAddressPoint",
        ))
    finally:
        logger.removeHandler(handler)

    assert len(fake.built) == 1
    assert fake.submitted == []
    assert any("DiscrepancyReport" in r.getMessage() for r in records)


def test_submit_posts_when_an_endpoint_is_configured(monkeypatch):
    fake = _FakeDiscrepancyReporting()
    monkeypatch.setattr(runtime_state, "discrepancy", fake)
    monkeypatch.setenv("GCS_DR_ENDPOINT", "https://dr.example.com/Reports")

    asyncio.run(file_gis_dr(
        GISProblem.BadGeometry, ProblemSeverity.Moderate,
        detail="no usable geometry",
    ))

    assert len(fake.submitted) == 1
    report, responder_uri = fake.submitted[0]
    # DiscrepancyReporting.submit() appends "/Reports" itself.
    assert responder_uri == "https://dr.example.com"
    assert report.report_type == "GISDiscrepancyReport"
    assert report.problem_service == "GIS"
    assert report.problem_severity == "Moderate"
    assert report.report_specific == {
        "problem": "BadGeometry", "detail": "no usable geometry",
    }


# ---------------------------------------------------------------------------
# fire_gis_dr() — the sync fire-and-forget wrapper sync call sites use
# ---------------------------------------------------------------------------

def test_fire_gis_dr_drops_silently_with_no_event_loop_captured(monkeypatch):
    """candidates.py/search.py run both under the request-handling event loop
    and, in tests, with no loop at all — this is the second case, and a
    filing side-effect must never raise into the caller computing an answer."""
    fake = _FakeDiscrepancyReporting()
    monkeypatch.setattr(runtime_state, "discrepancy", fake)
    monkeypatch.setattr(runtime_state, "_event_loop", None)

    fire_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate)

    assert fake.built == []


def test_fire_gis_dr_schedules_onto_the_captured_event_loop(monkeypatch):
    scheduled = []

    def fake_run_coroutine_threadsafe(coro, loop):
        scheduled.append((coro, loop))
        coro.close()  # never actually driven — this test owns scheduling, not execution

    monkeypatch.setattr(discrepancy_report.asyncio, "run_coroutine_threadsafe",
                         fake_run_coroutine_threadsafe)

    async def _run():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(runtime_state, "_event_loop", loop)
        fire_gis_dr(GISProblem.BadGeometry, ProblemSeverity.Moderate)
        return loop

    loop = asyncio.run(_run())

    assert len(scheduled) == 1
    coro, scheduled_loop = scheduled[0]
    assert asyncio.iscoroutine(coro)
    assert scheduled_loop is loop
