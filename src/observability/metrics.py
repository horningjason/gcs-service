"""Prometheus metrics for the GCS service — operations tooling, not a wire
protocol concern (no implications for the algorithm specification; this stays
out of it entirely).

Multiprocess plumbing (PROMETHEUS_MULTIPROC_DIR setup, the /metrics ASGI app,
and the gunicorn child_exit hook) lives in i3_fe_core.observability.metrics —
see that module's docstring for the multiprocess-mode mechanics. This module
holds only GCS's metric definitions.

Only Counters and Histograms are used (no Gauges): both sum correctly across
workers with no extra configuration.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from i3_fe_core.observability.metrics import (
    clear_multiproc_dir,  # noqa: F401
    ensure_multiproc_dir,
    mark_worker_dead,  # noqa: F401
    metrics_app,  # noqa: F401
)

# Must happen before the prometheus_client import below — see core module
# docstring. Multiprocess vs single-process mode is decided once, at
# prometheus_client.values import time.
ensure_multiproc_dir("/tmp/gcs_prometheus_multiproc")

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Transport-level
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "gcs_http_requests_total",
    "Total HTTP requests handled, by endpoint and status code.",
    ["endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "gcs_http_request_duration_seconds",
    "HTTP request handling duration in seconds, by endpoint.",
    ["endpoint"],
)

# ---------------------------------------------------------------------------
# GIS provisioning
# ---------------------------------------------------------------------------

reload_events_total = Counter(
    "gcs_reload_events_total",
    "Total GIS data (re)load attempts, by trigger and outcome.",
    ["trigger", "outcome"],
)

# Per-conversion metrics deliberately do not exist yet. The MetricsMiddleware
# in src/server.py already labels every request by endpoint path and status,
# which for the four conversion resources IS a per-operation, per-status
# series — a second counter incremented on the same events would double-count
# the same information. Add operation-level metrics only when they would carry
# something the HTTP series cannot (e.g. per-rung or per-tier outcomes).
# Load-shedding metrics arrive with load shedding (spec §3.9.5, decision 100).
