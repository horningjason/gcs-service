"""Live-handshake verification for the GCS's TLS/mTLS listener (spec §3.9.3,
§A.8, decision 107).

These tests attempt real TLS connections against real subprocesses (plain
uvicorn via main.py's mechanism, and gunicorn+UvicornWorker via
gunicorn.conf.py's) and assert on the OBSERVED handshake outcome — not on
`ssl.SSLContext` attributes or environment variables. Decision 107's whole
premise is that LVF once had a config that read as CERT_REQUIRED while the
service silently accepted anonymous clients; a test that only inspects
`make_server_ssl_context(...).verify_mode` would have passed throughout that
episode. See reports/core_security_prior_art.md for the incident this
guards against.

gunicorn is POSIX-only (fcntl, os.fork) — the gunicorn-marked cases are
skipped on Windows, matching gunicorn.conf.py's own documented constraint.
They were run and their results recorded in the implementation report before
being committed; skipping on an unsupported platform is not the same as
being unverified.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    import fcntl  # noqa: F401

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

requires_gunicorn = pytest.mark.skipif(
    not _HAS_FCNTL,
    reason="gunicorn requires POSIX (fcntl/os.fork) — see gunicorn.conf.py's own constraint",
)


# ---------------------------------------------------------------------------
# Server process management
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        time.sleep(0.2)
    return False


def _gunicorn_executable() -> str:
    candidate = Path(sys.executable).parent / "gunicorn"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("gunicorn")
    if found:
        return found
    raise RuntimeError("gunicorn executable not found next to sys.executable or on PATH")


@contextlib.contextmanager
def _uvicorn_server(env: dict):
    port = _free_port()
    full_env = {**os.environ, **env, "GCS_TEST_PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.security._run_uvicorn_test_server"],
        cwd=str(REPO_ROOT),
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_for_port(port):
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            proc.terminate()
            pytest.fail(f"uvicorn test server did not start on {port}. Output:\n{out}")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@contextlib.contextmanager
def _gunicorn_server(env: dict, *, cert_optional_fallback: bool = False, workers: int = 1):
    port = _free_port()
    full_env = {
        **os.environ,
        **env,
        "GCS_TEST_PORT": str(port),
        "GCS_TEST_WORKERS": str(workers),
        "GCS_GUNICORN_CERT_OPTIONAL_FALLBACK": "true" if cert_optional_fallback else "false",
    }
    proc = subprocess.Popen(
        [
            _gunicorn_executable(),
            "-c",
            "tests/security/_gunicorn_test.conf.py",
            "tests.security._tls_test_app:app",
        ],
        cwd=str(REPO_ROOT),
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_for_port(port):
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            proc.terminate()
            pytest.fail(f"gunicorn test server did not start on {port}. Output:\n{out}")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Client-side raw TLS
# ---------------------------------------------------------------------------


def _client_context(
    ca_cert: Path,
    *,
    client_cert: Path | None = None,
    client_key: Path | None = None,
    maximum_version: ssl.TLSVersion | None = None,
    ciphers: str | None = None,
) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=str(ca_cert))
    if client_cert is not None:
        ctx.load_cert_chain(certfile=str(client_cert), keyfile=str(client_key))
    if maximum_version is not None:
        ctx.maximum_version = maximum_version
    if ciphers is not None:
        ctx.set_ciphers(ciphers)
    return ctx


def _attempt_handshake(port: int, ctx: ssl.SSLContext, timeout: float = 5.0) -> tuple[bool, str]:
    """Attempt a real TLS handshake + tiny HTTP request. Returns (ok, detail).

    ok is True only when an actual HTTP response came back — NOT merely when
    ctx.wrap_socket() returned without raising. Under TLS 1.3, client
    certificate authentication is a POST-handshake exchange (RFC 8446 §4.3.2):
    the client's wrap_socket() can return successfully — its own view of the
    handshake is complete — before the server has finished validating the
    certificate the client just sent, and an async server (uvicorn's asyncio
    SSL transport, observed here specifically on Windows — see the
    implementation report) can accept the connection at the transport layer
    and only abort it a moment later once verification fails server-side.
    From the client's perspective this looks like "handshake succeeded, then
    zero bytes and a reset" rather than an exception at handshake time — a
    real rejection, just a differently-shaped one. Treating any
    non-exception as acceptance would have been the same class of shallow
    verification bug decision 107 exists to correct, so a genuine (non-empty)
    HTTP response is required before this returns ok=True.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname="localhost") as tls_sock:
                tls_sock.settimeout(timeout)
                tls_sock.sendall(
                    b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                )
                data = tls_sock.recv(200)
                if not data:
                    return False, "handshake returned but connection closed with no data (post-handshake rejection)"
                return True, data.decode(errors="replace")
    except ssl.SSLError as exc:
        return False, f"SSLError: {exc}"
    except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _mtls_env(pki) -> dict:
    return {
        "GCS_TLS_MODE": "mtls",
        "GCS_TLS_CERT_FILE": str(pki.server_cert),
        "GCS_TLS_KEY_FILE": str(pki.server_key),
        "GCS_TLS_CA_FILE": str(pki.ca_cert),
    }


# ---------------------------------------------------------------------------
# Plain-uvicorn path (main.py's mechanism) — runs everywhere, Windows included
# ---------------------------------------------------------------------------


def test_uvicorn_no_client_cert_is_rejected(tls_pki):
    """§5.4: an mtls listener MUST NOT accept a connection with no client
    certificate. This is the exact scenario decision 107 found silently
    passing (CERT_OPTIONAL) before this task's wiring."""
    with _uvicorn_server(_mtls_env(tls_pki)) as port:
        ok, detail = _attempt_handshake(port, _client_context(tls_pki.ca_cert))
    assert not ok, f"expected the handshake to be rejected with no client cert; got: {detail}"


def test_uvicorn_untrusted_client_cert_is_rejected(tls_pki):
    with _uvicorn_server(_mtls_env(tls_pki)) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.untrusted_client_cert,
            client_key=tls_pki.untrusted_client_key,
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert not ok, f"expected the handshake to be rejected for an untrusted client cert; got: {detail}"


def test_uvicorn_trusted_client_cert_is_accepted(tls_pki):
    with _uvicorn_server(_mtls_env(tls_pki)) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.trusted_client_cert,
            client_key=tls_pki.trusted_client_key,
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert ok, f"expected the handshake to succeed for a CA-signed client cert; got: {detail}"
    assert "200" in detail or "ok" in detail.lower()


def test_uvicorn_tls_1_1_is_rejected(tls_pki):
    """i3 §2.8.1: MUST NOT offer or accept TLS 1.0/1.1."""
    with _uvicorn_server(_mtls_env(tls_pki)) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.trusted_client_cert,
            client_key=tls_pki.trusted_client_key,
            maximum_version=ssl.TLSVersion.TLSv1_1,
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert not ok, f"expected a TLS-1.1-capped handshake to be rejected; got: {detail}"


def test_uvicorn_non_pfs_cipher_is_rejected(tls_pki):
    """i3 §2.8.1: perfect forward secrecy MUST be used within the ESInet.
    AES128-SHA is a static (non-ECDHE/DHE) TLS 1.2 cipher — no PFS."""
    try:
        weak_ctx_probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        weak_ctx_probe.set_ciphers("AES128-SHA")
    except ssl.SSLError as exc:
        pytest.skip(
            f"this OpenSSL build refuses to offer AES128-SHA at all (no PFS-less "
            f"cipher reachable client-side to probe with): {exc}"
        )

    with _uvicorn_server(_mtls_env(tls_pki)) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.trusted_client_cert,
            client_key=tls_pki.trusted_client_key,
            maximum_version=ssl.TLSVersion.TLSv1_2,
            ciphers="AES128-SHA",
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert not ok, f"expected a non-PFS-cipher-only handshake to be rejected; got: {detail}"


def test_uvicorn_disabled_mode_serves_plaintext(tls_pki):
    """Baseline: GCS_TLS_MODE=disabled must remain plaintext HTTP for local
    development (spec §3.9.3) — this wiring must not silently force TLS."""
    with _uvicorn_server({"GCS_TLS_MODE": "disabled"}) as port:
        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
            sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            data = sock.recv(200)
    assert b"200" in data or b"ok" in data.lower()


# ---------------------------------------------------------------------------
# gunicorn+UvicornWorker path — POSIX only
# ---------------------------------------------------------------------------


@requires_gunicorn
def test_gunicorn_no_client_cert_is_rejected_under_multiple_workers(tls_pki):
    """Shipped configuration (GcsUvicornWorker's default gunicorn_mode=False,
    direct-injected CERT_REQUIRED — see that module's docstring for the full
    verification history, including an earlier false alarm from a
    measurement bug in this same kind of test). Uses multiple workers and
    repeated attempts deliberately: a single worker + a single attempt looks
    clean regardless of whether the underlying mechanism is reliable — that
    was true of LVF's original CERT_REQUIRED and, briefly, of this task's own
    first pass at verifying this exact mechanism. 0 accepted out of many
    attempts is the bar; anything else means the mechanism has regressed and
    src/app/gunicorn_worker.py's default needs to be revisited before this
    test is loosened."""
    attempts = 24
    accepted = 0
    with _gunicorn_server(_mtls_env(tls_pki), workers=3) as port:
        for _ in range(attempts):
            ok, _detail = _attempt_handshake(port, _client_context(tls_pki.ca_cert))
            if ok:
                accepted += 1
    assert accepted == 0, (
        f"{accepted}/{attempts} no-cert connections were accepted under 3 "
        f"gunicorn workers — direct injection no longer reliably enforces "
        f"CERT_REQUIRED in this toolchain. Do not treat this as a flake; see "
        f"src/app/gunicorn_worker.py's module docstring, which was written "
        f"from exactly this test failing before the mechanism was verified "
        f"correctly. Either the toolchain regressed or something changed in "
        f"GcsUvicornWorker — investigate before loosening this assertion, "
        f"and set GCS_GUNICORN_CERT_OPTIONAL_FALLBACK=true only as a "
        f"temporary mitigation while doing so."
    )


@requires_gunicorn
def test_gunicorn_untrusted_client_cert_is_rejected(tls_pki):
    with _gunicorn_server(_mtls_env(tls_pki), workers=3) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.untrusted_client_cert,
            client_key=tls_pki.untrusted_client_key,
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert not ok, f"expected the handshake to be rejected for an untrusted client cert; got: {detail}"


@requires_gunicorn
def test_gunicorn_trusted_client_cert_is_accepted(tls_pki):
    with _gunicorn_server(_mtls_env(tls_pki), workers=3) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.trusted_client_cert,
            client_key=tls_pki.trusted_client_key,
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert ok, f"a CA-signed client cert should always be accepted; got: {detail}"


@requires_gunicorn
def test_gunicorn_cert_optional_fallback_does_not_enforce(tls_pki):
    """The break-glass fallback (GCS_GUNICORN_CERT_OPTIONAL_FALLBACK=true —
    documented in .env.example, see src/app/gunicorn_worker.py) reverts to
    core's own gunicorn_mode=True acknowledgment and must NOT enforce, so an
    operator who sets it as a temporary mitigation gets exactly the
    documented (lack of) behaviour, not a surprise either way."""
    with _gunicorn_server(_mtls_env(tls_pki), cert_optional_fallback=True) as port:
        ok, detail = _attempt_handshake(port, _client_context(tls_pki.ca_cert))
    assert ok, (
        f"expected the CERT_OPTIONAL fallback to accept a no-cert connection "
        f"— if this now rejects, core's gunicorn_mode contract changed; got: {detail}"
    )


@requires_gunicorn
def test_gunicorn_tls_1_1_is_rejected(tls_pki):
    """The TLS-version floor is applied by _apply_tls_constraints() before
    either gunicorn_mode branch — independent of the cert-requirement
    question, this must hold under gunicorn+UvicornWorker too, and does
    under the shipped configuration."""
    with _gunicorn_server(_mtls_env(tls_pki)) as port:
        ctx = _client_context(
            tls_pki.ca_cert,
            client_cert=tls_pki.trusted_client_cert,
            client_key=tls_pki.trusted_client_key,
            maximum_version=ssl.TLSVersion.TLSv1_1,
        )
        ok, detail = _attempt_handshake(port, ctx)
    assert not ok, f"expected a TLS-1.1-capped handshake to be rejected under gunicorn; got: {detail}"
