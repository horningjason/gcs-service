"""Gunicorn config for tests/security's live-handshake tests.

Structurally identical to gunicorn.conf.py (same worker_class, same
validate_tls_files() gate) but binds tests/security/_tls_test_app:app on a
test-controlled port (GCS_TEST_PORT) instead of src.server:app on 8000 — see
_run_uvicorn_test_server.py's docstring for why the plain-uvicorn side of
this test suite avoids the real app too. GCS_TEST_WORKERS (default 1) sets
the worker count — src/app/gunicorn_worker.py's module docstring records
that the first attempt at verifying its direct-injection mechanism looked
clean under a single worker and only surfaced a (later corrected — see that
docstring) concern under multiple workers, so the tests exercising this
mechanism default to more than one.

Run as a subprocess:
    gunicorn -c tests/security/_gunicorn_test.conf.py tests.security._tls_test_app:app
"""
import os
import sys

from src.core_components import build_tls_settings, validate_tls_files

bind = f"127.0.0.1:{os.environ.get('GCS_TEST_PORT', '8443')}"
worker_class = "src.app.gunicorn_worker.GcsUvicornWorker"
workers = int(os.environ.get("GCS_TEST_WORKERS", "1"))
timeout = 30
graceful_timeout = 5
loglevel = "warning"

_tls_error = validate_tls_files(build_tls_settings())
if _tls_error is not None:
    print(f"ERROR: {_tls_error}", file=sys.stderr)
    sys.exit(1)
