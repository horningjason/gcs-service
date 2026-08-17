"""
Server lifecycle: configuration validation, XML schema loading, GIS
initialization, and the FastAPI lifespan startup/shutdown sequence.

Mirrors lvf-service/src/app/lifecycle.py minus everything federation-shaped.
There is no role module and no node-role branching: the GCS has exactly one
deployment mode (spec §3.1 — "There is no referral-only deployment mode").
There is likewise no routing-only mode: an LVF with no GeoPackage can still
route to a parent or child, whereas a GCS with no GIS data can do nothing at
all, so missing data is a hard ServiceDisruption rather than a degraded mode.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Optional

from lxml import etree

from i3_fe_core.runtime.worker import SingleWorkerContext, WorkerContext
from i3_fe_core.state.store import ElementState, ServiceState

from src import runtime_state
from src.discrepancy.discrepancy_report import GISProblem, ProblemSeverity, file_gis_dr
from src.engine import scoring
from src.engine import scoring_registry
from src.gis import provisioning as gis_provisioning
from src.observability import metrics as _metrics

log = logging.getLogger(__name__)

# Compiled schemas/gcs-pidflo.xsd. Read by src/api/admission.py on the request
# path (spec §4.1). None means schema validation is unavailable.
_schema: Optional[etree.XMLSchema] = None

# Leader gate for process singletons. SingleWorkerContext always reports
# leader; swap for a cross-process implementation when GCS_WORKERS > 1 needs
# real election (i3-fe-core README design rule 4).
_worker: WorkerContext = SingleWorkerContext()

# The SIP wire adapter (src/notify/sip_notifier.py), when maybe_start_sip()
# starts it. Kept as a module reference — same reason _schema and _worker
# above live here rather than on app.state: lifespan_startup()/_shutdown()
# are called from src/server.py's _lifespan() without the app object, so
# there is no app.state to hang this off (unlike lvf-service's server.py,
# which keeps the equivalent reference on app.state.sip_notifier).
_sip_notifier: object | None = None


def _schemas_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "schemas",
    )


def _load_schema() -> Optional[etree.XMLSchema]:
    """Compile schemas/gcs-pidflo.xsd — the master wrapper importing the PIDF
    envelope, the civic namespaces, the GML/GeoShape namespaces and RFC 7459
    confidence. See schemas/README.md for why one combined schema is required
    rather than validating against the envelope alone."""
    master = os.path.join(_schemas_dir(), "gcs-pidflo.xsd")
    try:
        compiled = etree.XMLSchema(etree.parse(master))
        log.info("XML schema loaded from %s", master)
        return compiled
    except Exception as exc:
        log.warning(
            "Could not load XML schema from %s: %s — schema validation disabled",
            master,
            exc,
        )
        return None


def validate_config() -> None:
    """Fail fast on configuration that has no safe default.

    GCS_AMBIGUITY_TOLERANCE_M governs the §6.3 ambiguity test: surviving
    Geocode candidates that differ horizontally by more than this yield 468
    rather than a merged position. §6.3 names no value, and Appendix C item (a)
    does not list it among the deferred defaults — so unlike the four tuning
    distances there is no spec figure to fall back on, and the plausible range
    spans from a city block to §6.3's own forty-mile illustration. Choosing
    silently would bury a consequential decision in a default.
    """
    if runtime_state._ambiguity_tolerance_m is None:
        raise RuntimeError(
            "GCS_AMBIGUITY_TOLERANCE_M is required and has no default. It sets the "
            "horizontal agreement tolerance for the spec §6.3 ambiguity test: "
            "candidates differing by more than this return 468 instead of being "
            "merged into an averaged position with extent-sized uncertainty. "
            "§6.3 gives no value — its own illustration is two matches forty miles "
            "apart (~64000), while a city-block figure would be ~150. See "
            "spec Appendix C.4 and .env.example."
        )
    if runtime_state._ambiguity_tolerance_m <= 0:
        raise RuntimeError(
            f"GCS_AMBIGUITY_TOLERANCE_M must be greater than 0 "
            f"(got {runtime_state._ambiguity_tolerance_m})"
        )
    if runtime_state._rcl_offset_m <= 0:
        # Spec §7.3: the offset MUST never place the returned position exactly
        # on the centerline itself.
        raise RuntimeError(
            f"GCS_RCL_OFFSET_M must be greater than 0 — spec §7.3 requires the "
            f"returned position never sit on the centerline "
            f"(got {runtime_state._rcl_offset_m})"
        )


def is_leader() -> bool:
    return _worker.is_leader()


def maybe_start_sip() -> None:
    """Start the SIP wire adapter (src/notify/sip_notifier.py) if enabled.

    i3 §4.5 places the same MUST on the GCS that §4.4 places on the MCS: each
    FE publishes ElementState/ServiceState over SIP, not just HTTP. Ported
    from lvf-service/src/server.py's _maybe_start_sip() — leader-gated like
    every other process singleton this module starts (the GIS watcher thread
    below): under GCS_WORKERS > 1, every worker binding the same UDP/TCP port
    is a startup crash, not graceful degradation, so only the leader worker
    starts it (i3-fe-core README design rule 4). mcs-service's equivalent
    starts unconditionally and is awaited directly rather than leader-gated
    and fire-and-forget — the right call for MCS, which runs single-process
    only today (see its CLAUDE.md), but not for the GCS, which is deployed
    multi-worker under gunicorn (GCS_WORKERS).

    Called from src/server.py's _lifespan(), after lifespan_startup() returns
    rather than from inside it: lifespan_startup() returns early when
    GCS_GPKG_PATH is unset/missing (see below), and ElementState/ServiceState
    are meaningful — and worth publishing over SIP — precisely when the
    service is in that degraded state, so SIP start must not be nested inside
    the branch that can skip it.
    """
    global _sip_notifier
    if os.environ.get("GCS_ENABLE_SIP", "true").strip().lower() != "true":
        log.info("SIP notifier disabled (GCS_ENABLE_SIP is not 'true')")
        return
    if not is_leader():
        log.info("SIP notifier not started — another worker is the leader")
        return
    sip_port_raw = os.environ.get("GCS_SIP_PORT", "5060").strip()
    try:
        sip_port = int(sip_port_raw)
    except ValueError:
        sip_port = 5060
    if sip_port == 0:
        return
    sip_host = os.environ.get("GCS_SIP_HOST", "0.0.0.0").strip()
    from src.notify.sip_notifier import SipWireAdapter
    _sip_notifier = SipWireAdapter(
        runtime_state.element_notifier,
        runtime_state.service_notifier,
        host=sip_host,
        port=sip_port,
        logging_client=runtime_state.logging_client,
    )
    # Fire-and-forget, matching lvf-service: start() awaits two socket binds
    # before returning, and lifespan startup should not block on that.
    asyncio.ensure_future(_sip_notifier.start())


def _register_scorers() -> None:
    """Install src/engine/scoring.py's forward and reverse scorers.

    Safe to call before GIS data has loaded: score() and the closure returned
    by make_reverse_scorer() read src/gis/field_stats.py and
    src/gis/provisioning.py's module state live, at request time, rather than
    capturing it here. The two §10.6 constants — GCS_REVERSE_SEARCH_RADIUS_M
    and GCS_GEOCODED_PLACEMENT_PENALTY — are bound at registration time, since
    both are fixed scale constants rather than things that change on a GIS
    reload. For the penalty, that binding is more than a wiring detail: it is
    the tuning mechanism decision 83 settles on. The constant is a deliberate
    editorial default rather than an untuned strawman, because it cannot be
    swept (STA-006.3 records that a placement was geocoded, never the error
    magnitude of that derivation) and cannot change an answer (§10.3 orders
    lexicographically on containment, tier, then distance — spatial fit is not
    a term in the ordering, so the penalty moves the reported number and
    confidence, never rank, admission, or a 200-vs-468). A deployment that
    knows its own geocoded placements sets the environment variable; the
    shipped 0.9 assumes nothing about them.

    Without this, every conversion 454s via scoring_registry.ScorerUnavailable
    — see that module's docstring for why that is the intended failure mode
    rather than a formula silently defaulting.
    """
    scoring_registry.set_forward_scorer(scoring.score)
    scoring_registry.set_reverse_scorer(
        scoring.make_reverse_scorer(
            runtime_state._reverse_search_radius_m,
            geocoded_penalty=runtime_state._geocoded_placement_penalty,
        )
    )


# ---------------------------------------------------------------------------
# GIS reload callbacks
# ---------------------------------------------------------------------------

def _on_gpkg_reload_success() -> None:
    """on_success callback for gis_provisioning.watch(). GIS code only signals
    "a reload succeeded"; deciding what that means for element/service state and
    metrics is this layer's job."""
    _metrics.reload_events_total.labels(trigger="gpkg_watcher", outcome="success").inc()
    log.info(
        "GIS data reload complete — %d SSAP, %d RCL — resuming normal service",
        gis_provisioning.ssap_count(),
        gis_provisioning.rcl_count(),
    )
    runtime_state.element_notifier.set_state(ElementState.NORMAL, "GIS reload succeeded")
    runtime_state.service_notifier.set_state(ServiceState.NORMAL, "GIS reload succeeded")


def _on_gpkg_reload_failure(exc: Exception) -> None:
    """on_failure callback for gis_provisioning.watch().

    Spec §3.5 (decision 94): stale data is preferred over no data. DatasetCache
    leaves the last good dataset in place, the service keeps converting against
    it, and this callback reports the disruption via ElementState (§A.4) —
    degraded and visible, not stopped. ServiceState is deliberately NOT driven
    to DOWN here; that happens only when there has never been a good load.

    Also files a GIS discrepancy report on the running event loop — decision 99,
    same GeneralProvisioning token lvf-service files for this same condition.
    This callback runs on gis_provisioning.watch()'s background thread, not on
    the event loop, hence run_coroutine_threadsafe rather than create_task.
    """
    _metrics.reload_events_total.labels(trigger="gpkg_watcher", outcome="failure").inc()
    log.error("GIS data reload failed", exc_info=exc)
    runtime_state.element_notifier.set_state(
        ElementState.SERVICE_DISRUPTION, "GIS reload failed"
    )
    event_loop = runtime_state._event_loop
    if event_loop is not None and event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            file_gis_dr(
                problem=GISProblem.GeneralProvisioning,
                severity=ProblemSeverity.Severe,
                detail=str(exc),
            ),
            event_loop,
        )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def prewarm() -> None:
    """Build the GIS JSON cache once before gunicorn forks its workers, so they
    hit a warm cache instead of all cold-building the GeoPackage concurrently."""
    gpkg_path = os.environ.get("GCS_GPKG_PATH", "")
    if gpkg_path and os.path.exists(gpkg_path):
        gis_provisioning.load(gpkg_path, runtime_state.now())
        log.info("Pre-warm complete")
    else:
        log.info("Pre-warm skipped — no GeoPackage at %r", gpkg_path)


def initialize(gpkg_path: str | None = None) -> None:
    """Synchronous startup for tests and tooling that do not run the ASGI
    lifespan. Loads the schema and the GIS data; does not touch state
    notifiers or start background threads."""
    global _schema
    validate_config()
    _register_scorers()
    _schema = _load_schema()
    path = gpkg_path or os.environ.get("GCS_GPKG_PATH", "")
    if path and os.path.exists(path):
        gis_provisioning.load(path, runtime_state.now())
    else:
        log.info("initialize(): no GeoPackage at %r — GIS data not loaded", path)


async def lifespan_startup() -> None:
    """Run startup tasks — called from the FastAPI lifespan context manager."""
    global _schema

    validate_config()
    _register_scorers()
    _schema = _load_schema()
    if _schema is None:
        # Spec §4.1 requires 454 on schema-invalid input. Without a compiled
        # schema that check cannot run, so this is louder than LVF's equivalent.
        log.error(
            "Operating WITHOUT XML schema validation — spec §4.1 requires 454 on "
            "schema-invalid input and that check cannot run"
        )

    runtime_state._event_loop = asyncio.get_running_loop()

    if is_leader():
        log.info("Worker %s is the GCS leader", _worker.worker_id())

    gpkg_path = os.environ.get("GCS_GPKG_PATH", "")
    gpkg_exists = bool(gpkg_path) and os.path.exists(gpkg_path)

    if not gpkg_exists:
        # No routing-only analogue here: a GCS with no GIS data cannot convert
        # anything. It stays up so /health, /ElementState and /ServiceState
        # keep answering, but /ready reports 503.
        runtime_state.element_notifier.set_state(
            ElementState.SERVICE_DISRUPTION, "GIS data unavailable"
        )
        runtime_state.service_notifier.set_state(
            ServiceState.DOWN, "GIS data unavailable"
        )
        log.error(
            "GIS data unavailable — GCS_GPKG_PATH=%r %s. The service cannot convert "
            "and /ready will report 503.",
            gpkg_path,
            "is not set" if not gpkg_path else "does not exist",
        )
        return

    try:
        gis_provisioning.load(gpkg_path, runtime_state.now())
    except Exception:
        _metrics.reload_events_total.labels(trigger="startup", outcome="failure").inc()
        log.error("GIS data load failed from %s", gpkg_path, exc_info=True)
        raise

    _metrics.reload_events_total.labels(trigger="startup", outcome="success").inc()
    log.info(
        "GIS data loaded: %d SSAP, %d RCL",
        gis_provisioning.ssap_count(),
        gis_provisioning.rcl_count(),
    )
    runtime_state.element_notifier.set_state(ElementState.NORMAL, "GIS data loaded")
    runtime_state.service_notifier.set_state(ServiceState.NORMAL, "GIS data loaded")

    poll_interval = int(os.environ.get("GCS_GPKG_POLL_INTERVAL_SECONDS", "60"))
    if poll_interval > 0:
        threading.Thread(
            target=gis_provisioning.watch,
            args=(runtime_state.now, _on_gpkg_reload_success, _on_gpkg_reload_failure),
            daemon=True,
        ).start()
        log.info("GeoPackage watcher started (poll interval: %ds)", poll_interval)


async def lifespan_shutdown() -> None:
    """Run shutdown cleanup — called from the FastAPI lifespan context manager
    after yield.

    The GIS watcher is a daemon thread and exits on process termination; it
    needs no explicit cancellation. The SIP wire adapter, when maybe_start_sip()
    started one, is the one long-running asyncio task this FE does start, and
    it is stopped explicitly here — without this, its bound UDP/TCP listeners
    and core's cleanup loop keep the event loop alive past gunicorn's
    graceful_timeout. LVF's equivalent additionally cancels LoST-Sync retry
    tasks, which have no GCS analogue (decision 4).
    """
    global _sip_notifier
    if _sip_notifier is not None:
        try:
            await _sip_notifier.stop()
        except Exception as exc:
            log.warning("Shutdown: SIP notifier stop raised: %s", exc)
        _sip_notifier = None
    log.info("GCS shutdown complete")
