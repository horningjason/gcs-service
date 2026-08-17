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
  `SiteStructureAddressPoint` and `RoadCenterLine` layers. A sample is
  already checked in at `data/data.gpkg`.

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

All four conversion endpoints sit under `/Gcs/v1`, take a PIDF-LO document
as the POST body (raw XML or a JSON string — both are accepted; see
`decode_body` in `src/api/admission.py`), and return JSON.

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
single `gml:Point` for 2801 Del Rio Drive — a real address point, so it
answers at rung 1 (`ADDRESS_POINT`).

**Forward geocode, interpolated (rung 2):**

```bash
curl -X POST http://localhost:8000/Gcs/v1/GeocodeEnhanced -H "Content-Type: application/xml" --data-binary @tests/requests/geocode_interpolated_point.xml
```

Same street, but house number 2800, which is deliberately absent from the
address-point layer while falling inside a road segment's range with the
right parity. The top candidate comes back `INTERPOLATED_POINT` on Del Rio
Drive — the comparative ladder (spec decision 70) lets the exact road match
outrank the wrong-street address points that share the house number, instead
of rung 1 shadowing the road search by merely being non-empty.

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

`468` with reason `"No candidate was derivable for the query address."`

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

`(0, 0)` is open water — `468` with reason `"No feature fell within
GCS_REVERSE_SEARCH_RADIUS_M of the origin."`

## 7. Run the automated test suite

```bash
pytest
```

472 tests as of this writing (run `pytest` for the current count), covering
admission, scoring, position derivation, reverse search, response assembly,
and full HTTP round trips —
no running server or network access required; `TestClient` drives the app
in-process. Every test currently lives in `tests/conformance/`;
`tests/regression/` and `tests/roundtrip/` are reserved directories, still
empty.

## 8. Field-stats report (before trusting the scoring weights)

```bash
python tools/field_stats_report.py data/data.gpkg
```

Prints, per civic element, how discriminative that field actually is in the
currently loaded data (`1 - max_frequency` of its most common value) — the
direct check on whether e.g. `Country` and `A1` really are near-constant in
this deployment before `src/engine/scoring.py` weights them accordingly.
Standalone: doesn't start the service or touch `.env`.

## Repository layout

```
src/
  api/         HTTP routes, request admission, XML/JSON wire format
  app/         startup/lifecycle (schema loading, GIS load, scorer registration)
  engine/      shared element model + scoring (src/engine/scoring.py)
  geocode/     forward direction: candidate identification, position derivation
  reverse/     reverse direction: nearest-feature search, civic derivation
  gis/         GeoPackage loading, record model, field-stats measurement
tests/
  conformance/ the test suite
  requests/    sample PIDF-LO request bodies for manual/curl testing
  regression/, roundtrip/   reserved, empty
tools/
  field_stats_report.py     standalone GIS data-quality/weighting report
references/
  GCS_Algorithm_Specification.md   the algorithm design document
```
