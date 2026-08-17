"""GCS discrepancy report filing — the FILING side.

Covers: NENA-STA-010.3f-2021 §3.7.11 (GISDiscrepancyReport). Decision 99
settles what the GCS files about: structural provisioning defects only — GIS
load/reload failure, a null NGUID (R3), a record with no usable geometry
(decision 55), and a multi-part centerline segment (decision 53) — never
attribution content, which is the SI's to resolve (decisions 29, 45, 46).

Report submission — the §3.7.1 reporting prolog (discrepancyReportId, jCard,
agent id), the §2.3 submittal timestamp, and the §3.7 SHOULD-level rate limit
on similar reports — is owned by i3_fe_core.discrepancy.DiscrepancyReporting,
shared via runtime_state.discrepancy (see src/core_components.py). This
module keeps only GCS's domain problem enum and the convenience function that
builds and files a GISDiscrepancyReport (§3.7.11) from it — mirroring
lvf-service/src/discrepancy/discrepancy_report.py. The GCS has no LoST role
and no equivalent of LVF's LoSTDiscrepancyReport helper, so only the GIS half
of that module's shape applies here.

GISProblem is a deliberate SUBSET of i3 §3.7.11's full registry (which also
carries Gap, Overlap, IncorrectLoST, DuplicateAttribute, IncorrectDataType,
AddressRange, MalformedURI, DisplayData, OtherGIS) — only the three tokens a
GCS detection path can actually produce:

    GeneralProvisioning — GIS load/reload failure (src/app/lifecycle.py)
    OmittedField         — DataQualityFlag.NGUID_MISSING (R3)
    BadGeometry           — DataQualityFlag.NO_GEOMETRY (decision 55) and
                             DataQualityFlag.MULTIPART_SEGMENT (decision 53)

The engine's DataQualityFlag set in src/engine/models.py stays the filing
vocabulary, exactly as that module's own docstring says. Detection stays
there too — GisRecord.from_record() only records what it observed and files
nothing itself. Filing happens at the call sites that consume the resulting
GisRecord: candidate identification (src/geocode/candidates.py) and
nearest-feature search (src/reverse/search.py).
"""

from __future__ import annotations

import asyncio
import logging
import os
from enum import Enum
from typing import Optional

from i3_fe_core.discrepancy import PROBLEM_SEVERITIES, DiscrepancyReport

from src import runtime_state

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProblemSeverity(Enum):
    Minor = "Minor"
    Moderate = "Moderate"
    Degraded = "Degraded"
    Impaired = "Impaired"
    Severe = "Severe"
    Critical = "Critical"


assert {s.value for s in ProblemSeverity} == set(PROBLEM_SEVERITIES), (
    "ProblemSeverity has drifted from i3_fe_core.discrepancy.PROBLEM_SEVERITIES (§3.7.1/§10.34)"
)


class GISProblem(Enum):
    """§3.7.11 problem tokens — see the module docstring for why this is a
    subset of i3's full registry rather than the whole thing."""
    GeneralProvisioning = "GeneralProvisioning"
    OmittedField = "OmittedField"
    BadGeometry = "BadGeometry"


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

async def _submit(report: DiscrepancyReport) -> None:
    """Log locally and, when GCS_DR_ENDPOINT is configured, submit through the
    shared DiscrepancyReporting component. Never raises."""
    log.info(
        "DiscrepancyReport [%s/%s]: %s",
        report.report_type, report.problem_severity, report.report_specific,
    )

    dr_component = runtime_state.discrepancy
    endpoint = os.environ.get("GCS_DR_ENDPOINT", "")
    if dr_component is None or not endpoint:
        return

    # GCS_DR_ENDPOINT has historically named the full .../Reports submission
    # URL; DiscrepancyReporting.submit() appends "/Reports" to responder_uri
    # itself, so strip it back off here if present.
    responder_uri = endpoint[: -len("/Reports")] if endpoint.endswith("/Reports") else endpoint

    try:
        await dr_component.submit(report, responder_uri)
    except Exception as exc:
        log.warning("DR submission to %s failed: %s", responder_uri, exc)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

async def file_gis_dr(
    problem: GISProblem,
    severity: ProblemSeverity,
    detail: Optional[str] = None,
    layer_ids: Optional[str] = None,
) -> None:
    """File a GISDiscrepancyReport (§3.7.11) against the SI. Never raises."""
    dr_component = runtime_state.discrepancy
    if dr_component is None:
        log.debug("DR component not initialized — GIS DR not filed")
        return

    report_specific = {"problem": problem.value}
    if layer_ids is not None:
        report_specific["layerIds"] = layer_ids
    if detail is not None:
        report_specific["detail"] = detail

    try:
        report: DiscrepancyReport = dr_component.build_report(
            report_type="GISDiscrepancyReport",
            problem_severity=severity.value,
            resolution_uri=os.environ.get("GCS_DR_RESOLUTION_URI", ""),
            problem_service="GIS",
            report_specific=report_specific,
        )
    except Exception as exc:
        log.warning("Failed to build GIS DR: %s", exc)
        return

    await _submit(report)


# ---------------------------------------------------------------------------
# Sync fire-and-forget wrapper
# ---------------------------------------------------------------------------

def fire_gis_dr(
    problem: GISProblem,
    severity: ProblemSeverity,
    detail: Optional[str] = None,
    layer_ids: Optional[str] = None,
) -> None:
    """Schedule file_gis_dr() from a synchronous call site. Never raises and
    never blocks the caller.

    Candidate identification (src/geocode/candidates.py) and nearest-feature
    search (src/reverse/search.py) are plain sync functions that detect
    DataQualityFlag conditions once per record. They run under the
    request-handling event loop in production, but also run directly and
    synchronously in tests with no loop at all — the same ambiguity
    src/app/lifecycle.py's _on_gpkg_reload_failure resolves for its own
    caller (a background watcher thread) by scheduling onto the loop
    captured at startup instead of assuming one is already running. This
    mirrors that guard rather than calling asyncio.create_task() directly,
    which would raise outside a running loop and take the detection call
    site down with it — a filing side-effect must never perturb the answer
    the caller is computing. With no loop available, the report is silently
    dropped rather than filed; DiscrepancyReporting's own rate limiter is
    what keeps a hot loop with many flagged records from flooding the SI
    when a loop IS available.
    """
    coro = file_gis_dr(problem, severity, detail=detail, layer_ids=layer_ids)
    event_loop = runtime_state._event_loop
    if event_loop is not None and event_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, event_loop)
    else:
        coro.close()
