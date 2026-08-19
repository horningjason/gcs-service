# Prior Art: TLS / mTLS / Peer Authentication in the i3-fe-core Sibling Family

> **POINT-IN-TIME SNAPSHOT.** Written before decision 107. Its findings about
> the *siblings* still stand and are the reasoning decision 107 rests on, but
> its statements about what the GCS wires are historical: the GCS now builds
> every SSL context through `i3_fe_core.security.tls`. Two details have also
> gone stale — `gcs-service` is now a git repository, and the LVF episode
> described below is guarded against here by `tests/security/`.

Audit-only. No file in this repo or in `../mcs-service`, `../lvf-service`, or
`../i3-fe-core` was modified. Both sibling repos were located one directory
up from `gcs-service`: `D:\geosos\software\projects\mcs-service` and
`D:\geosos\software\projects\lvf-service`. Both are git repositories with
usable history; `gcs-service` was not a git repo when this was written, so no
equivalent archaeology was possible for the GCS's own TLS code.

## Bottom line

**Neither sibling wires `i3_fe_core.security.tls` or `i3_fe_core.security.peer_auth`
either.** Grepping both trees for `i3_fe_core.security`, `ProxyClientCertMiddleware`,
`PeerCertVerifier`, `make_server_ssl_context`, `make_client_ssl_context` returns
zero hits in `mcs-service` and zero hits in `lvf-service`. The GCS's security
posture is **not a regression from a working LVF/MCS pattern** — it is the
same gap, present in all three services, none of which wired core's security
layer.

Where the three genuinely diverge:

- **LVF once enforced `ssl.CERT_REQUIRED`** for inbound mTLS (both in
  `main.py` and in a hand-built `ssl.SSLContext` for `gunicorn.conf.py`),
  discovered that `UvicornWorker` silently downgrades unenforced `cert_reqs`
  to `CERT_NONE`, and reverted to `CERT_OPTIONAL` — all on 2026-06-22, **two
  weeks before LVF adopted `i3-fe-core` at all** (`requirements.txt` gained
  its first `i3-fe-core` pin on 2026-07-05, per git history below). LVF's
  current unwired state is not a considered rejection of core's security
  module; the mTLS attempt and its revert happened, ran into exactly the
  gunicorn+UvicornWorker bug that `i3_fe_core.security.tls`'s own docstring
  names as its reason for existing, and was abandoned before core's answer to
  that bug (proxy-terminated mTLS + `ProxyClientCertMiddleware`) was
  available to LVF's authors.
- **LVF wires outbound TLS for its own federation traffic** (`src/utils.py`'s
  `outbound_ssl_context()`/`outbound_client_cert()`, consumed in
  `src/federation/recursion.py` and `src/federation/sync.py`) using
  hand-rolled `httpx` `verify=`/`cert=` parameters — not core's
  `make_client_ssl_context`. This traffic (child→parent sync push/pull,
  recursion) has no GCS analogue: the GCS has no peer-node federation (spec
  §3.1, decision 4, already cited in this repo).
- **MCS has no outbound TLS configuration of any kind** — no
  `outbound_ssl_context` equivalent, no `verify=`/`cert=` override anywhere,
  and (confirmed by grep) makes no direct outbound `httpx` calls in its own
  code at all. MCS also has no `gunicorn.conf.py` — its only deployment path
  is single-process `main.py` + uvicorn.
- **GCS's orphaned `.env.example` variables have an identified origin.**
  `GCS_TLS_CLIENT_CERT_FILE`/`GCS_TLS_CLIENT_KEY_FILE` are near-verbatim
  copies of `LVF_TLS_CLIENT_CERT_FILE`/`LVF_TLS_CLIENT_KEY_FILE`, which in
  LVF **are** read (by `src/utils.py::outbound_client_cert()`, consumed by
  LVF's federation calls). The GCS's `.env.example` inherited the variable
  names and prose from the LVF template without inheriting a consumer,
  because the GCS has no federation traffic to consume them for and never
  wired them to its actual outbound traffic (Logging Service POSTs, DR
  resolution callbacks) — which, per `core_integration_audit.md`, LVF itself
  also never wires to any TLS configuration.

## 1. Per-sibling findings

### 1.1 MCS

**Launch mechanism** — `mcs-service/main.py:1-66`. Structurally identical to
this repo's `main.py`: reads `MCS_TLS_MODE` (default `"disabled"`), and for
`tls`/`mtls` passes `ssl_certfile`/`ssl_keyfile` straight into
`uvicorn.run(**kwargs)` (line 62). No `gunicorn.conf.py` exists anywhere in
the MCS repo (confirmed by `find -iname "gunicorn*"`, which returns only
`.venv` package files) — MCS has no multi-worker production path at all,
unlike LVF and GCS.

**mTLS handling** — `mcs-service/main.py:46-60`. In `mtls` mode, sets
`kwargs["ssl_cert_reqs"] = ssl.CERT_OPTIONAL` (line 60), with an inline
comment (lines 56-59): *"CERT_OPTIONAL: requests a client certificate but
does not require one — connections without a client cert are still accepted.
Known limitation: this is not equivalent to enforcing mTLS."* No application
-layer compensating control exists anywhere in `src/` (grep for
`X-SSL-Client-Cert`, `verified_peer`, `client_cert`, `mtls_required` across
the whole MCS tree returns zero hits).

**Outbound clients** — Grep for `httpx.AsyncClient|httpx.Client|verify=`
across the entire MCS repository returns **zero hits**. MCS makes no direct
outbound HTTP calls in its own code. Its only outbound traffic is whatever
core's `LoggingClient` performs internally, and `mcs-service/src/core_components.py:65-68`
constructs that `LoggingClient` with no `http_client=` override — same gap as
GCS (`core_integration_audit.md` bucket C.4). MCS builds no
`DiscrepancyReporting` at all: `core_components.py:1-13`'s module docstring
states *"No DiscrepancyReporting instance is built here — NENA §3.7 DR is
deferred for MCS (see CLAUDE.md)"* — MCS's DR gap is a separate, already
-acknowledged deferral, not part of this audit's security scope.

**`.env.example` vs. code** — `mcs-service/.env.example:80-94` documents
`MCS_TLS_MODE`, `MCS_TLS_CERT_FILE`, `MCS_TLS_KEY_FILE`, `MCS_TLS_CA_FILE`.
All four are read by `main.py` (confirmed above) — **no orphaned variables**
in MCS's TLS section. MCS defines no client-cert variables at all (it has no
outbound-mTLS consumer to need them for), so there is nothing analogous to
GCS's orphaned pair to go missing.

**Git history** — `mcs-service` has two commits total:
`0c75ca8 2026-06-27 Initial commit` and
`6be90ae 2026-07-13 Updating to work with i3-fe-core`. `git show 6be90ae --stat`
shows the i3-fe-core adoption commit touched `core_components.py`,
`app/lifecycle.py`, `gis/provisioning.py`, `logging/`, `notify/`,
`observability/metrics.py`, `runtime_state.py`, and `server.py` — **`main.py`
is not in the diff.** MCS's TLS handling in `main.py` was already in the
`0c75ca8` initial commit, before i3-fe-core was a dependency, and was never
touched when i3-fe-core was wired in.

### 1.2 LVF

**Launch mechanism** — `lvf-service/main.py:1-73`, structurally identical to
GCS's and MCS's `main.py` (reads `LVF_TLS_MODE`, passes `ssl_certfile`/
`ssl_keyfile`/`ssl_ca_certs`/`ssl_cert_reqs` to `uvicorn.run()`). LVF also has
a `gunicorn.conf.py` (present in the repo root) with a parallel TLS block at
lines 42-71, explicitly commented `# ── TLS (mirrors main.py) ──`.

**mTLS handling — current state.** `lvf-service/main.py:63` and
`lvf-service/gunicorn.conf.py:71` both set `cert_reqs`/`ssl_cert_reqs` to
`ssl.CERT_OPTIONAL`, with the identical "Known limitation... not equivalent
to enforcing mTLS" comment found in GCS and MCS
(`main.py:63-66`, `gunicorn.conf.py:68-70`). No application-layer
compensating control exists in LVF's `src/` today (same zero-hit grep result
as MCS).

**mTLS handling — history (the code disagrees with an earlier version of
itself, and the current comments say so honestly).** `git log --oneline --all
--date=short --format="%h %ad %s" -- gunicorn.conf.py main.py src/utils.py`
in `lvf-service` shows, in order:

```
f566135 2026-06-16 Security: C-2 replace pickle cache with JSON; TLS/mTLS support (C-1)
...
5590e75 2026-06-22 TLS work
c713cb5 2026-06-22 mTLS work
900f5cd 2026-06-22 mTLS work, continued
b36d4f8 2026-06-22 mTLS gunicorn
d22c312 2026-06-22 Reverting mTLS work
fb95666 2026-06-22 mTLS completion and documentation
```

`git show d22c312` (the revert) removes, from `gunicorn.conf.py`, a hand
-built `ssl.SSLContext` with `verify_mode = ssl.CERT_REQUIRED` that had been
added specifically **because** (per the deleted comment) *"UvicornWorker
defaults to CERT_NONE if cert_reqs is not honoured"* — i.e., LVF's authors
independently discovered the exact gunicorn+UvicornWorker mTLS-enforcement
bug that `i3_fe_core.security.tls`'s module docstring (`i3-fe-core/src/i3_fe_core/security/tls.py:16-29`)
names as its own reason for existing, and gave up on handshake-level
enforcement rather than solve it. The same commit changes `main.py`'s
`ssl_cert_reqs` from `CERT_REQUIRED` to `CERT_OPTIONAL`. The very next
commit, `fb95666`, rewrites `.env.example` and `README.md` to be honest about
the resulting gap — `lvf-service/.env.example:244-246`: *"CERT_OPTIONAL
rather than CERT_REQUIRED, and there is no app-level enforcement (removed;
see git history). Do not rely on LVF_TLS_MODE=mtls alone for inbound access
control."* This is a rare case in the family where a comment is *more*
honest than the mechanism it describes needs it to be — worth noting given
the audit's general caution about comments outliving the code.

**Timing relative to i3-fe-core adoption.** `git log --oneline --all
--date=short -- requirements.txt` in `lvf-service` shows no `i3-fe-core`
line in `requirements.txt` until `7fdf906 2026-07-05 Refactoring and
implementation of i3 core functionality` — confirmed directly by
`git show f566135:requirements.txt` and `git show d22c312:requirements.txt`
(the mTLS work and its revert), both of which list `fastapi`, `uvicorn`,
`gunicorn`, `python-dotenv`, `pydantic` and **no `i3-fe-core`**. The mTLS
build-and-revert cycle is dated 2026-06-16 through 2026-06-22; the first
`i3-fe-core` pin lands 2026-07-05, upgraded to `v0.4.0` on
`94404d3 2026-07-13 Upgrade pinned i3-fe-core dependency to v0.4.0`. **LVF's
mTLS work predates its adoption of i3-fe-core by roughly two weeks**, and
`main.py`/`gunicorn.conf.py`'s TLS blocks were not revisited in the
`7fdf906` or `94404d3` commits (not in either commit's diff — confirmed by
`git show <sha> --stat`, not reproduced here for brevity but checkable the
same way as the MCS check above). This directly confirms the prompt's
hypothesis: LVF's non-adoption of `security.tls`/`security.peer_auth` is not
a considered choice against those modules; the modules were never in the
picture at the point the design question was live.

**Outbound clients.** `lvf-service/src/utils.py:37-59` defines
`outbound_ssl_context()` (returns `LVF_TLS_CA_FILE` path or `True`) and
`outbound_client_cert()` (returns `(LVF_TLS_CLIENT_CERT_FILE,
LVF_TLS_CLIENT_KEY_FILE)` tuple or `None`), both hand-rolled — not calls into
`i3_fe_core.security.tls`. These are consumed at three call sites:
`src/federation/recursion.py:132,180` and `src/federation/sync.py:489,593,654`
— all LVF-to-LVF federation traffic (child→parent sync push/pull, parent
→forest-guide push, recursive `findService` calls), which has no GCS
equivalent. **This wiring is inconsistent within LVF itself**: one more
outbound call, `src/lost/list_services_by_location.py:326`
(`async with httpx.AsyncClient(timeout=10.0) as client:`), uses plain httpx
with no `verify=`/`cert=` override at all — a LoST server-to-server call that
arguably belongs in the same trust boundary as the federation calls but isn't
wired to it. Neither LVF's `LoggingClient` nor its `DiscrepancyReporting`
(`lvf-service/src/core_components.py:77-102`) receives an `http_client=`
override — both use plain `httpx.AsyncClient()` defaults, identical to the
gap `core_integration_audit.md` found in GCS.

**`.env.example` vs. code — no drift, and it explains GCS's drift.**
`lvf-service/.env.example:247-273` documents `LVF_TLS_MODE`,
`LVF_TLS_CERT_FILE`, `LVF_TLS_KEY_FILE`, `LVF_TLS_CA_FILE`,
`LVF_TLS_CLIENT_CERT_FILE`, `LVF_TLS_CLIENT_KEY_FILE`. Every one of these is
read by real code: the last two by `src/utils.py::outbound_client_cert()`
(above), consumed by federation traffic. LVF's TLS section of
`.env.example` has **zero orphaned variables** — the client-cert pair is
real and load-bearing for LVF. `.env.example:263-266`'s comment spells out
exactly which traffic they serve: *"child->parent sync push, parent->FG
push, recursion calls."* This is the template GCS's `.env.example` copied
(`gcs-service/.env.example:267-269`, near-identical variable names and
phrasing, "Client credentials for outbound mTLS to peer FEs (Logging
Service, DR peers)") — but the GCS has no federation traffic, and (per
`core_integration_audit.md`, bucket C.4) never wired the variables to its
actual outbound consumers (`LoggingClient`, `DiscrepancyReporting`). The
orphaning is a copy-without-adaptation artifact, not an independent
oversight.

## 2. Side-by-side table

| Security concern | GCS | MCS | LVF |
|---|---|---|---|
| Listener TLS via core (`make_server_ssl_context`) | **Absent** — raw `uvicorn.run(ssl_certfile=..., ssl_keyfile=...)`, `gcs-service/main.py:70-71` | **Absent** — identical pattern, `mcs-service/main.py:43-44` | **Absent** — identical pattern, `lvf-service/main.py:50-51`, mirrored in `gunicorn.conf.py:57-58` |
| Cipher/TLS-version enforcement (§2.8.1 PFS, TLS-1.2 floor) | **Absent** — no `ssl_version`/`ssl_ciphers` kwarg anywhere; relies on uvicorn/Python `ssl` defaults | **Absent** — same | **Absent** — same, in both `main.py` and `gunicorn.conf.py` |
| mTLS peer cert **required** at handshake | **Absent** — `ssl_cert_reqs=ssl.CERT_OPTIONAL`, `gcs-service/main.py:78` | **Absent** — `ssl_cert_reqs=ssl.CERT_OPTIONAL`, `mcs-service/main.py:60` | **Absent today** — `CERT_OPTIONAL` in both `main.py:63` and `gunicorn.conf.py:71`; **was `CERT_REQUIRED` prior to `d22c312` (2026-06-22)**, reverted after discovering the gunicorn+UvicornWorker enforcement bug |
| Application-layer peer auth (`ProxyClientCertMiddleware`) | **Absent** — confirmed by `core_integration_audit.md`; zero hits in `src/` | **Absent** — zero hits in `src/` | **Absent today** — zero hits in `src/`; comment at `.env.example:244-246` explicitly records prior app-level enforcement was "removed; see git history" |
| Outbound client TLS (Logging Service, DR callbacks) | **Absent** — `LoggingClient`/`DiscrepancyReporting` built with no `http_client=`, `gcs-service/src/core_components.py` | **Absent** — `LoggingClient` built with no `http_client=`, `mcs-service/src/core_components.py:65-68`; no `DiscrepancyReporting` at all (separately deferred) | **Absent for Logging/DR** — `lvf-service/src/core_components.py:77-102`, same gap as GCS/MCS |
| Outbound client TLS (peer/federation traffic) | N/A — GCS has no federation role | N/A — MCS has no federation role | **Wired, hand-rolled** — `src/utils.py:37-59`, consumed in `federation/recursion.py`, `federation/sync.py`; **not** core's `make_client_ssl_context`; one LoST outbound call (`lost/list_services_by_location.py:326`) is *not* covered, an internal inconsistency |
| Client-cert env vars declared vs. read | **Declared, unread** — `GCS_TLS_CLIENT_CERT_FILE`/`_KEY_FILE`, `.env.example:267-269`, zero code references | **Not declared** — MCS has no outbound-mTLS consumer and defines no such variables | **Declared and read** — `LVF_TLS_CLIENT_CERT_FILE`/`_KEY_FILE`, `.env.example:263-273`, consumed by `src/utils.py::outbound_client_cert()` |
| Multi-worker (gunicorn) TLS path | Present — `gunicorn.conf.py` exists (referenced in `README.md`), same raw-uvicorn-style TLS block pattern as `main.py` | **Absent** — no `gunicorn.conf.py` in the repo; single-process only | Present — `gunicorn.conf.py:42-71`, explicitly "mirrors main.py" |
| `securityPosture` (ServiceState field — distinct concern from transport security) | Opted out, cited (`supports_security_posture=False`, `core_components.py`) | Opted out, cited (`supports_security_posture=False`, `mcs-service/src/core_components.py:82`) | Opted out, cited (`supports_security_posture=False`, `lvf-service/src/core_components.py:93`) |

## 3. Convergent pattern

All three services converge on exactly the same non-adoption of
`i3_fe_core.security`: raw `uvicorn.run(ssl_certfile=..., ssl_keyfile=...,
ssl_cert_reqs=ssl.CERT_OPTIONAL)` for the listener, and plain `httpx`
defaults for outbound calls to the Logging Service and DR peers. This is not
three independent decisions converging by coincidence — `main.py`'s TLS
block is close to byte-identical across all three repos (`gcs-service/main.py`,
`mcs-service/main.py`, `lvf-service/main.py` — same variable names modulo
prefix, same comment text verbatim for the `CERT_OPTIONAL` limitation note),
and LVF's git history shows this pattern was settled *before* i3-fe-core
existed as a dependency in any of the three repos, then carried forward
by copy-as-template into MCS and GCS without anyone returning to reconsider
it once `i3_fe_core.security` became available. There is no sibling
currently doing this "right" that GCS regressed from — the convergent
pattern **is** the gap, inherited three times.

The one place LVF diverges (hand-rolled outbound TLS for federation calls)
is solving a problem — LVF-to-LVF peer trust — that doesn't generalize to
either MCS or GCS, and even LVF doesn't extend that pattern to its own
Logging Service / DR traffic, so it isn't evidence of a more mature answer
being available and skipped.

## 4. What a GCS should not copy

- **LVF's `outbound_ssl_context()`/`outbound_client_cert()` pattern
  (`src/utils.py`) is scoped to LVF's federation role** — sync push/pull
  between LVF instances and recursive `findService` forwarding (RFC 5222).
  The GCS has no coverage-region concept, does not recurse, and does not
  redirect on its own initiative (already settled in this repo's spec, §3.1,
  decision 4). Copying this pattern verbatim would build outbound mTLS
  plumbing for a peer relationship the GCS's i3 role does not have. If the
  GCS wires outbound TLS for its actual outbound traffic (Logging Service,
  DR resolution callbacks), the closer prior art is core's own
  `make_client_ssl_context`-based wiring in `app/factory.py:191-216`
  (already read for `core_integration_audit.md`), not LVF's hand-rolled
  helpers.
- **LVF's now-reverted `CERT_REQUIRED`-at-handshake approach** hit a real,
  documented bug (`UvicornWorker`/gunicorn silently downgrading unenforced
  `cert_reqs`) that `i3_fe_core.security.tls`'s own module docstring
  (`i3-fe-core/src/i3_fe_core/security/tls.py:16-29`) names as the reason
  its `gunicorn_mode` parameter and the `security.peer_auth` compensating
  control exist. Re-attempting handshake-level `CERT_REQUIRED` under
  gunicorn+UvicornWorker without using core's `gunicorn_mode=True` path or
  the proxy-terminated-mTLS design would very likely reproduce the exact
  failure LVF already found and gave up on.
- **`supports_security_posture=True`** (used in core's own MCS worked
  example, `ADOPTION.md` line ~239, and matching an MCS call-handling
  duty) does not apply to the GCS — already a settled scope decision in
  this repo (`core_components.py`'s `supports_security_posture=False`
  comment), reconfirmed as the position all three siblings independently
  take (see table row above). Nothing new to flag here; noted only because
  the prompt specifically asked to check duties a sibling's wiring serves
  that a GCS does not have.

## 5. What core itself expects

`i3-fe-core/ADOPTION.md` documents **two consumption patterns** (lines 50-55,
already read for `core_integration_audit.md`): the **framework quick-start**
(`create_app()`, core owns the app) and the **library pattern** (FE keeps its
own app, wires pieces "à la carte"). The library-pattern description names
four things to wire à la carte: *"`SipNotifier`, `DiscrepancyReporting`, the
state notifiers, `NtpClient`"* (`ADOPTION.md:53-55`) — **`security.tls` and
`security.peer_auth` are not in that list.** All three real FEs (GCS, MCS,
LVF) use the library pattern (each builds its own `FastAPI()`/`Starlette()`
app directly — confirmed at `gcs-service/src/server.py:133`,
`mcs-service/src/server.py:297`, `lvf-service/src/server.py:195` — none call
`i3_fe_core.app.factory.create_app`). The **only** places `ADOPTION.md`
actually shows `security.tls` being used are the framework-quick-start worked
examples (`lvf/main.py`, `mcs/main.py` in `ADOPTION.md:92-111` and
`169-245`), both of which call `create_app()` and then separately do:

```python
from i3_fe_core.security.tls import make_server_ssl_context
...
ssl_ctx = make_server_ssl_context(settings.tls)
uvicorn.run(app, host="0.0.0.0", port=8443, ssl=ssl_ctx)
```

Neither worked example, nor any other part of `ADOPTION.md`, shows a
library-pattern consumer wiring `security.tls`/`security.peer_auth` by hand.
This is a real gap in the adoption story, not just an oversight repeated
three times by three FE authors: the one document meant to teach adoption
never demonstrates the wiring for the consumption pattern all three real
services actually use.

Reading the modules directly (`i3-fe-core/src/i3_fe_core/security/tls.py`,
`i3-fe-core/src/i3_fe_core/security/peer_auth.py`, already read in full for
`core_integration_audit.md`) and `app/factory.py:187-216,270-293` (which
*does* show the intended order for the framework path) gives the intended
adoption contract regardless of pattern:

1. Populate `CoreSettings.tls: TLSSettings` — `mode`, `cert_path`,
   `key_path`, `ca_path`, and for the proxy-terminated-mTLS compensating
   control specifically: `proxy_terminated_tls=True`, `client_cert_header`,
   `pca_trust_anchors` (falls back to `ca_path`), `trusted_proxies`.
   `TLSSettings.validate_proxy_terminated_tls` (`config/settings.py:63-76`)
   enforces `client_cert_header` and `pca_trust_anchors`/`ca_path` are both
   set before construction succeeds — a fail-fast check no consuming FE's
   `CoreSettings(...)` call currently exercises, because none of the three
   populate `tls=` at all.
2. Build the server-side context with `make_server_ssl_context(settings.tls,
   gunicorn_mode=...)` and pass its result to uvicorn's `ssl=` kwarg (dev) or
   to gunicorn (production — `app/factory.py:36-45`'s module docstring notes
   explicitly *"pass ssl context to gunicorn, not uvicorn, in this
   deployment"*).
3. When TLS terminates at a proxy (`gunicorn`+`UvicornWorker` is named
   explicitly as the case this exists for), add
   `ProxyClientCertMiddleware` — core's own `create_app()` does this
   conditionally at `app/factory.py:279-293`, gated on
   `settings.tls.mode == TLSMode.MTLS and settings.tls.proxy_terminated_tls`,
   inserted as the **outermost** middleware ("peer auth runs before request
   logging" — `app/factory.py:285`), with `/health` in `exempt_paths`.
4. Build outbound `httpx.AsyncClient` instances (for `LoggingClient` and
   `DiscrepancyReporting`) with `verify=make_client_ssl_context(settings.tls)`
   whenever `settings.tls.mode != TLSMode.OFF` — `app/factory.py:191-203,
   208-216`.

**Core's own conformance suite does not check any of this.**
`i3-fe-core/src/i3_fe_core/conformance/checks.py` was grepped for
`security|peer_auth|mTLS|mtls|ProxyClientCert|tls|TLSMode`; the only hits are
`securityPosture` (the unrelated ServiceState field — §10.18, lines
104-205,343,368) and `TLS/mTLS contexts` appearing once in a table inside
`ADOPTION.md`, not in the conformance module itself.
`assert_core_conformance()` — the function `ADOPTION.md` calls "core's own
statement of what a correctly-wired FE looks like" — probes ElementState/
ServiceState body shape, `/health`, DR resource behavior, IANA registry
exactness, NTP wiring, and timestamp format (per its own docstring at
`conformance/checks.py`, already read in full for `core_integration_audit.md`).
It does not construct a request over TLS, does not check for a `TLSSettings`
value, and does not probe for `ProxyClientCertMiddleware`. This means none of
the three FEs' current security gaps would be caught by running
`assert_core_conformance` against their apps — core's stated minimum bar is
silent on transport security entirely.
