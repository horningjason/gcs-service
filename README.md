# GCS Service

A Geocode Conversion Service (GCS) implementing the i3 `/Geocode` and
`/ReverseGeocode` functions (NENA i3, NENA-STA-006.3), plus an i3-improved
extension (`/GeocodeEnhanced`, `/ReverseGeocodeEnhanced`) that returns a
ranked, scored candidate list instead of a single best-guess answer.

The algorithm design lives in `references/GCS_Algorithm_Specification.md`.
This file is about running the thing.

## 1. Prerequisites

- Python 3.11+ (developed against 3.14)
- The GIS data this service converts against: a GeoPackage with
  `SiteStructureAddressPoint` and `RoadCenterLine` layers, placed at
  `data/data.gpkg`. It is **not** in version control — `.gitignore` excludes
  `data/*.gpkg` because real address data does not belong in git — so a fresh
  checkout has only `data/.gitkeep` and you supply your own export.

## 2. Install

```bash
pip install -r requirements.txt
```

## 3. Configure

Copy the template and edit as needed:

```bash
cp .env.example .env
```

A working `.env` for local development against the bundled sample data
needs at minimum:

```
GCS_GPKG_PATH=data/data.gpkg
GCS_AMBIGUITY_TOLERANCE_M=150.0
```

`GCS_AMBIGUITY_TOLERANCE_M` has no built-in default — startup fails without
it (see `.env.example` for why). Everything else has a workable default for
local use; `.env.example` documents every variable the service reads,
including which ones are `[PROPOSAL]` defaults not yet tuned against real
data and which are `[REQUIRED]`.

## 4. Start the service

**Single process (development):**

```bash
python main.py
```

Listens on `http://localhost:8000`. `GCS_TLS_MODE=disabled` (the default) is
plaintext HTTP — fine for local work, not for a real deployment.

**Multi-worker (gunicorn, Linux/Docker only):**

```bash
python prewarm.py && gunicorn -c gunicorn.conf.py src.server:app
```

`prewarm.py` builds the GIS JSON cache once before gunicorn forks workers,
so they all hit a warm cache instead of racing to cold-parse the GeoPackage
concurrently. Worker count is `GCS_WORKERS` in `.env`.

**Docker:**

```bash
docker compose up --build
```

Mounts `./data` into the container and reads `.env` for configuration; see
`docker-compose.yml` for the healthcheck and resource limits it sets.

## 5. Check it's up

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

`/health` is liveness — it stays `200` while GIS data is (re)loading.
`/ready` reports `503` during a reload, so a load balancer holds traffic off
a worker that can't convert yet. A healthy `/ready` response looks like:

```json
{"ready":true,"reloading":false,"ssap":78237,"rcl":19703}
```

If `ssap`/`rcl` are both `0`, the GeoPackage at `GCS_GPKG_PATH` wasn't
found or didn't load — check the startup log.

## 6. Try it

Six sample PIDF-LO request bodies are in `tests/requests/`, built against
addresses that are actually present in `data/data.gpkg` (Bismarck, ND) so
they exercise a real match, not a synthetic one. Each file's own comment
explains what it's for and what to expect.

All four conversion endpoints sit under `/Gcs/v1` and take a PIDF-LO document
as the POST body (raw XML or a JSON string — both are accepted; see
`decode_body` in `src/api/admission.py`).

The two interfaces answer in different formats, deliberately. A **strict**
`200` is `application/xml` — the normative YAML's own declared content type,
with the matched PIDF-LO carried in a CDATA section inside the declared
wrapper element (spec decision 116, `src/api/wire/strict_xml.py`):

```xml
<GeodeticData><pidfLoGeo><![CDATA[ … ]]></pidfLoGeo></GeodeticData>
```

An **enhanced** `200` is `application/json`, since the enhanced schema is the
GCS's own additive definition and is not bound to the normative YAML's
declared content type. Every non-200 response on both interfaces is JSON —
454 and 468 each carry a `reason` field.

**Forward geocode, enhanced (ranked, scored candidates — start here):**

```bash
curl -X POST http://localhost:8000/Gcs/v1/GeocodeEnhanced -H "Content-Type: application/xml" --data-binary @tests/requests/geocode_civic_address.xml
```

Returns `200` with a `candidates` array, each carrying `matchScore`,
`locationType`, `confidence`, and a per-field `matchScoreBreakdown` — the
i3-improved shape that the strict interface deliberately does not expose.

**Forward geocode, strict i3:**

```bash
curl -i -X POST http://localhost:8000/Gcs/v1/Geocode -H "Content-Type: application/xml" --data-binary @tests/requests/geocode_civic_address.xml
```

This one is worth trying with `-i` so you see the status code: `200`, with a
single `gml:Point` for 802 12th Avenue NW, Mandan — a real address point, so
it answers at rung 1 (`ADDRESS_POINT`).

**Forward geocode, interpolated (rung 2):**

```bash
curl -X POST http://localhost:8000/Gcs/v1/GeocodeEnhanced -H "Content-Type: application/xml" --data-binary @tests/requests/geocode_interpolated_point.xml
```

A different street this time (Del Rio Drive), queried at house number 2800,
which is deliberately absent from the address-point layer while falling
inside a road segment's range with the right parity. The top candidate comes
back `INTERPOLATED_POINT` on Del Rio Drive — the comparative ladder (spec
decision 70) lets the exact road match outrank the wrong-street address
points that share the house number, instead of rung 1 shadowing the road
search by merely being non-empty.

House number is a hard identity gate on address-point (SSAP) candidates
(spec decision 69) — a query supplying `Add_Number` only ever reaches
scoring against records whose house number matches exactly, rather than
being fuzzy-compared like a street name. Earlier, before that gate existed,
the general-purpose edit-distance similarity scored close-but-different
house numbers ("415" vs "416") as falsely similar, which could pull
wrong-address candidates in from across town and spread the surviving set
past `GCS_AMBIGUITY_TOLERANCE_M` — spec §6.3's ambiguity rule, which returns
468 rather than silently averaging two different places into one wrong
answer. That failure mode is gone for the identity field; the base editorial
scoring weights for every other field (`src/engine/scoring.py`'s
`_BASE_WEIGHTS`) are still an admitted guess pending real tuning — see
`references/GCS_Algorithm_Specification.md` Appendix C item (d) — so a
street-name-only or heavily fuzzy query can still land in ambiguity.
`GeocodeEnhanced` above never has this problem regardless: it returns the
full ranked list instead of collapsing it to one answer, so ambiguity is
information rather than a failure (spec decision 27).

**A genuine non-match**, for contrast — no ambiguity, just nothing found:

```bash
curl -i -X POST http://localhost:8000/Gcs/v1/Geocode -H "Content-Type: application/xml" --data-binary @tests/requests/geocode_no_match.xml
```

`468` with the invariant body `{"reason": "No result was derivable for the
query."}`. That string is the same on every 468 regardless of which §6.4 path
produced it — spec decision 114 deliberately does not distinguish them on the
wire. The diagnostic detail (here, "No candidate was derivable for the query
address.") is logged server-side instead; see `no_result_response()` in
`src/api/status.py` for why.

**Reverse geocode** (coordinate → address), strict:

```bash
curl -X POST http://localhost:8000/Gcs/v1/ReverseGeocode -H "Content-Type: application/xml" --data-binary @tests/requests/reverse_point.xml
```

`200` with the civic address for the point queried — this one reliably
matches, since reverse search has no §6.3-style ambiguity gate.

**Reverse geocode, enhanced, with a non-Point shape:**

```bash
curl -X POST http://localhost:8000/Gcs/v1/ReverseGeocodeEnhanced -H "Content-Type: application/xml" --data-binary @tests/requests/reverse_circle.xml
```

Same location as `reverse_point.xml`, but as a 100 m `gs:Circle` — shows
§10.6's extent-damping term bringing the score down for a vaguer query, and
that the search radius (`GCS_REVERSE_SEARCH_RADIUS_M`) governs how far the
search looks regardless of the circle's own radius.

**Reverse geocode with nothing nearby:**

```bash
curl -i -X POST http://localhost:8000/Gcs/v1/ReverseGeocode -H "Content-Type: application/xml" --data-binary @tests/requests/reverse_no_match.xml
```

`(0, 0)` is open water — `468`, carrying the same invariant
`{"reason": "No result was derivable for the query."}` the forward non-match
does. The distinguishing detail ("No feature fell within
GCS_REVERSE_SEARCH_RADIUS_M of the origin.") goes to the log, not the wire.

## 7. Run the automated test suite

```bash
pytest
```

Run `pytest` for the current count (it rots by design as decisions land). It
collects two directories:

- **`tests/conformance/`** — admission, scoring, position derivation, reverse
  search, response assembly, and full HTTP round trips. No running server or
  network access required; `TestClient` drives the app in-process, against a
  trivial two-record in-memory GIS fixture and stub scorers.
- **`tests/security/`** — live TLS/mTLS handshake verification (spec §3.9.3,
  decision 107). These spawn real uvicorn and gunicorn subprocesses against a
  throwaway PKI generated per session and assert on the *observed* handshake
  outcome rather than on `SSLContext` attributes. The gunicorn cases are
  skipped on Windows (gunicorn is POSIX-only), matching `gunicorn.conf.py`'s
  own documented constraint.

`tests/roundtrip/` is a reserved directory, still empty.

### Regression suite (real data, real scoring, not pytest)

`tests/regression/` is a separate golden-file suite that runs in-process
against the real `data/data.gpkg` and the real (if still data-unproven)
scoring functions in `src/engine/scoring.py` — no ASGI app, no TestClient, no
port, calling the same plain functions the route handlers wrap directly
(mirroring lvf-service's own regression runner). The opposite isolation
choice from `tests/conformance/`, on purpose, to catch what happens once the
algorithm runs against tens of thousands of real records instead of two
synthetic ones.

```bash
# Run all regression tests
python -m tests.regression.runner

# Run a single test by ID
python -m tests.regression.runner --test FWD-GAP-HNO-001
```

Exit code is `0` if everything passes, `1` on any failure, error, or missing
golden file. A fresh checkout has no fixtures or golden files committed
(`tests/regression/inputs/` and `tests/regression/golden/` are gitignored —
they're discovered from and scored against `data/data.gpkg`, which is itself
not committed); the first `runner` invocation builds and seeds both
automatically.

**Seeding golden files (run once — do not re-run casually):**

```bash
# (Re)discover fixtures from data.gpkg into tests/regression/inputs/
python -m tests.regression.build_inputs

# Seed all tests that don't yet have a golden file
python -m tests.regression.seed

# Force-overwrite one test's golden file after a reviewed behavior change
python -m tests.regression.seed --force FWD-GAP-HNO-001

# Force-reset the entire baseline (only after a deliberate, reviewed change)
python -m tests.regression.seed --force
```

See `tests/regression/README.md` for the full philosophy, the harness
architecture, and — worth reading before adding a fixture — a section on
several cases whose current shape only makes sense once you've seen how real
data defied the naive assumption a first draft made about it.

## 8. Field-stats report (before trusting the scoring weights)

```bash
python tools/field_stats_report.py data/data.gpkg
```

Prints, per civic element, how discriminative that field actually is in the
currently loaded data (`1 - max_frequency` of its most common value) — the
direct check on whether e.g. `Country` and `A1` really are near-constant in
this deployment before `src/engine/scoring.py` weights them accordingly.
Standalone: doesn't start the service or touch `.env`.

`tools/weight_ranking_sweep.py` is the companion probe, asking the narrower
question the report above does not: given two candidates that both already
clear `GCS_MIN_MATCH_SCORE`, do `_BASE_WEIGHTS`' *ratios* rank them correctly
relative to each other? Its own docstring explains the scope (six fields, not
seven) and why donor availability for `A1` and `Country` is itself a finding
in a single-state export.

## Repository layout

```
main.py              single-process launcher (builds the TLS context)
gunicorn.conf.py     multi-worker launcher config; prewarm.py warms the cache
src/
  server.py          FastAPI app: lifespan, middleware, route mounting
  runtime_state.py   env-var-derived module state and process-wide handles
  core_components.py i3-fe-core component container, hung on app.state
  api/               HTTP routes, request admission; api/wire/ serialisation
  app/               startup/lifecycle (schema, GIS load, scorer registration,
                     SIP start) and the TLS-aware gunicorn worker
  engine/            shared element model, geometry, scoring
  geocode/           forward direction: candidate identification, position derivation
  reverse/           reverse direction: nearest-feature search, civic derivation
  gis/               GeoPackage loading, record model, field-stats measurement
  discrepancy/       discrepancy-report filing (the responding side is core's)
  logging/           i3 LogEvent types and their emission
  notify/            SIP ElementState/ServiceState publication
  observability/     Prometheus metric definitions
tests/
  conformance/ the pytest suite (stub scorers, in-memory GIS)
  security/    pytest live TLS/mTLS handshake tests (gunicorn cases POSIX-only)
  regression/  golden-file suite against real data — not pytest, see §7
  requests/    sample PIDF-LO request bodies for manual/curl testing
  roundtrip/   reserved, empty
tools/
  field_stats_report.py     standalone GIS data-quality/weighting report
  weight_ranking_sweep.py   standalone _BASE_WEIGHTS ratio-ordering probe
schemas/     XML validation schemas — see schemas/README.md
reports/     point-in-time audit write-ups (dated snapshots, not live docs)
references/
  GCS_Algorithm_Specification.md   the algorithm design document
```
