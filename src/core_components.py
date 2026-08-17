"""GCS-owned container for i3-fe-core components.

Holds the ElementIdentity + CoreSettings built from GCS's environment, plus the
core component instances built here (StateStore, notifiers, DiscrepancyReporting,
LoggingClient). ntp_client is populated separately in server.py's lifespan (the
core NtpClient requires an async start()). Hung on app.state so handlers reach
it via request.app.state.core.

Mirrors lvf-service/src/core_components.py. The GCS consumes i3-fe-core as a
LIBRARY, not a framework: it keeps its own FastAPI app and routes and wires core
components in at startup (see i3-fe-core ADOPTION.md, "Two ways to consume
core").

TRANSPORT SECURITY (spec §3.9.3, §A.8, decision 107)

CoreSettings.tls is built here from the same GCS_TLS_* variables main.py and
gunicorn.conf.py already validate for the listener, so the LoggingClient and
DiscrepancyReporting egress in build_core_components() carries the same TLS
1.2 floor and PFS cipher enforcement as the listener — following
i3-fe-core/src/i3_fe_core/app/factory.py's own wiring (`make_client_ssl_context
(settings.tls)` gated on `settings.tls.mode != TLSMode.OFF`), not
lvf-service/src/utils.py's hand-rolled outbound_ssl_context()/
outbound_client_cert(), which exists to serve LVF's peer-federation role (child
->parent sync, recursion) that the GCS does not have (spec §3.1, decision 4).
In `mtls` mode this also presents GCS_TLS_CERT_FILE/KEY_FILE as the outbound
client identity, mirroring app/factory.py exactly — the GCS's own element
certificate doubling as both server and client identity is core's own pattern,
distinct from the removed GCS_TLS_CLIENT_CERT_FILE/KEY_FILE variables (decision
107), which would have been a second, unspecified identity.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from i3_fe_core.config.identity import ElementIdentity
from i3_fe_core.config.settings import CoreSettings, TLSMode, TLSSettings
from i3_fe_core.discrepancy import DiscrepancyReporting
from i3_fe_core.logging.logging_client import LoggingClient
from i3_fe_core.security.tls import make_client_ssl_context
from i3_fe_core.state.element_state import ElementStateNotifier
from i3_fe_core.state.service_state import ServiceStateNotifier
from i3_fe_core.state.store import InProcessStateStore, StateStore
from i3_fe_core.time.ntp import NtpClient

_TLS_MODES = {"disabled": TLSMode.OFF, "tls": TLSMode.TLS, "mtls": TLSMode.MTLS}


def build_tls_settings() -> TLSSettings:
    """Build TLSSettings from GCS_TLS_* (spec §3.9.3). Mirrors the values
    main.py and gunicorn.conf.py already validate for file existence — this
    function does not re-validate, since CoreSettings.tls is also consulted
    before those checks run in some call paths (e.g. tests); the listener
    launchers remain the place a missing/unreadable file is fatal.
    """
    mode_raw = os.environ.get("GCS_TLS_MODE", "disabled").strip().lower()
    mode = _TLS_MODES.get(mode_raw, TLSMode.OFF)

    cert_file = os.environ.get("GCS_TLS_CERT_FILE", "").strip()
    key_file = os.environ.get("GCS_TLS_KEY_FILE", "").strip()
    ca_file = os.environ.get("GCS_TLS_CA_FILE", "").strip()

    return TLSSettings(
        mode=mode,
        cert_path=Path(cert_file) if cert_file else None,
        key_path=Path(key_file) if key_file else None,
        ca_path=Path(ca_file) if ca_file else None,
    )


def validate_tls_files(tls_settings: TLSSettings) -> str | None:
    """Fail-fast file-existence check shared by main.py, gunicorn.conf.py and
    server.py's lifespan — one implementation instead of three hand-copies,
    which is how GCS_TLS_CLIENT_CERT_FILE/KEY_FILE ended up silently orphaned
    in the first place (decision 107). Returns an error message naming the
    missing/misconfigured variable, or None when *tls_settings* is valid for
    its mode. Callers decide how to fail (sys.exit, RuntimeError, ...).
    """
    if tls_settings.mode not in (TLSMode.TLS, TLSMode.MTLS):
        return None

    if tls_settings.cert_path is None or not tls_settings.cert_path.exists():
        return (
            "GCS_TLS_CERT_FILE must be set and the file must exist "
            f"(got: {tls_settings.cert_path!r})"
        )
    if tls_settings.key_path is None or not tls_settings.key_path.exists():
        return (
            "GCS_TLS_KEY_FILE must be set and the file must exist "
            f"(got: {tls_settings.key_path!r})"
        )
    if tls_settings.mode == TLSMode.MTLS:
        if tls_settings.ca_path is None or not tls_settings.ca_path.exists():
            return (
                "GCS_TLS_CA_FILE must be set and the file must exist for "
                f"mtls mode (got: {tls_settings.ca_path!r})"
            )
    return None


@dataclass
class CoreComponents:
    identity: ElementIdentity
    settings: CoreSettings
    ntp_client: NtpClient | None = None
    state_store: StateStore | None = None
    element_notifier: ElementStateNotifier | None = None
    service_notifier: ServiceStateNotifier | None = None
    # Never populated. The SIP wire adapter is now built and started (see
    # src/notify/sip_notifier.py, src/app/lifecycle.py's maybe_start_sip()),
    # but its reference lives on lifecycle.py's own module state (mirroring
    # _schema/_worker there), not here — lifespan_startup()/_shutdown() are
    # called without the app object, so there is no app.state to hang it off
    # at that call site. lvf-service's identically-named field is equally
    # never populated there, for the same underlying reason: its adapter
    # reference is kept on app.state directly (server.py), not threaded
    # through this dataclass either.
    sip_notifier: object | None = None
    discrepancy: object | None = None
    logging_client: LoggingClient | None = None


def _build_dr_contact_jcard() -> list:
    """RFC 7095 jCard for the DR contact fields (§3.7.1), built from
    GCS_DR_CONTACT_NAME / GCS_DR_CONTACT_EMAIL."""
    contact_name = os.environ.get("GCS_DR_CONTACT_NAME", "")
    contact_email = os.environ.get("GCS_DR_CONTACT_EMAIL", "")

    if not contact_name:
        logging.getLogger(__name__).warning(
            "GCS_DR_CONTACT_NAME is not set — using 'GCS Administrator' in DR jCard"
        )
    if not contact_email:
        logging.getLogger(__name__).warning(
            "GCS_DR_CONTACT_EMAIL is not set — DR jCard contact email will be empty"
        )

    return [
        "vcard",
        [
            ["fn", {}, "text", contact_name or "GCS Administrator"],
            ["email", {}, "text", contact_email or ""],
        ],
    ]


def build_core_components() -> CoreComponents:
    server_uri = os.environ.get("GCS_SERVER_URI", "gcs.example.com")

    identity = ElementIdentity(
        element_id=server_uri,
        agency_id=os.environ.get("GCS_AGENCY_ID", server_uri),  # dev default
        service_name="GCS",  # IANA serviceNames token, i3 §10.11
    )
    settings = CoreSettings(
        log_level=os.environ.get("GCS_LOG_LEVEL", "INFO"),
        ntp_servers=[os.environ.get("GCS_NTP_SERVER", "pool.ntp.org")],
        tls=build_tls_settings(),
    )

    state_store = InProcessStateStore()

    # Egress TLS (spec §3.9.3, decision 107): Logging Service POSTs and DR
    # resolution callbacks/submissions carry the same TLS 1.2 floor and PFS
    # cipher enforcement as the listener, instead of httpx's plaintext-capable
    # defaults. Built only when GCS_TLS_MODE != disabled, matching
    # i3_fe_core.app.factory.create_app()'s own gating.
    _outbound_http: httpx.AsyncClient | None = None
    if settings.tls.mode != TLSMode.OFF:
        _outbound_http = httpx.AsyncClient(verify=make_client_ssl_context(settings.tls))

    logging_client = LoggingClient(
        identity=identity,
        logging_service_uri=os.environ.get("GCS_LOGGING_SERVICE_URI", "") or None,
        http_client=_outbound_http,
    )

    element_notifier = ElementStateNotifier(
        identity,
        state_store,
        min_notify_interval=1.0,
        logging_client=logging_client,
    )

    service_domain = os.environ.get("GCS_SERVICE_DOMAIN", identity.element_id)
    service_notifier = ServiceStateNotifier(
        service=service_domain,
        name="GCS",
        domain=service_domain,
        service_id=service_domain,
        store=state_store,
        min_notify_interval=1.0,
        # The GCS handles no calls and holds no credentials beyond its own TLS
        # material, so it maintains no §10.18 security posture — same position
        # LVF takes. i3 §2.4.2 requires securityPosture to be ABSENT (not null)
        # when a service does not maintain one.
        supports_security_posture=False,
        logging_client=logging_client,
    )

    _dr_http: httpx.AsyncClient | None = None
    if settings.tls.mode != TLSMode.OFF:
        _dr_http = httpx.AsyncClient(verify=make_client_ssl_context(settings.tls))

    discrepancy = DiscrepancyReporting(
        identity=identity,
        contact_jcard=_build_dr_contact_jcard(),
        agent_id=os.environ.get("GCS_AGENCY_ID") or None,
        logging_client=logging_client,
        http_client=_dr_http,
    )

    return CoreComponents(
        identity=identity,
        settings=settings,
        state_store=state_store,
        element_notifier=element_notifier,
        service_notifier=service_notifier,
        discrepancy=discrepancy,
        logging_client=logging_client,
    )
