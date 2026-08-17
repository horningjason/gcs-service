"""Custom UvicornWorker for the gunicorn+UvicornWorker deployment path
(spec §3.9.3, §A.8; decision 107).

WHY THIS EXISTS

uvicorn.workers.UvicornWorker.__init__ builds its own uvicorn.Config from
gunicorn's ssl_options — certfile, keyfile, cert_reqs, ca_certs, ssl_version,
ciphers, all read from gunicorn.conf.py's module-level variables — and hands
them to uvicorn.Config as discrete ssl_certfile/ssl_cert_reqs/... kwargs.
uvicorn's own create_ssl_context() (uvicorn/config.py) never sets a TLS
minimum_version and has no PFS-only cipher default, so i3 §2.8.1's TLS-1.2
floor and i3-fe-core's PFS cipher suite cannot be expressed through that
surface regardless of how it's populated — the same limitation main.py's
plain-uvicorn path has (see that module's docstring). GcsUvicornWorker
instead builds the context via i3_fe_core.security.tls.make_server_ssl_context()
and assigns it directly to the uvicorn.Config instance the base class already
built, bypassing gunicorn's ssl_options -> uvicorn ssl_* kwargs ->
create_ssl_context() chain entirely.

WHY gunicorn_mode=False (genuine CERT_REQUIRED) IS THE SHIPPED DEFAULT

reports/core_security_prior_art.md's LVF git-history section found that
relying on gunicorn's ssl_options-forwarding path for CERT_REQUIRED was
unreliable under gunicorn+UvicornWorker — LVF reverted to CERT_OPTIONAL after
discovering it. That finding is about a DIFFERENT mechanism than this
module's: LVF's cert_reqs = ssl.CERT_REQUIRED relied on gunicorn's own
ssl_options -> uvicorn ssl_* kwargs forwarding (the same path this module
bypasses), and separately, LVF's actual mitigation attempt assigned a
hand-built ssl.SSLContext to gunicorn's `ssl_context` setting — which is only
consulted by gunicorn's own sync-worker socket wrapping (gunicorn/sock.py)
and is never read by UvicornWorker at all, so that specific fix could not
have taken effect regardless of whether the underlying forwarding bug was
real. See the prior-art report for the full commit-by-commit history.

This task verified GcsUvicornWorker's direct-injection mechanism
specifically (not LVF's) against a live handshake, and the first attempt at
that verification produced a false alarm worth recording here as a caution
against exactly the kind of premature claim decision 107 exists to correct:
an initial 3-worker, 30-attempt run appeared to show 11/30 (37%) no-certificate
connections silently accepted. That reading was wrong — the measurement
counted a TLS 1.3 characteristic as acceptance. Client certificate
authentication in TLS 1.3 is a POST-handshake exchange (RFC 8446 §4.3.2): a
client's wrap_socket() can return successfully — its own view of the initial
handshake is complete — before the server has finished validating the
certificate the client sent, so the server's rejection can surface as a
handshake that "succeeds" followed immediately by a closed connection with
zero bytes returned, rather than as an exception during the handshake call.
The original measurement treated any non-exception as acceptance; correcting
it to require an actual non-empty HTTP response changed the earlier result
to 0 false accepts.

Once measured correctly: 100 SEQUENTIAL no-certificate connection attempts
against 4 workers produced 0 genuine accepts (63 handshake-level exceptions,
37 post-handshake empty-response rejections — both real rejections, just
shaped differently). 80 CONCURRENT attempts (20 threads) against 4 workers
produced 0 genuine accepts (79 exceptions, 1 empty-response rejection). 180
total attempts, 0 false accepts, across 1/3/4-worker configurations. On that
evidence, direct injection is shipped as the default rather than core's own
conservative gunicorn_mode=True (CERT_OPTIONAL) acknowledgment — this
achieves actual i3 §5.4 enforcement under gunicorn+UvicornWorker rather than
settling for an honestly-disclosed gap.

This conclusion is specific to the toolchain it was verified against
(gunicorn==23.0.0, uvicorn==0.46.0, Python 3.14, Ubuntu 26.04/OpenSSL 3.5.5 —
see requirements.txt for the pins this repository ships). It is not a
general claim that gunicorn's ssl_options-forwarding path (LVF's mechanism)
is safe, nor a claim that this mechanism is safe on every OS/version
combination forever. Re-run tests/security/test_mtls_handshake.py's
gunicorn-marked cases — which exercise this exact mechanism against a live
handshake under both sequential and multi-worker load — before trusting a
materially different toolchain, and do not revert to trusting a
single-worker, single-attempt result the way the first pass at this
verification briefly did.

GCS_GUNICORN_CERT_OPTIONAL_FALLBACK reverts to core's own gunicorn_mode=True
acknowledgment (CERT_OPTIONAL, no handshake-level enforcement) for an
operator who hits a real, reproduced problem with direct injection in their
own environment while investigating. It IS documented — in .env.example's
transport-security section, alongside the other GCS_TLS_* variables — because
an undocumented switch that silently disables i3 §5.4 enforcement is the same
species of problem decision 107 withdrew: a service that reads as compliant
while something turns compliance off. Obscurity was tried first and reversed;
visibility plus a loud startup warning (below) is the control now. Setting it
disables i3 §5.4 mutual authentication under gunicorn+UvicornWorker entirely
and MUST NOT happen in production — see .env.example for the full warning
text, which this module's startup log deliberately echoes.
"""
from __future__ import annotations

import logging
import os

from i3_fe_core.security.tls import make_server_ssl_context
from uvicorn.workers import UvicornWorker

from src.core_components import build_tls_settings

_log = logging.getLogger(__name__)

_FALLBACK_VAR = "GCS_GUNICORN_CERT_OPTIONAL_FALLBACK"
_CERT_OPTIONAL_FALLBACK = os.environ.get(_FALLBACK_VAR, "").strip().lower() == "true"
if _CERT_OPTIONAL_FALLBACK:
    # Fires once per gunicorn worker process (module import time), matching
    # src/app/lifecycle.py's house style for loud config-validation warnings.
    _log.warning(
        "%s=true — i3 §5.4 mutual authentication is NOT enforced on this "
        "worker. The gunicorn+UvicornWorker listener is running CERT_OPTIONAL "
        "instead of CERT_REQUIRED: a client presenting no certificate is "
        "accepted. This is a break-glass fallback for a reproduced problem "
        "with direct injection, not a supported deployment configuration — "
        "MUST NOT be set in production. See .env.example and this module's "
        "docstring.",
        _FALLBACK_VAR,
    )


class GcsUvicornWorker(UvicornWorker):
    """UvicornWorker with a directly-injected i3_fe_core TLS context.

    See module docstring for why the default (gunicorn_mode=False, genuine
    CERT_REQUIRED via direct injection) was chosen over core's own more
    conservative CERT_OPTIONAL acknowledgment, and the verification evidence
    behind that choice.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        tls_settings = build_tls_settings()
        gunicorn_mode = _CERT_OPTIONAL_FALLBACK
        ssl_context = make_server_ssl_context(tls_settings, gunicorn_mode=gunicorn_mode)
        if ssl_context is None:
            return

        # Config.load() only rebuilds .ssl from gunicorn's forwarded ssl_*
        # kwargs when ssl_certfile is set (see main.py's docstring for the
        # same mechanism). Nothing set those kwargs here — gunicorn.conf.py
        # deliberately leaves certfile/keyfile/cert_reqs/ca_certs unset — so
        # .load() will not touch .ssl, but it must still run once before
        # Server._serve() checks `if not config.loaded`, or this override
        # would apply to a not-yet-loaded Config and be silently lost.
        self.config.load()
        self.config.ssl = ssl_context
        _log.info(
            "GcsUvicornWorker: injected i3_fe_core TLS context "
            "(gunicorn_mode=%s, verify_mode=%s)",
            gunicorn_mode,
            ssl_context.verify_mode,
        )
