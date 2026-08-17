"""
FastAPI server — thin router for the GCS service.

All conversion logic lives under src/engine/, src/geocode/ and src/reverse/;
all protocol handling under src/api/. This module defines the FastAPI app,
wires lifespan and middleware, mounts the operational endpoints, and re-exports
what test harnesses import directly.

ONE WEB SERVICE
---------------
The normative YAML (references/i3-geocode-conversion.yaml) defines a single
specification with one server base (/Gcs/v1) and one /Versions entry point
covering both operations. That resolves Appendix C.2 question 6 and is why this
file mounts one Versions route, unlike LVF which mounts three (LoST, LoST-Sync,
DR are three distinct web services there).

The GCS consumes i3-fe-core as a LIBRARY, not a framework — it keeps its own
FastAPI app and wires core components in at startup, rather than handing routes
to core's create_app().
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware

from i3_fe_core.state.store import ElementState
from i3_fe_core.time.ntp import NtpClient
from i3_fe_core.web_service.versions import build_version_entry, make_versions_route

from src import runtime_state
from src.api import build_router
from src.app import lifecycle
from src.core_components import build_core_components, build_tls_settings, validate_tls_files
from src.gis import provisioning as gis_provisioning
from src.observability import metrics

log = logging.getLogger(__name__)

# The server base the normative YAML declares for both operations.
_API_PREFIX = "/Gcs/v1"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    tls_settings = build_tls_settings()
    log.info("TLS mode: %s", tls_settings.mode.value)
    tls_error = validate_tls_files(tls_settings)
    if tls_error is not None:
        log.error("%s — aborting startup", tls_error)
        raise RuntimeError(f"TLS configuration error: {tls_error}")

    ntp_client = NtpClient(servers=app.state.core.settings.ntp_servers)
    await ntp_client.start()
    app.state.core.ntp_client = ntp_client
    runtime_state._ntp_client = ntp_client
    log.info(
        "NTP client started: is_healthy=%s offset=%s", ntp_client.is_healthy, ntp_client.offset
    )

    await lifecycle.lifespan_startup()
    lifecycle.maybe_start_sip()
    yield

    try:
        await lifecycle.lifespan_shutdown()
    except Exception as exc:
        log.warning("Shutdown: lifecycle cleanup raised: %s", exc)

    if ntp_client is not None:
        try:
            await ntp_client.stop()
        except Exception as exc:
            log.warning("Shutdown: NTP client stop raised: %s", exc)


class LimitBodySize(BaseHTTPMiddleware):
    """Reject oversized bodies before they are read.

    A PIDF-LO is a small document — a civic address or a single geometry. 1 MiB
    is already orders of magnitude more than any legitimate request needs.
    """

    _DEFAULT = 1_048_576

    async def dispatch(self, request, call_next):
        if int(request.headers.get("content-length", 0) or 0) > self._DEFAULT:
            return Response(status_code=413)
        return await call_next(request)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records gcs_http_requests_total / gcs_http_request_duration_seconds for
    every request. Added after LimitBodySize so it wraps it (outermost) — a 413
    from LimitBodySize still passes through call_next here and is counted with
    its actual status code."""

    async def dispatch(self, request, call_next):
        path = request.scope["path"]
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start
        metrics.http_requests_total.labels(endpoint=path, status=str(response.status_code)).inc()
        metrics.http_request_duration_seconds.labels(endpoint=path).observe(elapsed)
        return response


app = FastAPI(title="GCS Service", lifespan=_lifespan)

app.state.core = build_core_components()
# i3-fe-core's conformance suite reads the NTP client from app.state.i3
# (the attribute name its own create_app() uses). This FE consumes core as a
# library and owns its app, so the same container is exposed under both names
# rather than maintaining two.
app.state.i3 = app.state.core
runtime_state.state_store = app.state.core.state_store
runtime_state.element_notifier = app.state.core.element_notifier
runtime_state.service_notifier = app.state.core.service_notifier
runtime_state.discrepancy = app.state.core.discrepancy
runtime_state.logging_client = app.state.core.logging_client

app.add_middleware(LimitBodySize)
app.add_middleware(MetricsMiddleware)

# ---------------------------------------------------------------------------
# Conversion resources (spec §3.9.1, §3.9.2)
# ---------------------------------------------------------------------------
# Mounted under the /Gcs/v1 base the normative YAML declares. The two strict
# paths are always present; the enhanced pair is gated on GCS_ENABLE_ENHANCED.
app.include_router(build_router(runtime_state._enable_enhanced), prefix=_API_PREFIX)

if not runtime_state._enable_enhanced:
    log.info(
        "i3-improved resources disabled (GCS_ENABLE_ENHANCED is not 'true') — "
        "/GeocodeEnhanced and /ReverseGeocodeEnhanced are neither mounted nor advertised"
    )

# ---------------------------------------------------------------------------
# Versions entry point (i3 §4.12 MUST, spec §A.1)
# ---------------------------------------------------------------------------
# ONE web service, ONE entry point, covering both operations (decision 34).
#
# The enhanced resources are advertised through the `vendor` parameter — i3's
# own sanctioned hook for a service declaring vendor-specific capability
# (spec §3.9.2, decision 35). A client that does not understand the vendor
# string ignores it and sees a plain conformant v1 GCS.
#
# serviceInfo is omitted: it is CONDITIONAL per §4.12, present only for
# services that define it (e.g. requiredAlgorithms for JWS-signing services),
# and the GCS defines none.
#
# NOTE: the YAML places /Versions under its own `servers` override —
# https://api.example.com/Gcs — one segment ABOVE the /Gcs/v1 base the two
# operations sit on. It is mounted that way here. See spec Appendix C.4.
_version_major = int(os.environ.get("GCS_VERSION_MAJOR", "1"))
_version_minor = int(os.environ.get("GCS_VERSION_MINOR", "0"))
_build_fingerprint = os.environ.get("GCS_BUILD_FINGERPRINT", "gcs-service-dev")

_vendor = (
    "i3-improved: GeocodeEnhanced, ReverseGeocodeEnhanced"
    if runtime_state._enable_enhanced
    else None
)

app.mount(
    "/Gcs/Versions",
    Starlette(
        routes=[
            make_versions_route(
                fingerprint_provider=_build_fingerprint,
                versions_provider=[
                    build_version_entry(_version_major, _version_minor, vendor=_vendor)
                ],
                path="/",
            )
        ]
    ),
)

# ---------------------------------------------------------------------------
# Discrepancy Reporting (i3 §3.7 MUST, spec §A.6)
# ---------------------------------------------------------------------------
if os.environ.get("GCS_ENABLE_DR_SERVICE", "true").strip().lower() == "true":
    from i3_fe_core.discrepancy import make_discrepancy_routes

    # Mounted at BOTH /dr and the root, against the SAME DiscrepancyReporting
    # instance — so a report POSTed to /Reports is resolvable at /dr/Resolutions.
    #
    # Two readings of i3 collide here and the GCS spec settles neither:
    #   - §3.7.1-3.7.3 name the resources "Reports", "Resolutions" and
    #     "StatusUpdates" with no base path. i3-fe-core's own create_app()
    #     mounts them at the root, and its conformance suite probes them there.
    #   - §4.12 requires EVERY web service to have a Versions entry point, and
    #     DR is a distinct web service. Giving it one requires a base to hang
    #     it off, which is why LVF mounts DR under /dr and exposes
    #     /dr/Versions.
    # Serving both costs nothing and prejudges nothing. Raised in
    # spec Appendix C.4.
    # Appended as individual Routes rather than mounted as a sub-app: a
    # Mount at "/" is a catch-all and would shadow every route registered
    # after it, including /health, /ready and /metrics.
    for _route in make_discrepancy_routes(app.state.core.discrepancy):
        app.router.routes.append(_route)

    _dr_versioned = list(make_discrepancy_routes(app.state.core.discrepancy))
    _dr_versioned.append(
        make_versions_route(
            fingerprint_provider=_build_fingerprint,
            versions_provider=[
                build_version_entry(
                    _version_major,
                    _version_minor,
                    # requiredAlgorithms is present but empty until JWS signing
                    # keys are provisioned (i3 §5.10) — presence is stable
                    # across that transition, only the array's contents change.
                    service_info={"requiredAlgorithms": []},
                )
            ],
        )
    )
    app.mount("/dr", Starlette(routes=_dr_versioned))

# ---------------------------------------------------------------------------
# State endpoints (i3 §2.4.1, §2.4.2)
# ---------------------------------------------------------------------------
# Read-only HTTP views of the same notifier state SIP subscribers receive.
# Core's app factory would mount these, but this FE owns its own app, so they
# are wired here. assert_core_conformance() checks both.


@app.get("/ElementState")
async def element_state():
    return runtime_state.element_notifier.get_notify_body()


@app.get("/ServiceState")
async def service_state():
    return runtime_state.service_notifier.get_notify_body()


# ---------------------------------------------------------------------------
# Operational endpoints (spec §3.9.4)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """LIVENESS. Returns 200 whenever the process is up.

    Deliberately does NOT gate on GIS data or NTP health: a worker with stale
    GIS data or drifted time is impaired but alive, and killing it will not
    help. Spec §3.9.4 assigns the traffic-gating role to /ready, so making
    /health 503 as well would collapse the split it asks for.

    This is a deliberate divergence from i3-fe-core's own create_app() health
    route, which returns 503 when element state is not Normal or NTP is
    unhealthy. The three fields core's conformance suite requires — status,
    elementState, ntpHealthy — are all present and carry the same advisory
    meaning; only the status code differs. assert_core_conformance accepts
    either 200 or 503.

    `status` is therefore advisory: "degraded" here means look at /ready and
    at ElementState, not that this instance is dead.
    """
    ntp = getattr(app.state.core, "ntp_client", None)
    ntp_healthy = bool(ntp.is_healthy) if ntp is not None else False
    element_state = runtime_state.state_store.get_element_state().state
    degraded = ntp_healthy is False or element_state != ElementState.NORMAL

    return {
        # --- fields i3-fe-core's conformance suite requires ---
        "status": "degraded" if degraded else "ok",
        "elementState": element_state.value,
        "ntpHealthy": ntp_healthy,
        # --- GCS specifics ---
        "serviceState": runtime_state.state_store.get_service_state().state.value,
        "ssapRecords": gis_provisioning.ssap_count(),
        "rclRecords": gis_provisioning.rcl_count(),
        "gisReloading": gis_provisioning.is_reloading(),
    }


@app.get("/ready")
async def ready(response: Response):
    """READINESS — distinct from /health liveness. LOAD BALANCERS SHOULD CHECK
    THIS.

    Returns 503 while a GIS reload is in flight or before GIS data is loaded,
    so traffic is not routed to a worker that cannot convert yet (spec §3.9.4).

    There is no routing-only exemption here. LVF returns ready on a node with
    no GIS data because such a node can still route to a parent or child; a GCS
    with no GIS data can do nothing at all (spec §3.1, decision 4).
    """
    reloading = gis_provisioning.is_reloading()
    ssap_n = gis_provisioning.ssap_count()
    rcl_n = gis_provisioning.rcl_count()

    ready_flag = (not reloading) and bool(ssap_n or rcl_n)

    response.status_code = 200 if ready_flag else 503
    return {
        "ready": ready_flag,
        "reloading": reloading,
        "ssap": ssap_n,
        "rcl": rcl_n,
    }


app.mount("/metrics", metrics.metrics_app())
