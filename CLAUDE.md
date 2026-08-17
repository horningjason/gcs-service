# CLAUDE.md

Guidance for Claude Code working in this repository.

`README.md` covers how to run the service. This file covers how to *change* it:
the conventions the codebase holds itself to, and the work that is deliberately
unfinished.

## What this is

A Geocode Conversion Service (GCS) implementing NENA i3 `/Geocode` and
`/ReverseGeocode` (NENA-STA-006.3), plus an i3-improved extension
(`/GeocodeEnhanced`, `/ReverseGeocodeEnhanced`) returning ranked, scored
candidates instead of a single best-guess answer.

## Commands

```bash
pip install -r requirements.txt      # Python 3.11+ (developed against 3.14)
python main.py                       # dev server on http://localhost:8000
pytest                               # whole suite, no server or network needed
python tools/field_stats_report.py data/data.gpkg   # GIS discriminative-power report
```

`pytest` needs no arguments — `pyproject.toml` sets `pythonpath = ["."]`.
`TestClient` drives the app in-process. Multi-worker and Docker paths are in
`README.md` §4.

`.env` is required. `GCS_AMBIGUITY_TOLERANCE_M` has **no default** and startup
fails without it — deliberately (see `.env.example` for the reasoning).

## The specification is the authority

`references/GCS_Algorithm_Specification.md` is the design document, and it is
not background reading — it is the thing the code implements. It carries a
numbered decision register (Appendix B — over a hundred entries; check the
register itself for the current count rather than trusting a number here),
and the code cites decisions by number in docstrings and comments:

```python
"""§10.3 / §10.4's lexicographic sequence, as a sort key. ..."""
# decision 59 — the tier ordered on and the tier reported can differ
```

**Keep this discipline.** When changing behaviour the spec settles, cite the
section or decision you are implementing. When you find code and spec
disagreeing, that is a finding to surface, not something to quietly reconcile
in either direction — the spec is a normative document authored for a standards
audience, so editing it to match an implementation shortcut is the wrong repair
unless the decision genuinely deserves revisiting.

Docstrings here are unusually long and argue rationale, including alternatives
considered and rejected. Match that register. A future reader re-proposing a
rejected design because nobody wrote down why it lost is the specific failure
this style exists to prevent.

Working state lives in **Appendix C**: C.2 open questions, C.3 undrafted
sections, C.4 implementation-discovered questions (cited from code and tests —
the numbering is stable and retained even once resolved). As of Session 11
every C.4 question is resolved and C.3 lists nothing undrafted; what remains
open is the §16 gap register (NENA-facing) and the deferred implementation
work below.

## Architecture

```
src/
  server.py          FastAPI app: lifespan, middleware, route mounting
  runtime_state.py   env-var-derived module state (_env_float / _require_float)
  core_components.py i3-fe-core component container, hung on app.state
  api/               HTTP routes, request admission, XML/JSON wire format
  app/               startup/lifecycle: schema loading, GIS load, scorer registration
  engine/            shared element model, geometry, scoring
  geocode/           forward: candidate identification, position derivation
  reverse/           reverse: origin admission, nearest-feature search, civic derivation
  gis/               GeoPackage loading, record model, field-stats measurement
```

Two structural points worth knowing before editing:

**i3-fe-core is consumed as a library, not a framework.** The GCS keeps its own
FastAPI app and wires core components in at startup rather than handing routes
to core's `create_app()`. It is pinned to a GitHub tag in `requirements.txt`
(currently `v0.4.0`) — bump the tag and re-pin deliberately, checking
`ADOPTION.md` in that repo for interface changes, rather than floating the pin.

**Scoring functions are injected, never defaulted.** §6.5 and §10.6 settle the
*shape* of forward and reverse scoring and withhold the formulas (Appendix C
item (d), proprietary tuning). `src/engine/scoring_registry.py` is the seam;
`candidates.py` and `search.py` take a `score` callable with no fallback. With
nothing registered, conversions return **454**, not 468 — 468 asserts a search
happened and found nothing, and no search happened. Do not add a default
formula there; that would be authoring the part of the spec left open.

## Endpoints

Conversion, under `/Gcs/v1`: `Geocode`, `ReverseGeocode`, and — gated on
`GCS_ENABLE_ENHANCED` (default `true`) — `GeocodeEnhanced`,
`ReverseGeocodeEnhanced`. When disabled the enhanced pair is neither mounted
nor advertised, and the strict paths are byte-for-byte identical either way.

Operational: `/health` (liveness, stays 200 during GIS reload), `/ready` (503
during reload), `/ElementState`, `/ServiceState`, `/metrics`, `/Gcs/Versions`
(note: one path segment *above* `/Gcs/v1`, per the normative YAML's own
`servers` override — spec Appendix C.4 Q1), and `/dr`.

## Tests

They all live in `tests/conformance/` — run `pytest` for the current count
rather than trusting a number written here, which rots by design as decisions
land. `tests/regression/` and
`tests/roundtrip/` exist but are empty. `tests/requests/` holds six sample
PIDF-LO bodies built against real addresses in `data/data.gpkg` (Bismarck, ND)
for manual curl testing — each file's comment explains what it demonstrates.

Test names are full sentences describing the behaviour
(`test_a_record_with_no_street_name_is_not_disqualified`), and docstrings
explain *why the rule exists*, not what the assertion does. Follow suit.

## Deferred work — not oversights

None of the three packages this section used to describe as intentionally
empty stubs (`src/discrepancy/`, `src/notify/`, `src/logging/`) still are.
Each is now real, and each carries a docstring explaining what it does and
which decision unblocked it; read it before touching one.

`src/logging/` is no longer a stub. `src/logging/log_events.py` defines
`GcsQueryLogEvent`/`GcsResponseLogEvent` (decision 104's own proposal — i3
§4.12.3.7 registers no GCS-specific LogEvent type), and `src/logging/logger.py`
emits them via the already-wired `LoggingClient` (`runtime_state.logging_client`).
Wired at every return path of both `/Geocode` and `/ReverseGeocode`
(`src/api/geocode.py`, `src/api/reverse_geocode.py`), not just the success
path — mirroring mcs-service's one-call-site-covers-every-return discipline,
since i3 §4.5's payload-logging MUST covers the malformed and no-result cases
too, not only 200. The query event fires BEFORE Stage 0 (request admission)
runs, not after it succeeds: a malformed or unadmittable body is still "the
input object" §4.5 requires logging, and is the request most worth a
forensic record of — the module docstring in `log_events.py` explains why
this, and the single combined `query_adapter` payload field, differ from
lvf-service's split `query_adapter`/`malformed_query` fields.
`GcsResponseLogEvent.response_status` carries the actual HTTP status
(200/307/454/468) on every response, mandatorily — unlike lvf-service's
LoST-status-string field, which is populated only on error — because
decision 104 calls out responseStatus as the thing that must preserve cases
a combined event couldn't represent. Mirrors mcs-service's `emit_nowait()`
mechanism rather than lvf-service's background-event-loop shim: every GCS
call site is inside an `async def` handler, so the shim's reason for
existing (some LVF call sites run outside a running loop) doesn't apply.

`src/discrepancy/` is no longer a stub. Core's responding web service was
already mounted (canonically at `/dr`, decision 98); the filing side now
exists too, mirroring `lvf-service/src/discrepancy/`. Decision 99 settles
what the GCS files about — structural provisioning defects only, never
attribution content — and `src/discrepancy/discrepancy_report.py`'s
`GISProblem` enum covers exactly the three tokens GCS detection paths
produce: `GeneralProvisioning` (GIS load/reload failure,
`src/app/lifecycle.py`), `OmittedField` (`DataQualityFlag.NGUID_MISSING`),
and `BadGeometry` (`DataQualityFlag.NO_GEOMETRY` and
`DataQualityFlag.MULTIPART_SEGMENT`). Filing happens at the call sites that
consume a `GisRecord` — `src/geocode/candidates.py` and
`src/reverse/search.py` — never inside `GisRecord.from_record()` itself,
which only records what it observed (`src/engine/models.py`). Silent no-op
until `GCS_DR_ENDPOINT` is configured; see `.env.example`.

`src/notify/` is no longer a stub either. `src/notify/sip_notifier.py`'s
`SipWireAdapter` is ported from `lvf-service/src/notify/sip_notifier.py` (the
maintained, tested implementation there — 18 unit tests, 4 commits — rather
than `mcs-service`'s untested copy, which has sat untouched since its initial
port). It binds a real UDP+TCP listener via the `sipmessage` library and
publishes ElementState/ServiceState NOTIFYs, closing the i3 §4.5 conformance
gap: ElementState and ServiceState were previously reachable only over HTTP
(`/ElementState`, `/ServiceState`), never over SIP. Started from
`src/app/lifecycle.py`'s `maybe_start_sip()` — leader-gated exactly like the
GIS watcher thread, since under `GCS_WORKERS > 1` every worker binding the
same port is a startup crash, not graceful degradation — and called from
`src/server.py`'s `_lifespan()` rather than nested inside
`lifespan_startup()`, so a missing/unavailable GeoPackage (which returns
early there rather than raising) never suppresses SIP. Fire-and-forget via
`asyncio.ensure_future()`, mirroring lvf-service; mcs-service instead starts
unconditionally and awaits it directly, which is right for MCS's
single-process-only deployment but not for the GCS's gunicorn multi-worker
one. `core_components.py`'s `sip_notifier` field stays `None` regardless —
the adapter reference lives on `lifecycle.py`'s own module state (mirroring
`_schema`/`_worker` there), because `lifespan_startup()`/`_shutdown()` are
called without the `app` object to hang it off; lvf-service's identically
named field is equally never populated, for the same underlying reason (its
reference lives on `app.state` directly instead).

One deliberate deferral within the port itself, not an oversight: `SipNotifier`'s
`validate_target_uri` hook is left unset, at parity with both lvf-service and
mcs-service. It is core's Contact-URI allowlist guarding against NOTIFY
redirection/amplification; leaving it unset means only `authorize_subscriber`
(the `GCS_SIP_ALLOWED_SUBSCRIBERS` check) stands between an accepted SUBSCRIBE
and the NOTIFY target it names — worth a follow-up decision, not a silent gap.

`logging_client` is wired (`runtime_state.logging_client`, passed into
`SipWireAdapter.__init__`'s `SipNotifier(...)` construction, same as every
other GCS core component), so SIP SUBSCRIBE traffic emits a `SubscribeLogEvent`
(§4.12.3) for every processed SUBSCRIBE — core owns the emission logic; the
GCS only supplies the client.

Also unwired: load shedding. Settled in shape by decision 100 (§3.9.5: 429 +
Retry-After as a transport-layer response outside i3's closed conversion
status set, the same reading that licenses the existing 413) but deliberately
unimplemented; no configuration variables are reserved for it — they arrive
with the implementation that reads them.

## Tuning constants that are strawmen, not answers

Several numeric constants are explicitly unjustified-by-data and flagged in
Appendix C item (d). Do not treat them as settled, and do not tune them to make
a specific test pass:

- `_BASE_WEIGHTS` (`src/engine/scoring.py`) — base editorial field weights
- `_STREET_QUALIFY_MIN_EDIT_SIM` = 0.5 (decision 71)
- `GCS_MIN_MATCH_SCORE`, `GCS_REVERSE_SEARCH_RADIUS_M`,
  `GCS_RCL_OFFSET_M`, `GCS_RCL_ENDPOINT_MARGIN_M` — `[PROPOSAL]` defaults

`GCS_GEOCODED_PLACEMENT_PENALTY` = 0.9 was on that list and is off it as of
decision 83: a settled editorial default, not a strawman. It cannot change an
answer (§10.3's ordering is lexicographic and spatial fit is not a term in it)
and cannot be swept (STA-006.3 records that a placement was geocoded, never the
error magnitude), so the env binding is its tuning mechanism. Do not re-open it
looking for a sweep.

By contrast, `_MIN_POPULATION = 30` in `src/gis/field_stats.py` is a
first-principles sample-size floor (decision 68), not a data-tuned value, and
the tier ceilings (100/90/80/75/50 in `models.py`) are fixed by the
specification so two implementations cannot disagree about what a confidence
value means — neither is a knob.

## Configuration

`.env.example` is the canonical variable reference: every variable the service
reads, its default, and whether it is `[REQUIRED]` or a `[PROPOSAL]` value not
yet tuned. Spec §3.8 carries prefix-level orientation only and points here.
Keep the two in sync when adding a variable — and add it to
`src/runtime_state.py` using the existing `_env_float` / `_require_float`
helpers rather than reading `os.environ` at the point of use.
