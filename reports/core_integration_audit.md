# i3-fe-core Integration Audit

> **SUPERSEDED SNAPSHOT — read as history, not as current state.** This audit
> was written before decision 107. Its central finding, that the GCS is
> "materially under-integrated with core's security layer" and imports
> `i3_fe_core.security.tls` / `.peer_auth` nowhere, is **no longer true**:
> `main.py`, `gunicorn.conf.py`, `src/app/gunicorn_worker.py` and
> `src/core_components.py` all build their SSL contexts through
> `i3_fe_core.security.tls`, and `tests/security/` verifies the resulting
> handshakes live. The capability table below is likewise a point-in-time
> reading. Kept because the reasoning that identified the gap is still worth
> reading; the root `CLAUDE.md` is authoritative for what is wired today.

Audit-only. No source files were modified. Scope: what `../i3-fe-core`
(sibling checkout, pinned at `v0.4.0` in `requirements.txt`) provides, what
the GCS is obligated by NENA-STA-010.3f-2021 to use, what it actually wires
today, and what core surface the GCS correctly declines to adopt.

## Bottom line

The GCS is **materially under-integrated with core's security layer**, not
just behind on the four items the spec's own Appendix C.3 already names as
deferred (SIP transport, GCS log-event types, discrepancy filing, load
shedding). `i3-fe-core.security.tls` and `i3-fe-core.security.peer_auth` —
the modules that discharge §2.8.1 (TLS 1.2 floor, no TLS 1.0/1.1, PFS
ciphers) and §5.4 (PCA-traceable mutual authentication) — are imported
**nowhere** in `src/`. `main.py` and `src/server.py` build TLS by hand,
passing raw file paths straight to `uvicorn.run()`; in `mtls` mode this sets
`ssl.CERT_OPTIONAL` and stops there, with a comment in `main.py` that
correctly names `security.peer_auth` as the compensating control and then
does not wire it. This is a fifth deferred item that the spec's Appendix C.3
does not record alongside the other four. Once that gap is fixed, the
remaining distance to full integration genuinely is the four known items —
core's non-security surface (identity, NTP, state notifiers, GIS dataset
cache, metrics, Versions, the DR *responding* role) is wired completely and
correctly.

## Capability table

Bucket key: **A** wired/complete · **B** wired but partial · **C** not
wired, GCS is obligated · **D** not wired, not required of a GCS · **E**
unclear.

| Core capability | Bucket | Rationale | Citation |
|---|---|---|---|
| `config.identity.ElementIdentity` | A | Built once in `core_components.py` from `GCS_SERVER_URI`/`GCS_AGENCY_ID`, shared everywhere identity is needed. | i3 §2.1 |
| `config.settings.CoreSettings` (minus `.tls`) | A | `log_level`, `ntp_servers` passed through. | — |
| `config.settings.TLSSettings` / `CoreSettings.tls` | C | Never set — `CoreSettings(...)` in `core_components.py` omits `tls=`, so it silently defaults to `TLSMode.OFF` regardless of the real `GCS_TLS_MODE` env var, which is read independently and ad hoc in `main.py`/`server.py`. | i3 §2.8.1 |
| `time.ntp.NtpClient` | A | Started in `server.py`'s lifespan, exposed via `runtime_state.now()` for i3-timestamp correction, drives `/health`'s `ntpHealthy`. | i3 §4.3.5, §2.2 |
| `state.store.InProcessStateStore` | A | One store shared by both notifiers via `core_components.py`. | §2.4 design |
| `state.element_state.ElementStateNotifier` | A | Driven by `app/lifecycle.py`'s GIS-load/reload callbacks; read via `GET /ElementState`. | i3 §4.5, §4.3.5 (Appendix A.4) |
| `state.service_state.ServiceStateNotifier` | A | `supports_security_posture=False` is a deliberate, cited opt-out (see bucket D). Read via `GET /ServiceState`. | i3 §4.5 (Appendix A.5) |
| `web_service.versions.build_version_entry` / `make_versions_route` | A | Mounted at `/Gcs/Versions` and `/dr/Versions` (decisions 95, 98). | i3 §2.8.3, §4.12 (Appendix A.1) |
| `discrepancy.service.DiscrepancyReporting` — responding role | A | Mounted at `/dr` + root aliases against one shared instance (decision 98); receives/tracks/resolves DRs. | i3 §3.7, §4.9 (Appendix A.6) |
| `discrepancy.service.DiscrepancyReporting` — reporting-role hooks (`on_report`, `authorize_reporter`, `authorize_responder`, `known_problem_services`) | B | Constructed with none of these — see Bucket B detail below. | i3 §3.7.1, §5.4 |
| `discrepancy.routes.make_discrepancy_routes` | A | Both mount points wired in `server.py`. | i3 §3.7.1–3.7.3 |
| `gis.DatasetCache` / `gis.dataset.DatasetSpec` | A | `GcsDatasetSpec` in `src/gis/provisioning.py` implements the protocol fully — mtime-keyed reload, cache serialize/restore, consistent-snapshot reads by reference. | design (Appendix A.7 context) |
| `observability.metrics` (`ensure_multiproc_dir`, `metrics_app`, `clear_multiproc_dir`, `mark_worker_dead`) | A | Wired in `src/observability/metrics.py` and `main.py`; `/metrics` mounted in `server.py`. | — (ops, no i3 citation) |
| `runtime.worker.WorkerContext` / `SingleWorkerContext` | A | Used as the leader gate for the GIS reload watcher thread in `app/lifecycle.py`. | design rule 4 |
| `logging.logging_client.LoggingClient` | B | Instantiated and passed to the element/service notifiers and to `DiscrepancyReporting`, so `ElementStateChangeLogEvent`, `ServiceStateChangeLogEvent`, and `DiscrepancyReportLogEvent` **are** emitted. No GCS code calls `.emit()`/`.emit_nowait()` directly anywhere in `src/` — confirmed by grep, zero hits outside those three internal call sites. | i3 §4.12.3.1 (Appendix A.3) |
| `logging.logevent.LogEventPrologue` subclassing pattern | C | `src/logging/` is an empty stub; no `GcsQueryLogEvent`/`GcsResponseLogEvent` exist, so the §4.5 payload-logging MUST is entirely unmet for conversion traffic. | i3 §4.5, §4.12.3.7 (Appendix A.3, decision 104) |
| `app.factory._RequestLoggingMiddleware` (per-request `AccessLogEvent`) | C — *implicitly, by omission* | This exists in core but only inside `create_app()`, which the GCS does not use (library-consumption pattern). The GCS has no equivalent middleware anywhere, so **no LogEvent of any kind is emitted for an HTTP request that isn't itself a state change or a DR**. This is a consequence of the library-vs-framework choice (correctly made, see below) but leaves a hole the GCS must fill itself. | i3 §4.12.3.1 |
| `notify.sip_notifier.SipNotifier` | C | `core_components.py`'s `sip_notifier` field is `object \| None`, permanently `None`. Confirmed by grep: no code anywhere constructs a `SipNotifier`. | i3 §4.5 (identical MUST to MCS's §4.4) (Appendix A.4/A.5) |
| `security.tls.make_server_ssl_context` / `make_client_ssl_context` | C | Zero imports of `i3_fe_core.security` anywhere in `src/`. `main.py` builds `ssl_certfile`/`ssl_keyfile`/`ssl_cert_reqs` kwargs for `uvicorn.run()` directly, bypassing core's TLS-1.2-floor enforcement and its explicit PFS-only cipher string (`_PFS_CIPHERS_TLS12`, which excludes static-RSA suites that plain `ssl.PROTOCOL_TLS_SERVER` defaults do not necessarily exclude). | i3 §2.8.1 (Appendix A.8) |
| `security.peer_auth.ProxyClientCertMiddleware` / `PeerCertVerifier` | C | Not wired. `main.py`'s `mtls` path sets `ssl_cert_reqs=ssl.CERT_OPTIONAL` and stops — its own comment names `security.tls`/`security.peer_auth` as "the §5.4 application-layer compensating control" and does not add it. No middleware verifies a forwarded client certificate anywhere in `src/`. | i3 §5.4 (Appendix A.8) |
| TLS-aware outbound `httpx.AsyncClient` for `LoggingClient`/`DiscrepancyReporting` (`make_client_ssl_context(settings.tls)`) | C | Core's own `create_app()` builds these outbound clients from `settings.tls` when TLS is enabled (`app/factory.py` lines ~194–216). `core_components.py` passes no `http_client=` to either constructor, so both use plain `httpx.AsyncClient()` defaults for calls to the Logging Service and DR resolution callbacks — regardless of `GCS_TLS_MODE`. `.env.example` documents `GCS_TLS_CLIENT_CERT_FILE`/`GCS_TLS_CLIENT_KEY_FILE` for exactly this purpose; neither variable is read by any code (grep, zero hits). | i3 §2.8.1 |
| `state.store.SecurityPosture` / `ServiceStateNotifier(supports_security_posture=...)` | D | Deliberately `False` — see Bucket D. | i3 §2.4.2, §10.18 |
| `testing.make_test_credential` | D | No mTLS is exercised anywhere in the GCS test suite (consistent with TLS/mTLS being unwired — see bucket C), so there is nothing for this helper to support yet. Revisit once the security-layer gap above is closed. | NG-SEC §6.23.8, §6.9 |
| `conformance.checks.assert_core_conformance` | E | Not run against the GCS app anywhere found in `tests/`. See Bucket E. | — |

## Bucket C — not wired, GCS is obligated

### C.1 SIP transport (`notify.sip_notifier.SipNotifier`)

Already fully documented in `CLAUDE.md` and spec Appendix C.3: `ElementState`
and `ServiceState` are reachable over HTTP but not published over SIP. i3 §4.5
places the identical MUST on the GCS that §4.3.5/§4.4 place on other FEs
(ADOPTION.md states this explicitly for the MCS/GCS pair). What's missing
GCS-side: the FE-owned SIP socket adapter (`src/notify/`, currently an empty
stub with an accurate docstring) that would call `SipNotifier.handle_subscribe`
and supply a `send_notify` callback. Core's half — the notifier, the RFC 6446
rate filter/watchdog, the RFC 6665 SUBSCRIBE state machine, the §5.4
authorization hook seam — is complete and unit-tested; nothing there blocks
adoption. Nothing breaks today in the sense of an exception; the conformance
gap is silent (a SIP client that SUBSCRIBEs gets no response at all, since
there is no SIP listener).

### C.2 TLS transport security (`security.tls`)

**Not recorded in spec Appendix C.3's deferred-work list — this is the
audit's primary finding.** §2.8.1 is unconditional: every i3 service MUST
support HTTPS, MUST support TLS 1.2, MUST NOT offer TLS 1.0/1.1, and MUST use
perfect forward secrecy within the ESInet. `security.tls.make_server_ssl_context`
implements exactly this (minimum-version pinning, an explicit PFS-only cipher
string for TLS 1.2, TLS-1.3-is-always-PFS reasoning documented in its
docstring) and is never called. Instead:

- `main.py` passes `ssl_certfile`/`ssl_keyfile` straight to `uvicorn.run()`.
  Uvicorn's own SSL context is not guaranteed to match core's explicit
  `_PFS_CIPHERS_TLS12` cipher selection (which deliberately excludes static
  RSA key exchange — no PFS) or its `minimum_version = TLSv1_2` (with the
  accompanying comment on why `OP_NO_TLSv1`/`OP_NO_TLSv1_1` are the wrong,
  deprecated mechanism).
- Nothing in the GCS verifies at startup or at runtime that the negotiated
  cipher suite is PFS-capable.

What wiring it would take: build `settings.tls` in `core_components.py` from
the already-parsed `GCS_TLS_*` env vars, and pass
`make_server_ssl_context(settings.tls, gunicorn_mode=...)`'s result into
`uvicorn.run(ssl=...)` (dev) and into `gunicorn.conf.py` (production —
core's own `app/factory.py` docstring documents passing the context to
gunicorn rather than uvicorn in that deployment). What breaks today without
it: nothing observable in a functional test — the gap is a compliance
posture, not a crash — but a deployment relying on `GCS_TLS_MODE=tls` today
gets whatever TLS 1.2/1.3 negotiation Python's `ssl` module defaults to via
uvicorn, not the specifically-audited PFS-restricted cipher set §2.8.1 calls
for.

### C.3 Peer certificate verification (`security.peer_auth`)

§5.4: "Mutual Authentication MUST be used for TLS and SIP session
establishment using a certificate traceable to the PCA." `mtls` mode in
`main.py` sets `ssl_cert_reqs=ssl.CERT_OPTIONAL` — i.e., a client certificate
is requested but a connection without one is still accepted — with a comment
stating plainly: *"this is not equivalent to enforcing mTLS. See i3-fe-core
security.tls for the §5.4 application-layer compensating control."* That
compensating control (`ProxyClientCertMiddleware` + `PeerCertVerifier`,
verifying a proxy-forwarded client cert against PCA trust anchors) is never
added to `app.add_middleware(...)` in `server.py`. The practical consequence:
in the one deployment mode where TLS termination happens at a reverse proxy
(the mode the code's own comments anticipate — `gunicorn`+`UvicornWorker`),
**no code path in the GCS enforces §5.4 at all**. This also means the
`/dr/Reports` responding endpoint (Bucket B below) has no authenticated
caller identity available even if it wanted to check one.

What wiring it would take: populate `TLSSettings.proxy_terminated_tls`,
`client_cert_header`, `pca_trust_anchors`, `trusted_proxies` in
`core_components.py` from new/existing `GCS_TLS_*` env vars, and add
`ProxyClientCertMiddleware` to `server.py`'s middleware stack (before
`LimitBodySize`/`MetricsMiddleware`, mirroring core's own ordering — "peer
auth runs before request logging"). What breaks today without it: nothing
observable — this is a silent authorization gap, not a functional failure.

### C.4 TLS-aware outbound HTTP clients for Logging/DR

A narrower instance of C.2: even if server-side TLS were fixed, the
*outbound* calls this process makes — `LoggingClient._post()` to the Logging
Service, `DiscrepancyReporting.submit()`/`.resolve()` to DR peers — use
`httpx.AsyncClient()` with no `verify=` override, because
`core_components.py` never builds `settings.tls` or passes
`make_client_ssl_context(settings.tls)` as core's own `create_app()` does.
`.env.example` already reserves `GCS_TLS_CLIENT_CERT_FILE`/
`GCS_TLS_CLIENT_KEY_FILE` for this and neither is read anywhere — see
"Appendix A inaccuracies" below; this is also a `.env.example` contract
violation in its own right (CLAUDE.md: "every variable the service reads").

### C.5 GCS-specific LogEvent types (`logging/`)

Already documented (spec decision 104, `src/logging/__init__.py`'s
docstring). Core provides the `LogEventPrologue` base, `to_i3_json_key`
camelCase serialization, the conditional-field-absent-not-null contract, and
`LoggingClient.emit`/`emit_nowait`. What's missing GCS-side: the
`GcsQueryLogEvent`/`GcsResponseLogEvent` dataclasses this document already
proposes, and the call sites in `src/api/geocode.py`/`reverse_geocode.py`
(or a middleware layer analogous to core's `_RequestLoggingMiddleware`) that
would construct and emit them per conversion request. Nothing breaks
today; the payload-logging MUST (i3 §4.5) is simply unmet.

### C.6 Discrepancy filing (`src/discrepancy/`)

Already documented (spec decision 99). Core's `DiscrepancyReporting.build_report()`
and `.submit()` (with the §3.7 SHOULD-level similarity rate limit already
implemented) are ready to receive calls; what's missing GCS-side is the
translation from `src/engine/models.py`'s `DataQualityFlag` values (GIS
load/reload failure, null NGUID, multi-part RCL segment, no usable geometry)
into `build_report()` calls at the point each condition is detected. Nothing
breaks today beyond the DR feedback loop to the SI simply not firing.

## Bucket B — wired but partial (detail)

**`LoggingClient`.** Fully functional for the three internal call sites core
already drives it from (element/service state changes, DR lifecycle events,
SUBSCRIBE processing — the last one moot while C.1 is unwired). Zero direct
calls from GCS-authored code. This is the same gap as C.5 from a different
angle: the client is wired, the GCS-specific *events* are not.

**`DiscrepancyReporting` responding-role hooks.** The DR web service accepts
reports from any reporter (`authorize_reporter` unset → accept-all, with a
one-time warning logged, mirroring `SipNotifier`'s own unguarded-subscribe
pattern) and does nothing beyond storing the report (`on_report` unset — no
operator alert is fired; §3.7's own text says "humans usually act on DRs").
`known_problem_services` is unset, so `problemService` is never checked
against a real allow-list — every report is accepted regardless of what it's
about, rather than 470'ing reports that aren't the GCS's concern. This is
survivable today only because C.3 (peer auth) is also unwired, so there is no
authenticated identity to hand `authorize_reporter` anyway — fixing C.3
without also wiring these hooks would leave any authenticated peer able to
file unlimited reports.

## Bucket D — scope decisions (deliberately not adopted)

### D.1 `securityPosture` support

`ServiceStateNotifier(supports_security_posture=False, ...)` in
`core_components.py`, with an inline citation: "The GCS handles no calls and
holds no credentials beyond its own TLS material, so it maintains no §10.18
security posture — same position LVF takes." §2.4.2 requires
`securityPosture` to be **absent** (not null) when a service does not
maintain one, so this is not merely unimplemented — it's a citable stance
that adopting `SecurityPosture`/`securityPosture` reporting would itself be
wrong for a GCS, which files no dynamic threat-level assessment of its own
(unlike an MCS/ECRF fielding live call signaling). Scoped away by: the GCS
having no call-handling or credential-issuing role for which a security
posture would be meaningful (i3 §2.4.2's own conditional-presence rule).

### D.2 core's identity-agnostic design leaves little sibling-only surface to decline

Worth stating explicitly since it bears on the audit's own premise: `README.md`'s
design rule 1 ("Identity-agnostic core... lets ECRF and LVF coexist in the
same process space") means i3-fe-core, unlike a monolithic framework, does
not actually expose LVF/ECRF/MCS-specific *routes or domain logic* as
importable surface — `ADOPTION.md`'s LVF/MCS sections are worked examples of
how to *use* the generic pieces, not core modules reserved for those FEs.
Every module under `src/i3_fe_core/` (`config`, `time`, `state`, `notify`,
`discrepancy`, `logging`, `security`, `runtime`, `app`, `gis`,
`observability`, `conformance`, `testing`) states a cross-cutting §2.x/§3.7/
§4.12/NG-SEC obligation that binds a GCS exactly as it binds any other FE.
Beyond D.1, there is no sibling-only surface in this package for the GCS to
have correctly declined.

## Bucket E — unclear

**E.1 — Which outbound HTTP paths specifically require mTLS vs. TLS-with-server-auth-only?**
Spec Appendix A.8 states the §2.8.1 posture at a summary level ("HTTPS
mandatory... perfect forward secrecy within the ESInet") but doesn't dissect
whether the Logging Service POST, the SI/GIS provisioning feed (out of
scope per A.7, mechanism-agnostic), and DR resolution callbacks to arbitrary
reporter-supplied `resolutionUri` values all carry the identical §5.4 mutual
-auth obligation, or whether some of these (e.g., a callback to a URI the
*reporter* controls, not a fixed peer FE) are TLS-server-auth-only by nature
of not being a "peer FE" relationship in the §5.4 sense. This matters for
how `make_client_ssl_context` should be parameterized once C.4 is fixed —
resolving it would sharpen exactly what `TLSMode.MTLS` should require for
the DR reporting role's outbound leg.

**E.2 — Should `assert_core_conformance` run against the live GCS app?**
`i3-fe-core.conformance.checks.assert_core_conformance(app, identity)` is
core's own statement of what a correctly-wired FE looks like (ElementState/
ServiceState body shape, `/health` presence, DR resource probing, IANA
registry exactness, NTP wiring, timestamp format). No test in
`tests/conformance/` was found invoking it against `src.server.app`. Given
this repo's own `tests/conformance/` naming convention already tracks i3
conformance by a different meaning of the word (spec-derived behavioral
tests), it's unclear whether running core's helper is intended to be
additional (catching exactly the kind of drift this audit found) or
considered redundant with the hand-written suite. Given that the SIP,
security, and (partly) logging gaps above are all things
`assert_core_conformance` does *not* check (it doesn't probe TLS/mTLS or
SIP), wiring it would not have caught this audit's main finding — but it
would be a cheap regression guard for the parts it does cover (ElementState/
ServiceState/health/DR shape) that the current hand-written tests may or may
not fully overlap with. Resolving this is a question of test-suite intent,
not of i3 obligation.

## Appendix A accuracy check

- **A.8 Security** — states "i3-fe-core security.tls / security.peer_auth"
  as the discharging module with no qualifying note. Given C.2/C.3/C.4
  above, this line is misleading as currently written: it reads as "handled,"
  the way A.1/A.2/A.4/A.5/A.6/A.7's parallel lines correctly do for their
  capabilities, but the module is not imported anywhere in `src/`. Every
  other Appendix A row that has an unresolved gap (A.3, A.4/A.5 via the SIP
  note, A.6) carries either a `✔ Settled` callout explaining the current
  state or a cross-reference to the deferred-work list in `CLAUDE.md`/spec
  Appendix C.3. A.8 has neither. Recommend either adding a callout matching
  A.4's SIP-gap note, or adding this gap to Appendix C.3 alongside the other
  four deferred items — it belongs there by the same standard.
- All other Appendix A rows (A.1 Versions, A.2 NTP, A.3 Logging, A.4
  ElementState, A.5 ServiceState, A.6 Discrepancy Reporting, A.7 SI/SDPI)
  check out accurately against current code: module names, mount points, and
  the caveats they do carry (A.3's "logging.logging_client is wired; the
  event types are not," A.6's `/dr` canonical-base note) all match what was
  found.

## Beyond scope

- **`.env.example` documents two variables no code reads.**
  `GCS_TLS_CLIENT_CERT_FILE`/`GCS_TLS_CLIENT_KEY_FILE` (lines ~268–269, under
  "Client credentials for outbound mTLS to peer FEs") are grep-confirmed
  unread anywhere in `src/`. `CLAUDE.md` states `.env.example`'s contract
  explicitly: "every variable the service reads, its default, and whether it
  is `[REQUIRED]` or a `[PROPOSAL]`." These two variables violate that
  contract today — they're either premature documentation for C.4's future
  fix (in which case a `# not yet read — see reports/core_integration_audit.md`
  note would keep the contract honest) or dead entries to remove.
- **`GCS_TLS_MODE=mtls` today provides no more authentication than
  `GCS_TLS_MODE=tls`.** Since `ssl_cert_reqs=ssl.CERT_OPTIONAL` in `mtls`
  mode (main.py) accepts connections both with and without a client
  certificate, and nothing downstream checks whether one was presented, an
  operator who sets `GCS_TLS_MODE=mtls` believing it enforces mutual
  authentication is not getting that guarantee — the mode name currently
  overpromises relative to what it does. This is downstream of C.3 and
  would be closed by the same fix.
