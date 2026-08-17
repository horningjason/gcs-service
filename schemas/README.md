# `schemas/` — XML validation schemas

`gcs-pidflo.xsd` is the entry point. It declares nothing itself; it imports
every namespace a GCS PIDF-LO can legitimately contain so that one compiled
lxml schema validates the whole document. `src/app/lifecycle.py` compiles it
once at startup.

GCS spec §4.1 requires a schema-invalid request to return **454** on both
operations, which is only enforceable if the validator actually descends into
the civic and geodetic payloads. RFC 3863 and RFC 4119 both declare their
extension points as `xs:any processContents="lax"`, and a *lax* validator
silently accepts any foreign-namespace element it has no declaration for.
Importing all of them together is what closes that hole. This is the same
device LVF uses with `lost1.xsd`.

## Provenance

| File | Namespace | Source | Status |
|---|---|---|---|
| `pidf.xsd` | `urn:ietf:params:xml:ns:pidf` | RFC 3863 §4.4 | RFC text, localised import |
| `geopriv10.xsd` | `…:pidf:geopriv10` | RFC 4119 §2.2.5 | RFC text, localised imports |
| `basicPolicy.xsd` | `…:pidf:geopriv10:basicPolicy` | RFC 4119 §2.2.5 | RFC text, localised import |
| `civicAddr.xsd` | `…:pidf:geopriv10:civicAddr` | RFC 5139 | copied from `lvf-service/schemas/`, unmodified |
| `civicAddr-ext.xsd` | `…:pidf:geopriv10:civicAddr:ext` | RFC 6848 | copied from `lvf-service/schemas/`, unmodified |
| `nenaCivicAddr.xsd` | `urn:nena:xml:ns:pidf:nenaCivicAddr` | NENA legacy `cdx1:` (STPS only) | copied from `lvf-service/schemas/`, unmodified |
| `nenaCivicAddr2.xsd` | `urn:nena:xml:ns:pidf:nenaCivicAddr2` | NENA-STA-004.2-2024 | copied from `lvf-service/schemas/`, unmodified |
| `confidence.xsd` | `urn:ietf:params:xml:ns:geopriv:conf` | RFC 7459 §7 | RFC text, verbatim |
| `xml.xsd` | `http://www.w3.org/XML/1998/namespace` | W3C | fetched from `w3.org/2001/xml.xsd`, unmodified |
| `gml-geoshape/*.xsd` | `http://www.opengis.net/gml`, `http://www.opengis.net/pidflo/1.0` | OGC 06-142r1 BP, GML 3.1.1 PIDF-LO Geometry Shape profile **v0.1.0** | fetched from `schemas.opengis.net`, unmodified |

`gml-geoshape/` was fetched from
`https://schemas.opengis.net/gml/3.1.1/profiles/geoshape/0.1.0/` and is the
schema RFC 5491 §4 and §5 normatively reference. Its seven files chain by
`xs:include`: `geometryPrimitives` → `geometryBasic2d` → `geometryBasic0d1d` →
`measures` → `gmlBase` → `basicTypes`, with `GML-pidf-lo-shape.xsd` importing
`geometryPrimitives`. Importing those two files therefore covers both
namespaces. All schemaLocations inside the profile are already relative
filenames, so no localisation was needed.

## Localisation

Three files carry the only edits made to RFC-sourced text, all of them to
`schemaLocation` attributes. Nothing else was changed — no declarations were
added, removed, or relaxed.

1. `pidf.xsd`, `geopriv10.xsd`, `basicPolicy.xsd` — the `xml.xsd` import
   pointed at `http://www.w3.org/2001/xml.xsd`. The GCS XML parser runs with
   `no_network=True`, so it points at the local copy instead.
2. `geopriv10.xsd` — RFC 4119 declares
   `<xs:import namespace="…:basicPolicy"/>` with **no** `schemaLocation` at
   all. One was added so the schema resolves offline.

Each edit is annotated in place in the file that carries it.

## What is deliberately absent

- **`lost1.xsd` / `lostExt-Ids.xsd`** — LVF has these; the GCS is not a LoST
  server (§2.2), so the LoST envelope has no place here. Consequence worth
  knowing: LVF sources `callId` / `incidentTrackingId` for its i3 LogEvent
  prologue from `lostExt-Ids`, and a GCS request carries no equivalent. Those
  prologue fields are CONDITIONAL, so omitting them is conformant.
- **RFC 4745 `common-policy.xsd`** — not required. RFC 4119's `basicPolicy`
  schema defines `locPolicyType` self-contained and does not import
  common-policy.
- **The i3 §4.5 wrapper objects** (`GeodeticData`, `CivicAddress`) — those are
  JSON, defined by `references/i3-geocode-conversion.yaml`, not XSD. The
  PIDF-LO travels inside them as a string.
