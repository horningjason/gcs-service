# `references/` provenance

Where each vendored source came from, so a future session can re-verify it.

| File | Source | Retrieved |
|---|---|---|
| `GCS_Algorithm_Specification.md` | Authored in-repo (Jason Horning, ENP); markdown-native as of this date, converted from the prior docx-based version history (which Appendix D retains for continuity) | 2026-07-31 |
| `i3-geocode-conversion.yaml` | `https://raw.githubusercontent.com/NENA911/Geocode-Conversion-Service/main/i3-geocode-conversion.yaml` | 2026-07-30 |
| `i3-geocode-conversion-enhanced.yaml` | Authored in-repo; an additive diff against the vendored `i3-geocode-conversion.yaml` adding `/GeocodeEnhanced` and `/ReverseGeocodeEnhanced`. Modifies no line of the normative file. DRAFT — not yet logged to spec Appendix B nor cited from §3.9.2/§12.2 | 2026-08-02 |
| `rfc3863.txt` | `https://www.rfc-editor.org/rfc/rfc3863.txt` | 2026-07-30 |
| `rfc4119.txt` | `https://www.rfc-editor.org/rfc/rfc4119.txt` | 2026-07-30 |
| `rfc4745.txt` | `https://www.rfc-editor.org/rfc/rfc4745.txt` | 2026-07-30 |
| `rfc5491.txt` | `https://www.rfc-editor.org/rfc/rfc5491.txt` | 2026-07-30 |
| `rfc7459.txt` | `https://www.rfc-editor.org/rfc/rfc7459.txt` | 2026-07-30 |
| `rfc5139.txt`, `rfc 6848.txt` | Pre-existing in repo | — |
| NENA `.pdf` files | Pre-existing in repo | — |

## The normative YAML

`i3-geocode-conversion.yaml` is vendored byte-for-byte from the `main` branch,
version `1.0` per its own `info.version`. Per i3 §2.8 it is **normative and
controls over the §4.5 text** wherever the two disagree, so it needs to be in
this repo rather than only cited.

Reading it directly confirms every Session 3 finding recorded in spec §2.1:

- one server base, `/Gcs/v1`
- `GeodeticData { pidfLoGeo }` and `CivicAddress { pidfLoAddress }` — the
  published text's `GeodecticData` and `PIDFLOAddress` are not the schema's
  spellings
- referral travels in the `Location` header of a **307**; there is no
  `gcsReferralUri` property on either response object
- `/ReverseGeocode` omits **454** entirely, while `/Geocode` lists it
- the request body is `application/json` with `schema: type: string`, and the
  200 response is `application/xml` referencing a JSON-shaped object — the
  incoherence recorded as a §16 row

Two further details were found on this read. Both are now recorded in the
specification as Appendix C.4 Q1 and Q2 respectively:

1. **`/Versions` carries its own `servers` override** —
   `https://api.example.com/Gcs`, i.e. one path segment *above* the `/Gcs/v1`
   base the two operations sit on. So `Versions` is not at
   `/Gcs/v1/Versions`. See spec Appendix C.4 Q1; the service mounts it that way.
2. **The `/Versions` 200 body `$ref`s an external file**,
   `i3-common.yaml#/components/schemas/VersionsArray`, which is not present in
   the NENA911 repository. The reference is unresolvable as published. This
   does not block implementation — `i3_fe_core.web_service.versions` already
   implements the §4 body shape — but it is a defect in the normative
   definition of the same kind as the content-type incoherence already logged.
   See spec Appendix C.4 Q2.
