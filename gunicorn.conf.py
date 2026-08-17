"""Gunicorn configuration for the GCS service (per-machine multi-worker).

Run with:
    python prewarm.py && gunicorn -c gunicorn.conf.py src.server:app

Worker count is controlled by GCS_WORKERS (default 1 == single-process
behavior).

TLS (spec §3.9.3, §A.8; decision 107): file-existence validation mirrors
main.py exactly, but the actual SSL context is NOT built here through
gunicorn's own certfile/keyfile/cert_reqs/ca_certs settings — that path
cannot express i3 §2.8.1's TLS-1.2 floor or PFS cipher suite, and is the
exact mechanism reports/core_security_prior_art.md's LVF git-history section
found unreliable for client-certificate enforcement under
gunicorn+UvicornWorker. worker_class below points at
src/app/gunicorn_worker.py's GcsUvicornWorker, which builds the context
through i3_fe_core.security.tls.make_server_ssl_context() and injects it
directly — see that module's docstring for the full mechanism and why
certfile/keyfile/cert_reqs/ca_certs are deliberately left unset here.

Multi-worker requires Linux or Docker — gunicorn is POSIX-only.
"""

import os
import sys

from src.core_components import build_tls_settings, validate_tls_files
from src.observability import metrics

bind = "0.0.0.0:8000"
worker_class = "src.app.gunicorn_worker.GcsUvicornWorker"
workers = int(os.environ.get("GCS_WORKERS", "1"))
timeout = int(os.environ.get("GCS_WORKER_TIMEOUT", "120"))
graceful_timeout = 30


def on_starting(server):
    """Runs once in the gunicorn master, before any worker forks — the only
    safe place to clear the Prometheus multiprocess directory (clearing it
    per-worker would race with siblings writing to it). Normally prewarm.py
    already did this; this is a defense-in-depth, harmless-if-redundant
    re-run for anyone invoking gunicorn directly without prewarm.py first."""
    metrics.clear_multiproc_dir()


def child_exit(server, worker):
    """Official prometheus_client multiprocess pattern: remove a dead
    worker's metric files on exit. See src/observability/metrics.py."""
    metrics.mark_worker_dead(worker.pid)


# -- TLS file-existence validation (mirrors main.py) --------------------------
# Fails fast in the gunicorn master before any worker forks. The actual TLS
# context is built per-worker by GcsUvicornWorker (see module docstring
# above) — this block only validates the files it will read exist.
_tls_error = validate_tls_files(build_tls_settings())
if _tls_error is not None:
    print(f"ERROR: {_tls_error}", file=sys.stderr)
    sys.exit(1)
