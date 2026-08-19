**NG9-1-1 GeoCode Service (GCS) Algorithm Specification**

*Developed as a companion to and extension of NENA-STA-010.3f-2021 §4.5*

Draft Specification | July 2026

*Status: Draft — In Development. Converted to Markdown at the close of the Version 7 (docx) revision; from this point forward, history is tracked via git commit log rather than a bumped version number in this file. Appendix D retains the full docx-era version history for continuity.*

*Author: Jason Horning, ENP*

**Governing Standards:**

NENA-STA-010.3f-2021 | NENA-STA-004.2-2024 | NENA-STA-006.3-2026 | RFC 4119 | RFC 5139 | RFC 5491 | RFC 7459

# Table of Contents

- 1. Purpose and Scope
    - 1.1 Governing Standards
    - 1.2 Document Philosophy and Approach
    - 1.3 Document Conventions and Context Tracking
    - 1.4 PIDF-LO Namespace Prefixes
- 2. Service Overview
    - 2.1 i3 Normative Baseline (STA-010.3f-2021 §4.5)
    - 2.2 Two Interfaces
    - 2.3 One Engine
    - 2.4 Algorithm Overview — Geocode
    - 2.5 Algorithm Overview — ReverseGeocode
- 3. Pre-Algorithm Context
    - 3.1 Scope
    - 3.2 GIS Data Quality
    - 3.3 Provisioned Layers and the Precision Ladder
    - 3.4 GIS Record Temporal Filtering
    - 3.5 GIS Data Reload and Unavailability Window
    - 3.6 Service Scope, Discovery, and Referral
    - 3.7 Coordinate Reference Systems and Three-Dimensional Operation
    - 3.8 Environment Variables
    - 3.9 HTTP Interface
    - 3.10 Civic Element Model and PIDF-LO Mapping
- 4. Geocode — Stage 0: Request Admission
    - 4.1 Body, Content-Type, and Schema Validation
    - 4.2 Multiple Location Handling
    - 4.3 Profile Check
- 5. Geocode — Structural Conformance
- 6. Geocode — Candidate Identification
    - 6.1 Layer Search Order
    - 6.2 Candidate Set
    - 6.3 Ambiguity and Tie-Breaking
    - 6.4 No-Candidate Conditions
    - 6.5 Scoring
- 7. Geocode — Position Derivation
    - 7.1 SSAP-Derived Position
    - 7.2 RCL-Derived Position — Address Range Interpolation
    - 7.3 Setback and the Access Point Problem
    - 7.4 Uncertainty and Confidence
    - 7.5 Three-Dimensional Spaces
- 8. Geocode — Response Assembly
    - 8.1 The i3 Interface — GeodeticData
    - 8.2 The i3-improved Interface
    - 8.3 PIDF-LO Construction
    - 8.4 Status Code Selection
- 9. ReverseGeocode — Stage 0: Request Admission
- 10. ReverseGeocode — Nearest Feature Search
    - 10.1 Search Structure — One Pass
    - 10.2 Search Radius
    - 10.3 Candidate Ordering — Containment, Tier, Distance
    - 10.4 Tie-Breaking
    - 10.5 Distance Metric
    - 10.6 Spatial-Fit Scoring
- 11. ReverseGeocode — Civic Derivation
    - 11.1 SSAP-Derived Civic Address
    - 11.2 RCL-Derived Civic Address
    - 11.3 Administrative Element Sourcing
    - 11.4 Element Population and Omission
- 12. ReverseGeocode — Response Assembly
    - 12.1 The i3 Interface — CivicAddress
    - 12.2 The i3-improved Interface
    - 12.3 Status Code Selection
- 13. Referral
- 14. Cross-Element and Round-Trip Consistency
    - 14.1 Round-Trip Consistency
- 15. Complete Algorithm Pseudologic
    - 15.1 Geocode
    - 15.2 ReverseGeocode
- 16. Known Gaps and Recommended Actions
- Appendix A — i3 Infrastructure and Protocol Requirements
    - A.1 Versions Entry Point
    - A.2 NTP Client Interface
    - A.3 Logging (LogEvent Interface)
    - A.4 ElementState Event Notification
    - A.5 ServiceState Event Notification
    - A.6 Discrepancy Reporting
    - A.7 SI/SDPI Data Feed Interface
    - A.8 Security
- Appendix B — Decision Register
- Appendix C — Open Tasks and Questions
    - C.1 Source Documents Not Yet Read
    - C.2 Open Questions
    - C.3 Sections Not Yet Drafted
    - C.4 Implementation-Discovered Questions
- Appendix D — Document Change Log

# 1. Purpose and Scope

This document is the author’s internal working record for building the NG9-1-1 GeoCode Service (GCS): the conversion of a civic address expressed as a PIDF-LO into a geodetic representation of the same location (Geocode), and the inverse conversion of a geodetic representation into a civic address (ReverseGeocode). It captures this implementation’s own algorithm — the matching, scoring, and derivation logic that is this GCS’s own competitive design and is not intended for standardization. Geocoders are not meant to converge on identical internal logic. What must be interoperable is the interface: the request/response contract, status codes, and any uncertainty or confidence vocabulary a consumer can rely on regardless of which GCS answered. The exportable product of this document — the part intended to be shared with NENA — is §16’s gap register together with the specific interface extensions proposed to fill those gaps. The algorithm sections, the decision register, and the open questions exist to carry context between working sessions and are not offered as a reference implementation for the industry.

The need for this document is rooted in a structural gap. NENA-STA-010.3f-2021 §4.5 is approximately two pages. It defines two HTTP endpoints, a request body (“a PIDF-LO as a string”), two response objects, and five status codes. It defines no candidate identification logic, no interpolation method, no uncertainty representation, no tie-breaking rule for the “nearest point algorithm” it explicitly invokes, no referral discovery mechanism, and no relationship to LVF validation results. Two conformant GCS implementations can therefore return materially different coordinates for the same address, and neither is non-conformant.

This document covers US civic addresses only (CLDXF-US profile). Canadian addresses (CLDXF-CA) are explicitly out of scope for this version.

***✔ Settled (Session 1):** US civic addresses only (CLDXF-US). CLDXF-CA out of scope for v1.*

## 1.1 Governing Standards

| **Standard**         | **Version**   | **Role in This Algorithm**                                                                                                                                                                                                                                                                                                                         |
|------------------------|------------------------|------------------------|
| NENA-STA-010.3f-2021 | October 2021  | i3 Standard — normative source for the GCS web service definition (§4.5), resource names, request/response objects, status codes, provisioning model, ElementState/ServiceState obligations, and the IANA registries in §10. Per §2.8, the OpenAPI YAML in NENA’s GitHub repository — not the text — is the normative definition of the interface. |
| NENA-STA-004.2-2024  | February 2024 | Authoritative source for CLDXF-US element definitions, PIDF-LO names, namespaces, and business rules — governs the civic side of both conversions.                                                                                                                                                                                                 |
| NENA-STA-006.3-2026  | March 2026    | Authoritative source for GIS layer definitions, standardized field names, address range and parity fields, 3D support on SiteStructureAddressPoint (§4.2.1), and the Placement Method registry (§6.1). STA-006.3 Table 4-1 lists RoadCenterLine and SiteStructureAddressPoint as Required for the GCS.                                             |
| NENA-INF-027.1-2018  | August 2018   | Reference source for civic element evaluation logic and hierarchy principles. Where INF-027 conflicts with STA-004.2-2024 or STA-006.3-2026, the newer standard takes precedence.                                                                                                        |
| NENA-REQ-003         | —             | Requirements for 3D Location Data for E9-1-1 and NG9-1-1. Implemented by STA-006.3’s SSAP layer; the basis for HAE as the vertical datum.                                                                                                                                                                                                          |
| RFC 4119             | December 2005 | PIDF-LO — the presence document format carrying location in both directions. Mandates and within ; constrains values to an IANA registry.                                                                                                                                                                                                          |
| RFC 5139             | February 2008 | Base PIDF-LO civic address schema (ca: namespace).                                                                                                                                                                                                                                                                                                 |
| RFC 5491             | March 2009    | GEOPRIV PIDF-LO usage clarification. Constrains geodetic representation, defines the GML 3.1.1 subset and geoshapes, and gives guidance for conveying exactly one location.                                                                                                                                                                        |
| RFC 7459             | February 2015 | Defines the normative confidence element and its schema for PIDF-LO location estimates, updating RFC 4119 and RFC 5491. RFC 5491 supplies only shape vocabulary and a one-line confidence recommendation; RFC 7459 is the actual confidence mechanism. Source for the confidence value carried on Geocode/ReverseGeocode responses (§7.4).         |
| RFC 6848             | January 2013  | PIDF-LO civic address extensions (cae: namespace).                                                                                                                                                                                                                                                                                                 |
| NENA-STA-040.2-2024  | October 2024  | NG-SEC — transport security and credential requirements for the GCS web service interface.                                                                                                                                                                                                                                                         |

## 1.2 Document Philosophy and Approach

The content of this document falls along a spectrum relative to existing standards. At one end are sections that clarify how existing normative requirements apply in practice. In the middle are sections that formalize guidance the standards imply but do not fully specify. At the far end are genuinely novel contributions where no current standard provides guidance; these are explicitly marked as recommended best practice.

Throughout this document, where content departs from or extends the standards, it does so to enable consistent real-world implementation, not to supersede or contradict them. In all cases the normative basis for each decision is cited, and where the document fills gaps it says so explicitly. §16 serves as the formal record of gaps identified during development. This document is not itself a NENA standard; it represents the considered judgment of its author on what a correct and consistent GCS implementation requires.

This document draws a line between two audiences. The algorithm sections — candidate identification, scoring, position derivation, and the pseudologic in §15 — are this implementation’s own working method: proprietary design that is deliberately not offered as a model for other GCS implementations to converge on. Only §16, the gap register, and the specific interface extensions proposed to fill those gaps are intended to be shared outward, specifically with NENA. The decision register (Appendix B) and open questions (Appendix C) are cross-session working memory, not a deliverable.

### 1.2.1 Strict Reading — Algorithm Gaps We Fill, Wire Vocabulary We Do Not Invent

This document draws a line forced by how materially incomplete the GCS interface is relative to i3’s LoST-based interfaces.

Where i3 is silent on behavior — interpolation, nearest-feature search, tie-breaking, candidate identification — this document specifies it, because something must happen and the standard does not say what. Where i3 supplies a fixed set of status codes, response fields, or messages, that set is closed. This document does not mint status codes, does not add fields to i3-defined response objects, and does not invent messages. Where the i3 vocabulary is insufficient to express a condition honestly, the implementation carries the deficiency, the departure is stated in the text, and a gap row is recorded in §16 — not merely as an internal audit trail, but as the seed of what gets proposed to NENA.

A corollary applies in both directions. Just as this document does not add vocabulary i3 lacks, it does not add restrictions i3 lacks. i3 §4.5 imposes no structural precondition on a Geocode request; requiring one would be an invention of the same kind, in the opposite direction. See §5.

A second corollary governs embedded documents. The RFC 4119 constraint on PIDF-LO content travels with the format, not with the interface. Any PIDF-LO this service emits — on either interface (§2.2) — is bound by RFC 4119 and RFC 5491 regardless of what envelope carries it. Extensions this document defines ride in the i3-improved interface’s own envelope; the PIDF-LO records embedded within it remain conformant.

***✔ Settled (Session 1):** Strict reading adopted. Status codes limited to the five in §4.5. No new fields on GeodeticData or CivicAddress. No invented messages. Deficiencies carried and documented rather than patched.*

## 1.3 Document Conventions and Context Tracking

This document is the source of truth for GCS behavior. The implementation follows the document; where the two disagree, the document is correct and the code is a defect — unless the disagreement reveals that the document is wrong, in which case the document is amended and the version incremented.

| **Convention**                         | **Purpose**                                                                                                                                                                                                                                           |
|------------------------------------|------------------------------------|
| Versioned filename                     | The version number in the filename is the only version identifier. Every substantive change increments it. Superseded versions are retained so a past implementation decision can be traced to the text that governed it.                             |
| Normative citation on every decision   | Each rule states the standard and section it derives from. A rule with no citation is by definition a novel contribution and must carry a best-practice callout instead.                                                                              |
| ⚠️ Best-practice callout               | Marks a section where no current standard provides guidance and this document fills the gap. Every callout should have a corresponding row in §16.                                                                                                    |
| ✔ Settled callout                      | Records a decision reached in a working session, so that later readers (and later sessions) do not silently reopen it. Mirrored in Appendix B.                                                                                                        |
| §16 Known Gaps and Recommended Actions | The formal gap register. Rows are added as gaps are discovered and are never silently deleted; a resolved gap is marked resolved with the resolving standard and version. This table is the primary artifact intended for NENA standards development. |
| Appendix B — Decision Register         | Cross-session decision log. Because a materially higher share of GCS rules are novel contributions with no citation to anchor them, the reasoning has nowhere natural to live inline. The register carries it.                                        |
| Appendix C — Open Tasks and Questions  | Working state carried between sessions. Emptied as items are resolved.                                                                                                                                                                                |
| DRAFTING NOTE                          | Temporary. Marks a skeletal section or unresolved question. Zero drafting notes is the definition of a complete draft.                                                                                                                                |

## 1.4 PIDF-LO Namespace Prefixes

| **Prefix** | **Namespace URI**                                   | **Source**                                                                               |
|------------------------|------------------------|------------------------|
| ca:        | urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr     | RFC 5139 — base civic address elements                                                   |
| cae:       | urn:ietf:params:xml:ns:pidf:geopriv10:civicAddr:ext | RFC 6848 — IETF extensions                                                               |
| cdx1:      | urn:nena:xml:ns:pidf:nenaCivicAddr                  | NENA — original CLDXF extensions (STPS only)                                             |
| cdx2:      | urn:nena:xml:ns:pidf:nenaCivicAddr2                 | NENA-STA-004.2 — NENA-defined extensions                                                 |
| gml:       | http://www.opengis.net/gml                          | OGC GML 3.1.1 subset per RFC 5491 §4                                                     |
| gs:        | http://www.opengis.net/pidflo/1.0                   | GeoShape extensions (Circle, Ellipse, ArcBand, Sphere, Ellipsoid, Prism) per RFC 5491 §5 |
| gp:        | urn:ietf:params:xml:ns:pidf:geopriv10               | GEOPRIV wrapper per RFC 4119 — location-info, usage-rules                                |
| pidf:      | urn:ietf:params:xml:ns:pidf                         | PIDF presence document root per RFC 3863 / RFC 4119                                      |

***✔ Confirmed (Session 11):** The gs: prefix and URI are verified against the OGC GML-pidf-lo-shape schema itself (`schemas/gml-geoshape/GML-pidf-lo-shape.xsd`, `targetNamespace="http://www.opengis.net/pidflo/1.0"`), which is the schema RFC 5491 §5 normatively references. The table above stands as written.*

# 2. Service Overview

## 2.1 i3 Normative Baseline (STA-010.3f-2021 §4.5)

The following is the complete set of normative requirements i3 §4.5 places on the GCS. It is reproduced here in full because it is short enough to reproduce in full, which is itself the observation that motivates this document.

| **Aspect**         | **Geocode**                                                                                                                            | **ReverseGeocode**                                                                         |
|------------------------|------------------------|------------------------|
| HTTP method        | POST                                                                                                                                   | POST                                                                                       |
| Resource name      | …/Geocode                                                                                                                              | …/ReverseGeocode                                                                           |
| Request body       | PIDF-LO as a string, containing a civic address                                                                                        | PIDF-LO as a string, containing a geodetic representation                                  |
| Response object    | GeodecticData \[sic — see §16\]                                                                                                        | CivicAddress                                                                               |
| Success field      | pidfLoGeo — PIDF-LO resulting from conversion. MUST be present if conversion succeeds.                                                 | PIDFLOAddress — PIDF-LO resulting from conversion. MUST be present if conversion succeeds. |
| Failure field      | gcsReferralUri — URI of another GCS. MUST be present if conversion does not succeed.                                                   | gcsReferralUri — URI of another GCS. MUST be present if conversion does not succeed.       |
| Multiple locations | If the request PIDF-LO contains more than one location, the return MUST contain only one result: the conversion of the first location. | Not stated. See §16.                                                                       |

Status codes, identical for both functions. Per §1.2.1 this set is closed.

| **Code** | **i3 meaning**              | **This algorithm — condition**                                                                                                                                                                                                                               |
|------------------------|------------------------|------------------------|
| 200      | Data Successfully Converted | A single result was derived. See §8.3 / §12.2.                                                                                                                                                                                                               |
| 307      | Temporary Redirect          | Not emitted. See §13.                                                                                                                                                                                                                                        |
| 454      | Unspecified Error           | Schema validation failure — malformed body, invalid PIDF-LO, wrong structure — on both operations, with a human-readable reason in the response body as this implementation’s convention. Also the residual bucket for internal errors. See §4.1, §8.4, §16. |
| 468      | No Address Found            | No result derivable from provisioned data, including the ambiguous case beyond tolerance (§6.3). Emitted without gcsReferralUri when none is provisioned — a documented departure from §4.5’s MUST. See §13 and §16.                                         |
| 469      | Unknown MCS/GCS             | Not emitted. The condition this code describes is undefined for a request carrying no service identifier. See §16.                                                                                                                                           |

Additional i3 §4.5 requirements outside the request/response contract:

| **Requirement**      | **i3 text**                                                                                                                                                                                                         | **Disposition** |
|------------------------|------------------------|------------------------|
| Provisioning         | Provisioned using the same mechanism as the ECRF and LVF: layer replication from the master SI. The layers include all of the layers to create a PIDF-LO.                                                           | §3.3            |
| Error acknowledgment | Any conversion can introduce errors; conversion is complicated by inherent uncertainty of the measurements and the “nearest” point algorithm employed. Reverse geocoding is typically less accurate than geocoding. | §7.4, §10       |
| Logging              | The service logs the invocation of the function, as well as the input and output objects.                                                                                                                           | Appendix A.3    |
| ElementState         | Each FE in the GCS MUST implement the server-side of the ElementState event notification package.                                                                                                                   | Appendix A.4    |
| ServiceState         | The set of GCS FEs within an ESInet MUST implement the server-side of the ServiceState event notification package.                                                                                                  | Appendix A.5    |

***✔ Settled (Session 3):** The normative OpenAPI YAML (NENA911/Geocode-Conversion-Service, i3-geocode-conversion.yaml, v1.0) has been read in full. Per §2.8 it supersedes the text above wherever they disagree, and they disagree materially: the schema object is GeodeticData (the text’s “GeodecticData” is a typo), the ReverseGeocode success field is pidfLoAddress (not PIDFLOAddress), the referral URI travels in the Location header of a 307 response rather than as a gcsReferralUri body field (GeodeticData has no such property), and /ReverseGeocode omits status 454 entirely. The request body is declared application/json with schema type string; the 200 response is declared application/xml yet references a JSON-shaped object wrapper — an incoherence that cannot be implemented as written. See §3.9.1 for the adopted readings and §16 for the defect rows.*

***⚠ CORRECTED (Session 14, decision 116) — the last sentence above does not hold.*** *"An incoherence that cannot be implemented as written" did not account for OpenAPI 3.0's own default XML serialization: absent an `xml:` annotation (the YAML declares none), an object's properties become child elements named after the property, so `application/xml` and `{pidfLoGeo: string}` both hold at once — `<GeodeticData><pidfLoGeo><![CDATA[...]]></pidfLoGeo></GeodeticData>`. This implementation now emits real `application/xml` for the strict interface's 200 response accordingly. Every other finding in the paragraph above stands unchanged. See §3.9.1's own correction note (same decision) and Appendix B decision 116 for the full reasoning; retained here per §16's no-silent-deletion rule rather than rewritten in place.*

## 2.2 Two Interfaces

***⚠️ Recommended Best Practice — No Current Standards Guidance:** A geocoder is conventionally a scored, ranked, multi-candidate service: a query for **“101 Main St”** legitimately surfaces **“101 Mayne St”** as a lower-scored candidate, and two equally perfect matches must both be disclosed rather than silently reduced to one. i3 §4.5 has no vocabulary for any of this. GeodeticData carries one PIDF-LO and no score; i3 defines no scoring concept anywhere; and the match-quality vocabulary i3 does define — **\<**matchType**\>** and **\<**degradedMatch**\>**, §3.4.10, with tokens in the §10.31 Match Type registry — is bound to LoST extension points that the GCS, not being a LoST server, cannot reach. The two-interface arrangement below is a recommended best practice developed to satisfy both the standard and the requirement.*

This document specifies two interfaces over one engine (§2.3):

| **Interface**             | **Contract**                                                                                                                                                    | **Purpose**                                                                                                                                  |
|------------------------|------------------------|------------------------|
| The i3 interface          | Strictly §4.5. POST …/Geocode and …/ReverseGeocode. GeodeticData / CivicAddress exactly as defined. Five status codes. No added fields.                         | Conformance. Interoperability with any i3 client.                                                                                            |
| The i3-improved interface | Non-i3. Ranked scored candidates; match type; tie disclosure; Placement Method passthrough; the full matched PIDF-LO record per candidate, not a bare geometry. | The service a geocoder must actually provide. The gap it patches — and the specific fields it adds to do so — is what gets proposed to NENA. |

***✔ Settled (Session 1):** Two interfaces. The i3 interface is carried faithfully, including its deficiencies — no score floor, no invented fields, no patching. A fuzzy match returns 200 and a coordinate indistinguishable from an exact match, because that is what §4.5 permits it to return. This is deliberate: the two interfaces form a controlled comparison with the i3 contract as the variable, which sharpens exactly what §16’s gap rows and proposed extensions are patching. Merging the two remains available if the standard catches up.*

Prior art confirms the shape is conventional rather than invented. Google’s Geocoding API returns a relevance-ordered results array with a location_type precision classification (ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER, APPROXIMATE), a partial_match flag, and a viewport expressing extent. Each has a counterpart here: the precision ladder (§3.3), i3’s own §10.31 Match Type tokens, i3’s , and RFC 5491 uncertainty — which is a stronger instrument than a bounding box, being a real geometry with confidence.

***✔ Settled (Session 4):** The §10.31 registry has been read in full — Address, RoadCenterline, PoliticalBoundary, MsagCommunity, CoverageRegion, Hybrid, Other. The enhanced interface emits Address for point-tier matches and RoadCenterline for road-tier matches, and carries locationType alongside because the registry cannot express the distinctions this document computes. Mapping and rationale in §12.2; the registry’s coarseness is a §16 row.*

## 2.3 One Engine

***✔ Settled (Session 1):** One engine, two interfaces. The engine always produces a ranked, scored candidate list. The i3 interface takes rank 1 and drops everything §4.5 has no field for. The i3-improved interface returns the list. Consequences: §15 contains one algorithm rather than two; the i3 answer is provably the same answer; and fuzzy matching informs both interfaces or neither.*

## 2.4 Algorithm Overview — Geocode

| **Stage** | **Name**                 | **Success**                                                        | **Failure** |
|------------------|------------------|------------------|------------------|
| 0         | Request Admission        | Well-formed PIDF-LO carrying at least one civic location — proceed | TBD — 454?  |
| 1         | Candidate Identification | Ranked candidate list produced (§6)                                | 468 (§6.4)  |
| 2         | Position Derivation      | Position and uncertainty derived from rank-1 candidate (§7)        | TBD         |
| 3         | Response Assembly        | 200 — GeodeticData (i3) / candidate list (i3-improved)             | —           |

*Gate 1 is deliberately absent — see §5. Stage numbering was reviewed when §15 was written (decision 84) and is retained as-is: §15.1's four stages match this table exactly.*

## 2.5 Algorithm Overview — ReverseGeocode

| **Stage** | **Name**               | **Success**                                                                                                          | **Failure** |
|------------------|------------------|------------------|------------------|
| 0         | Request Admission      | Well-formed PIDF-LO carrying at least one geodetic location — proceed                                                | TBD         |
| 1         | Nearest Feature Search | Candidate list produced. 3D pass first if the input carries Z; 2D fallback pass if the 3D pass finds nothing (§3.7). | 468         |
| 2         | Civic Derivation       | Civic address composed from the matched feature (§11)                                                                | TBD         |
| 3         | Response Assembly      | 200 — CivicAddress (i3) / candidate list (i3-improved)                                                               | —           |

# 3. Pre-Algorithm Context

## 3.1 Scope

***✔ Settled (Session 1):** The GCS is scoped to the ESInet in which it operates and the GIS data provisioned to it. It has no coverage region concept, does not recurse, and does not redirect on its own initiative. It serves geocodes and reverse geocodes from the data in front of it. Discovery of the correct GCS is an external concern (§3.6). There is no referral-only deployment mode.*

*There is exactly one deployment mode — the converting service described above — and no local policy constrains the i3 contract: the enhanced resources are additive siblings (§3.9.2), the strict paths are byte-for-byte conformant either way, and §3.5/§3.9.4 describe operational states of that one mode rather than modes of their own. The former drafting note asking to enumerate deployment modes is discharged by there being nothing to enumerate.*

## 3.2 GIS Data Quality

The GCS is only as good as the data it receives. Conversion results are authoritative only to the extent that the underlying GIS data is accurate, complete, and consistently maintained. The GCS performs no independent assessment of GIS data quality — it converts against what it has been provisioned with, and returns results accordingly.

The GCS’s dependency on geometric quality is direct: the output is the coordinate. Address point placement convention, centerline positional accuracy, and address range completeness and monotonicity all propagate directly into the answer.

STA-006.3 does define Placement Method ID on SSAP with its own registry (§6.1, **“Site/Structure Address Point Placement Method”**), so the placement convention is discoverable per record rather than assumed — this is the closest available analog to Google’s ROOFTOP vs GEOMETRIC_CENTER distinction, and it is data passed through rather than vocabulary invented. The registry values (read in Session 4) are Structure, Site, Parcel, Geocoding, ExteriorAccess, InteriorAccess, InteriorCentroid, PropertyAccess, Unknown; Geocoding as a placement method is circular for reverse operation (§10.6), and the interior-aware values arrived with the 2026 revision. STA-006.3 Table 8-1 still carries open placement questions.

***✔ Settled (Session 11, decision 103 — resolves Appendix C.4 Q19):** Placement Method arrives in provisioned data as the registry token TEXT, not the integer FK into STA-006.3 Table 15-8 the standard describes — no join is performed and the field is typed as text; code expecting an integer would fail against this SI. The provisioned spellings do not all match the registry (`Property Access` with a space, against the registry token `PropertyAccess`), so every comparison against a registry token — §10.6's Geocoding damping in particular — is made after trim-and-casefold normalisation. The token itself is passed through to the enhanced interface as the SI spelled it, uncorrected. Worth noting for §10.5's disclosure argument: the largest single value in the provisioned data is Parcel (42% of records) — a parcel centroid rather than a structure point, exactly the placement variance §10.5 surfaces rather than corrects.*

***✔ Settled (Session 11, decision 103 — adopts Appendix C.4 R4):** Ingestion strips surrounding whitespace from every text value and normalises empty or whitespace-only text to null; interior whitespace is preserved untouched. This is forced by fixed-width export padding in the provisioned data — 32 of 49 sampled SSAP text columns are whitespace-only in over 90% of rows, and padding appears on non-blank values too — and without it exact comparison ("Bismarck" versus a stored "Bismarck ") and §11.4's omit-rather-than-emit-empty rule are both unimplementable. Stripping is safe because no CLDXF-US element's meaning depends on leading or trailing whitespace.*

## 3.3 Provisioned Layers and the Precision Ladder

STA-006.3 Table 4-1 lists RoadCenterLine and SiteStructureAddressPoint as Required for the GCS. No other layer is listed as Required, Strongly Recommended, or Recommended for the GCS.

***✔ Settled (Session 1):** The search is a three-rung precision ladder, not a two-layer fallback. The third rung is a different kind of answer, not merely a less precise one: it is the whole segment, and the honest return is a representative position with uncertainty spanning the segment extent.*

| **Rung** | **Source**                                                | **Result**                                                       | **Nearest Google analog** |
|------------------|------------------|------------------|------------------|
| 1        | SiteStructureAddressPoint                                 | The address point position, Z included where present             | ROOFTOP                   |
| 2        | RoadCenterLine, HNO interpolated within the address range | Interpolated position along the segment                          | RANGE_INTERPOLATED        |
| 3        | RoadCenterLine, no HNO to interpolate                     | Representative position, uncertainty spanning the segment extent | GEOMETRIC_CENTER          |

| **Layer**                        | **STA-006.3 status for GCS**       | **Use**                                                                                                            |
|------------------------|------------------------|------------------------|
| SiteStructureAddressPoint (SSAP) | Required                           | Rung 1. The only layer STA-006.3 §4.2.1 declares 3D-capable.                                                       |
| RoadCenterLine (RCL)             | Required                           | Rungs 2 and 3. Not declared 3D-capable; Z present only if the provisioned geometry happens to carry it. See §16.   |
| SiteStructureAddressPolygon      | Not listed (Recommended, MDS only) | Not used in v1. See §16 — polygon extent would give a defensible uncertainty region where a bare point gives none. |
| 3D space / volume layer          | Does not exist                     | Future work. See §7.5 and §16.                                                                                     |
| Service boundary layers          | Not listed for GCS                 | Not used. No coverage concept (§3.6).                                                                              |

*A stated consequence, so consumers are not surprised: because only SSAP is 3D-capable — and decision 85 settles every RCL-derived answer as 2D regardless of what the export's geometry type carries — the rung that matched determines whether the answer can be three-dimensional at all. The same address can geocode 3D via SSAP and 2D via RCL. Not a defect; an honest report of what the data model declares (§16).*

## 3.4 GIS Record Temporal Filtering

STA-006.3 provisions Effective and Expire DATETIME fields on both required layers. Where either is populated, a record is not unconditionally in force — it has a window, and a query arriving outside that window should not see it.

***✔ Settled (Session 10):** Temporal filtering is evaluated at request time, not at load time. Each candidate record is tested against the instant the request is being processed, not against the instant the GIS data was last loaded — so a record's active/inactive status can change between two requests served from the same loaded dataset, with no reload required. Effective is honoured inclusively (a record becomes active at the start of its Effective instant) and Expire exclusively (a record stops being active at its Expire instant, not after it). A record carrying neither field is always active — the norm in the provisioned data, where both are null throughout, not the exception the mechanism is built for. An unparseable date is treated as absent rather than as grounds to drop the record: a formatting defect in the source data should not silently remove an address from service.*

i3 §4.5 provides no client-driven temporal qualifier for the GCS — no **\<asOf\>** analog, no revalidateAfter analog. This is not a gap the GCS needs to fill: STA-006.3's Effective/Expire pair already gives the service everything it needs to decide a record's status at the moment of the request, without a client asking for a particular instant. There is nothing for a client-supplied qualifier to add, and nothing in i3 §4.5 to honour even if a client sent one.

## 3.5 GIS Data Reload and Unavailability Window

The GCS holds its GIS data in memory and hot-reloads it on change (§3.3), via `i3_fe_core.gis.DatasetCache`. Reload can succeed, fail, or be in flight when a request arrives; each of those three states has an observable consequence.

***✔ Settled (Session 10):** Stale data is preferred over no data. A hot-reload that fails leaves the previously-loaded dataset in place rather than clearing it — the service keeps answering from the last good load rather than going dark over a single bad read of the GeoPackage. This is reported: a failed reload drives ElementState to SERVICE_DISRUPTION so the condition is externally visible, but the service continues converting against the stale-but-valid data underneath that signal. This is a different state from never having loaded at all — where no dataset has ever been loaded (missing GeoPackage, or the very first load failing), there is nothing to fall back to, and both ElementState (SERVICE_DISRUPTION) and ServiceState (DOWN) report accordingly.*

***✔ Settled (Session 10):** A request in flight during a reload is never served a half-swapped dataset. Requests read the live SSAP/RCL lists by reference; a reload does not mutate those lists in place, it rebinds the module-level reference to newly-built ones once the new data is fully assembled. A request already holding the old reference when a reload completes finishes against a fully consistent snapshot of whichever generation it started with — never a mix of old and new records.*

***✔ Settled (Session 10):** Readiness and health are reported separately, and only readiness gates traffic. `/health` (or its ElementState/ServiceState equivalents) reflects element-level condition and can report degraded while still serving. `/ready`, by contrast, is the traffic-gating signal (§3.9.4): it reports 503 specifically while a reload is in flight, or before any GIS data has ever loaded — narrower conditions than "disrupted" — so a load balancer holds traffic off a worker that cannot convert *right now*, without conflating that with the broader, and often survivable, "operating on stale data" state above.*

## 3.6 Service Scope, Discovery, and Referral

i3 §4.5 requires gcsReferralUri to be present whenever conversion does not succeed, and lists 307 Temporary Redirect among the status codes. It specifies no mechanism by which a GCS determines that it is not authoritative for a location, and no mechanism by which it discovers the URI of a GCS that is. There is no LoST-Sync analog for the GCS and no GCS forest guide.

***✔ Settled (Session 1):** Discovery is not the GCS’s problem. A client locates the authoritative ESInet using LoST against the ECRF, and thereby learns enough about that ESInet to reach its services. The GCS answers from its own provisioned data. Consequently the GCS has no coverage region, derives none, exchanges none, and cannot distinguish **“no such address”** from **“not my jurisdiction”** — it does not need to.*

### 3.6.1 The Specified Discovery Path

i3 §4.15 requires every service connected to the ESInet to be listed in the Service/Agency Locator, with the URI of its record stored in the ECRF that serves it. §4.15.2 defines the lookup: a LoST findService query with a `<service>` element of “urn:emergency:service:serviceagencylocator.” followed by a Service Name, plus the location. The ECRF returns a LoST mapping containing the S/AL record URI; an HTTPS GET on that URI returns the record.

The vocabulary needed already exists. The §10.11 serviceNames registry contains “GCS — GeoCode Service”. The §10.30 Interface Names registry contains both “Geocode” and “ReverseGeocode”.

The path fails at the last inch. The §4.15.4 Service/Agency Locator Record schema has no field carrying the GCS interface URI. It has mdsFeatureIntefaceUri and mdsImageIntefaceUri, loggingServiceUriArray, eidoInterfaceUri, dscRptSvc, svcStateUri, emergencySipInterfaceUri and adminLineUri — the Mapping Data Service received two dedicated fields; the GeoCode Service received none. The record a client correctly arrives at cannot tell it where the GCS is. The MSAG Conversion Service is missing for the same reason.

***⚠️ Recommended Best Practice — No Current Standards Guidance:** In the absence of an S/AL field, this document proposes gcsInterfaceUri — a single OPTIONAL field carrying the GCS base URI, to which a client appends /Geocode or /ReverseGeocode. One field rather than two, because §4.5 already expresses the resource names as **“…/Geocode”** relative to a common base, and because i3 §10 treats the GCS as a single interface for permissions purposes. This deliberately follows the existing per-interface field pattern rather than proposing a more general mechanism. See §16.*

*(The mds\* misspellings — mdsFeatureIntefaceUri / mdsImageIntefaceUri, missing the “r” that eidoInterfaceUri and emergencySipInterfaceUri spell correctly — are cited in the §16 row, whose recommended action includes correcting them. The former drafting note asking for that citation is discharged.)*

### 3.6.2 gcsReferralUri

***✔ Settled (Session 1):** gcsReferralUri is populated from static configuration (GCS_REFERRAL_URI). The GCS performs no coverage test and makes no judgment about who is authoritative; it emits the configured URI on conversion failure because §4.5 requires a referral to be present. Where none is configured, 468 is returned without gcsReferralUri — a knowing departure from the MUST, recorded in §16. The deficit is data, not vocabulary: the GCS lacks a URI to publish, not a way to express one, so inventing a message would not help.*

A consequence follows directly from having no coverage concept and is stated here rather than discovered later: the referral is emitted on every conversion failure, including for addresses that exist nowhere. The client is sent onward for a lost cause. This is what §4.5 literally specifies, and is part of why the gap row is justified rather than pedantic.

***✔ Settled (Session 3):** The carrier is the Location header of a 307 response, per the normative YAML — which defines no gcsReferralUri property on GeodeticData at all, contradicting the §4.5 text’s MUST. Where GCS_REFERRAL_URI is configured, failure emits 307 with the configured URI in Location; where it is not, 468 is returned as before. The text/YAML contradiction is a §16 row; the YAML controls per §2.8.*

### 3.6.3 Why the Referral Is Not a Failover Mechanism

An alternative reading — that gcsReferralUri points to a peer GCS within the same ESInet when the primary is impaired — is not supported by i3’s usage elsewhere. Every other 307 in i3 is a scope referral: the IS-ADR (§4.11) returns 307 to instruct a client to direct its query to the resource specified; the Policy Store (§3.3.1.2.1) pairs 307 with “453 Not Available Here, No Referral Available”; the S/AL Search by Name (§4.15.3) returns a ReferralUri to another Search Service and is provisioned with other Search Services’ URIs “much like a Forest Guide.” i3’s idiom for functional element redundancy is client-side multi-instance configuration rather than in-band redirect — the Logging Service is the clearest case, where clients MUST support at least two Logging Services — with health communicated out-of-band via ElementState and ServiceState.

## 3.7 Coordinate Reference Systems and Three-Dimensional Operation

STA-006.3 §4.2.1 states that with version 3 of the GIS Data Model, the SiteStructureAddressPoint layer implements NENA-REQ-003 and now supports 3D, and that the Z value of the geometry corresponds to Altitude, which is the Height Above Ellipsoid. The vertical datum is therefore not a choice this document makes; it is the choice the data model already made.

***✔ Settled (Session 1):** Vertical datum is Height Above Ellipsoid (WGS84), per STA-006.3 §4.2.1 and NENA-REQ-003. CRS is a per-response property determined by the matched feature, not a configuration setting: urn:ogc:def:crs:EPSG::4326 where the matched feature carries no Z, urn:ogc:def:crs:EPSG::4979 where it does.*

### 3.7.1 Geocode — Z Is Carried, Not Computed

***✔ Settled (Session 1):** Geocode returns a Z if and only if the matched GIS feature has one. SSAP: the Z of the address point. RCL: the Z along the line at the position to which the address number interpolates. 3D volume (future): the centroid of the space. No 3D search is performed in the forward direction — Z is carried through, not derived.*

This has a structural consequence worth stating: position derivation is one interpolation along the matched geometry that carries whatever dimensions the vertices have, degenerating to 2D when they carry none. It is not 2D interpolation with a vertical step appended. One algorithm, one code path, dimensionality determined by the data. See §7.2.

### 3.7.2 ReverseGeocode — 3D Search with 2D Fallback

***✔ Settled (Session 1):** Where the input geodetic location carries a Z, the nearest-feature search is performed in three dimensions using the HAE value. If no feature is found within the search constraints in 3D, the candidate geometries are flattened to 2D and the search is repeated. Where the input carries no Z, only the 2D pass runs.*

***✔ Revised (Session 4) — mechanism absorbed, intent preserved.***\* The two-pass structure is withdrawn in favour of a single pass with lexicographic ordering (§10.1). Vertical selectivity is no longer expressed as a 3D pass followed by a 2D fallback but as the leading term of the candidate ordering: candidates whose vertical extent contains the input’s Z rank ahead of those that do not, and horizontal distance orders candidates within a band. This produces the same preference the two passes were written to express, while eliminating a structure in which a candidate could be rejected by the first pass and re-admitted by the second — the same redundancy collapsed for containment in §10.3. Where the input carries no Z the ordering degrades to pure horizontal distance, which is the normal path today. The one capability genuinely surrendered is a separate search radius per pass; under a single pass there is one GCS_REVERSE_SEARCH_RADIUS_M (§10.2).\*

The 2D fallback is not an edge case. STA-006.3 Table 8-1 records, as deferred future work, that “stacked address points will result in topology errors and goes against existing GIS data standards” — stacked points being the only means of representing multiple vertically-separated addresses with the SSAP layer as it stands. The data model simultaneously supports 3D address points and disowns the sole available way to use them for a multi-story structure. Until a 3D space layer exists (§7.5), the 2D pass will be the productive one in most jurisdictions.

### 3.7.3 Minimising Maximum Error

A single principle governs position selection on both axes wherever more than one candidate survives, or where a candidate has extent rather than a position: return the position that minimises the maximum error across the surviving candidates, and size the uncertainty to their extent.

Vertically, this yields the midpoint of a space rather than its floor, and the midpoint of a set of stacked candidates rather than the lowest: naming floor 1 of a twenty-storey structure puts a responder up to sixty metres out, whereas the midpoint bounds the worst case at thirty, and gives sensor-based vertical determination room to converge from either direction. Horizontally, it yields a position between surviving candidates rather than an arbitrary election of one. §6.3 and §7.4 are applications of this principle rather than independent rules.

## 3.8 Environment Variables

***✔ Settled (Session 10):** The canonical reference is `.env.example`, at the repository root — it documents every variable the service reads, its default, and whether it is `[REQUIRED]` (startup fails if unset, no safe default exists) or a `[PROPOSAL]` value (an implementation-chosen starting point, not a spec figure, expected to be retuned against real deployment data per Appendix C item (a)). README.md §3 points there rather than repeating it, and this section does the same: it carries orientation by prefix only, not a restated table that would drift from the code the moment either changed.*

All service-specific configuration uses the `GCS_` prefix. By category: `GCS_GPKG_PATH` / `GCS_SSAP_LAYER` / `GCS_RCL_LAYER` / `GCS_GPKG_POLL_INTERVAL_SECONDS` (GIS data and reload, §3.3, §3.5); `GCS_REFERRAL_URI` (§3.6.2); `GCS_RCL_OFFSET_M` / `GCS_RCL_ENDPOINT_MARGIN_M` / `GCS_MIN_MATCH_SCORE` / `GCS_REVERSE_SEARCH_RADIUS_M` / `GCS_GEOCODED_PLACEMENT_PENALTY` / `GCS_AMBIGUITY_TOLERANCE_M` (conversion tuning, §6.3, §7.2, §7.3, §7.4, §10.2, §10.6 — `GCS_AMBIGUITY_TOLERANCE_M` is the one `[REQUIRED]` tuning constant, deliberately shipped with no default per §6.3's own reasoning); `GCS_SERVER_URI` / `GCS_AGENCY_ID` / `GCS_SERVICE_DOMAIN` / `GCS_NTP_SERVER` / `GCS_LOGGING_SERVICE_URI` (i3-fe-core identity, time, and logging, §A.2, §A.3); `GCS_ENABLE_SIP` / `GCS_SIP_*` (state notification transport, §A.4, §A.5 — read but currently inert, since the SIP wire adapter is not yet implemented); `GCS_ENABLE_DR_SERVICE` / `GCS_DR_*` (Discrepancy Reporting, §A.6); `GCS_TLS_MODE` and the `GCS_TLS_*` credential variables, plus the default-off `GCS_GUNICORN_CERT_OPTIONAL_FALLBACK` break-glass (transport security, §3.9.3, §A.8 — i3 §2.8.1 and §5.4 are enforced as of decision 108; two client-certificate variables were removed as orphaned, decision 107); `GCS_WORKERS` / `GCS_WORKER_TIMEOUT` (process management); `GCS_ENABLE_ENHANCED` (§3.9.2 discovery); `GCS_VERSION_MAJOR` / `GCS_VERSION_MINOR` / `GCS_BUILD_FINGERPRINT` (§A.1 Versions entry point); `GCS_LOG_LEVEL`. No variables are reserved for load shedding: §3.9.5 defers the implementation, and the configuration arrives with the code that reads it (decision 100).

Every core-backed variable (identity, time, logging, SIP, DR, TLS) is reviewed for applicability against the GCS's narrower scope rather than adopted wholesale from `i3-fe-core` or LVF — §3.6.2's referral handling and §3.1's single-deployment-mode posture are two places that review already changed behavior relative to the shared library's default.

## 3.9 HTTP Interface

### 3.9.1 The i3 Interface

***✔ Settled (Session 3):** One web service, per the normative YAML: a single specification with one server base (/Gcs/v1) and one /Versions entry point covering both POST /Geocode and POST /ReverseGeocode. The request body is the PIDF-LO as a string (declared application/json, schema type string). The 200 response objects are GeodeticData { pidfLoGeo: string } and CivicAddress { pidfLoAddress: string }. Referral is 307 with the URI in the Location header (§3.6.2). The YAML’s declared response Content-Type (application/xml wrapping a JSON-shaped object) is incoherent as written; this implementation emits application/json for the wrapper object, carrying the PIDF-LO XML document as the string value — the only reading under which the declared schemas are implementable — and records the defect in §16.*

***⚠ CORRECTED (Session 14, decision 116) — this paragraph's response-Content-Type finding does not hold.*** *Session 3's "incoherent as written" claim did not consider OpenAPI 3.0's own default XML serialization: absent any `xml:` annotation on a schema (and the YAML declares none on GeodeticData or CivicAddress), an object's properties become child elements named after the property — confirmed directly against the OpenAPI 3.0.3 specification and Swagger's own reference documentation. Read that way, `application/xml` and `{pidfLoGeo: string}` are NOT irreconcilable: `<GeodeticData><pidfLoGeo>...</pidfLoGeo></GeodeticData>`, with the embedded PIDF-LO carried as a CDATA section — standard XML for embedding markup-like text verbatim, not an OpenAPI-specific mechanism, and not something the standard needs to mention for it to be available. This implementation now emits real `application/xml` for the strict interface's 200 response, honouring the YAML's declared content type literally rather than substituting `application/json` for it. The request-body finding above (JSON string, or raw XML, both accepted — decision 95) is untouched; only the 200 response encoding is corrected. See decision 116 (Appendix B) for the full reasoning, including the i3 §4.4 (MSAG Conversion Service) precedent checked before adopting this reading, and §16's now-partially-resolved "Normative YAML content types are incoherent" row.*

***✔ Settled (Session 11, decision 95 — resolves Appendix C.4 Q1 and Q14):** Two readings the implementation adopted provisionally are adopted as specification. The `/Versions` entry point lives at `/Gcs/Versions` — one path segment ABOVE the `/Gcs/v1` base, following the normative YAML's own `servers` override literally — and is unversioned by design: a client must reach version discovery before it knows which versions exist. And the request body is accepted in both of the YAML's two readable forms — a JSON string carrying the escaped PIDF-LO, or the raw XML itself — discriminated by the first non-whitespace byte, with Content-Type logged but not enforced; rejecting either form would add a restriction i3 does not impose, enforced against a declaration §16 already records as incoherent. A sender may therefore send either form. The YAML's `/Versions` response `$ref` to `i3-common.yaml` is unresolvable from the published repository; that defect is a §16 row.*

### 3.9.2 The i3-improved Interface

***✔ Settled (Session 3):** The i3-improved interface consists of sibling resources on the same web service: POST /GeocodeEnhanced and POST /ReverseGeocodeEnhanced, alongside the standard paths and discovered through the /Versions vendor parameter — i3’s own sanctioned hook for a service advertising vendor-specific capability. The strict i3 paths remain byte-for-byte conformant to the normative YAML, untouched. The enhanced response carries ranked candidates; each candidate carries the full matched PIDF-LO record (§8.2), the three-field quality model of §7.4 (matchScore with per-field breakdown, locationType, confidence), the ladder rung’s registry match type (§3.3), and — on the reverse resource only — the Placement Method ID where the matched record carries one (decision 92). The embedded PIDF-LO records remain RFC 4119 / RFC 5491 conformant (§1.2.1). Because the enhanced schema is purely additive alongside the v1 YAML, the NENA-facing interface extension proposal can be expressed as a literal diff against the published definition.*

### 3.9.3 Transport Requirements

*Transport is i3's, restated rather than invented: HTTPS per i3 §2.8.1 — HTTP/1.1 MUST, HTTP/2 SHOULD, TLS 1.2 MUST, TLS 1.3 MAY, TLS 1.0/1.1 MUST NOT — with perfect forward secrecy within the ESInet and credentials per NENA-STA-040.2-2024. Configuration is `GCS_TLS_MODE` (disabled | tls | mtls) with the `GCS_TLS_*` credential variables (§3.8); `disabled` is plaintext HTTP for local development only.*

***✔ Settled (Session 13, decision 108 — closes the Session 12 KNOWN GAP; see decision 107):** i3 §2.8.1 and §5.4 are now enforced. Listener TLS on both deployment paths runs through `i3_fe_core.security.tls`, not ad hoc `uvicorn.run()` kwargs: the plain-uvicorn path builds its context via `make_server_ssl_context(tls_settings, gunicorn_mode=False)` and genuine `CERT_REQUIRED`, since that process terminates TLS itself. The gunicorn + `UvicornWorker` path runs through `GcsUvicornWorker`, a worker subclass that injects the built context directly rather than going through gunicorn's own certfile/cert_reqs-forwarding chain — the mechanism the Session 12 prior-art report implicated in LVF's earlier silent downgrade. Both paths carry core's PFS cipher enforcement and TLS 1.2 floor. Outbound calls (Logging Service, Discrepancy Reporting callbacks) are built with `httpx.AsyncClient(verify=make_client_ssl_context(settings.tls))`, mirroring `i3_fe_core.app.factory.create_app()` rather than LVF's federation-specific helper, which the GCS has no role to justify (§3.1, decision 4).*

***✔ Settled (Session 13, decision 108):** Enforcement is verified by observed handshake behaviour, not by configuration inspection, and holds on both deployment paths. Across 180 handshake attempts against the gunicorn + `UvicornWorker` path (100 sequential, 80 concurrent across 4 workers) zero connections lacking a valid client certificate were accepted; the plain-uvicorn path rejects the same cases directly. All five required cases pass on both platforms tested: no certificate, an untrusted certificate, TLS 1.1, and a non-PFS cipher are each rejected, and a valid certificate is accepted. This conclusion is scoped explicitly to the pinned toolchain versions recorded in the enforcing module's docstring and is backed by a standing regression suite (`tests/security/`) that will fail if it stops holding — the verification is not a one-time finding.*

***✔ Settled (Session 13, decision 108):** A documented break-glass exists for environments where genuine enforcement is observed to fail: `GCS_GUNICORN_CERT_OPTIONAL_FALLBACK` forces `CERT_OPTIONAL` on the gunicorn path. It is default-unset, is documented in `.env.example` per decision 100's contract that the canonical variable reference omits nothing the service reads, states plainly that setting it disables §5.4 enforcement and that it MUST NOT be set in production, and logs a WARNING-or-higher line at worker startup naming itself and stating that enforcement is disabled whenever it is set — so a running service with degraded enforcement is evident from its own logs, not only from its configuration. The correct response to needing the flag is to report the environment, not to leave it set.*

***✔ Settled (Session 12, decision 107, retained under decision 108):** `GCS_TLS_CLIENT_CERT_FILE` and `GCS_TLS_CLIENT_KEY_FILE` are REMOVED from `.env.example` rather than wired. They were inherited from the LVF template, where the identically-named variables are genuine — LVF presents a client certificate on its own peer-federation traffic (child→parent sync and recursion). The GCS has no federation role (§3.1, decision 4), and decision 108's outbound wiring confirms the resolution anticipated here: the GCS's own server certificate now doubles as its outbound identity on Logging Service and DR traffic, so no separate client-certificate variable was ever needed.*

### 3.9.4 Operational Endpoints

***✔ Settled (Session 11, decision 101 — resolves Appendix C.4 Q11; complements decision 94):** Liveness and readiness are distinct endpoints answering distinct questions, and only readiness gates traffic. `/health` is LIVENESS: it returns 200 whenever the process is up, carrying `status`, `elementState`, `ntpHealthy`, and the GIS record counts as advisory fields — a worker with stale GIS data or drifted time is impaired but alive, restarting it fixes nothing, and the impairment is already externally visible through ElementState/ServiceState and `/ready`. `/ready` is READINESS: it returns 503 while a GIS reload is in flight or before any GIS data has ever loaded (§3.5), and it is the endpoint a load balancer should check. This is a recorded, deliberate divergence from i3-fe-core's own `create_app()` convention, whose health route returns 503 when element state is not Normal or NTP is unhealthy — making `/health` 503 as well would collapse the liveness/readiness split into one signal. Core's conformance suite accepts either status code, so the divergence is interoperable. The remaining operational endpoints — `/ElementState`, `/ServiceState` (read-only HTTP views of the notifier state, §A.4/§A.5), `/metrics` (operations tooling, outside this specification), and `/Gcs/Versions` (§3.9.1) — carry no traffic-gating semantics.*

### 3.9.5 Load Shedding

***✔ Settled (Session 11, decision 100 — resolves Appendix C.4 Q9):** The shedding response is a TRANSPORT-layer response, emitted before a request is admitted as a GCS operation, and therefore outside §1.2.1's closed status set — which governs conversion outcomes, not connection admission. This is the same reading that already permits 413 (oversized body, rejected by middleware before admission — emitted by the implementation since the plumbing pass) and 405: once a request is admitted as a Geocode or ReverseGeocode operation, only the five §4.5 codes may describe its outcome; before that, HTTP is HTTP. A shed request receives 429 with a `Retry-After` header and no i3-shaped body. It is never 454, which tells a shedding client nothing and invites the retry storm shedding exists to prevent, and never 468, which asserts a search happened. Sustained shedding is an ElementState-reportable condition.*

***◐ Declined for now (decision 112):** Shedding itself remains UNIMPLEMENTED, and is no longer carried on Appendix C.3's active deferred-work list — decision 100 above settles what the status shape would be if built, but building it is deprioritized rather than scheduled. No configuration variables are reserved for it. Revisit if operational load ever exceeds what transport-layer protections already bound.*

## 3.10 Civic Element Model and PIDF-LO Mapping

***✔ Settled:** The element model carries STA-006.3 column names throughout the engine — `CivicAddress` matches the SSAP civic block field for field, which makes §11.1's reverse derivation a copy rather than a translation and gives §6.5 like-named fields to compare. Translation between PIDF-LO `ca:` element names and those column names happens once, at the wire layer, in both directions (decision 62).*

*The mapping is not this document's invention. NENA-STA-004.2-2024 states it element by element, in the form "CLDXF-US name (PIDF-LO name)"; the table below is a transcription for implementation convenience, and STA-004.2 governs on any disagreement.*

| STA-006.3 column | PIDF-LO element | CLDXF-US name |
|---|---|---|
| Country | `ca:country` | Country |
| A1 | `ca:A1` | State |
| A2 | `ca:A2` | County |
| A3 | `ca:A3` | Incorporated Municipality |
| A4 | `ca:A4` | Unincorporated Community |
| A5 | `ca:A5` | Neighborhood Community |
| Post_Comm | `ca:PCN` | Postal Community Name |
| Post_Code | `ca:PC` | Postal Code |
| PostCodeEx | `cdx2:PCE` | Postal Code Extension |
| AddNum_Pre | `cae:HNP` | Address Number Prefix |
| Add_Number | `ca:HNO` | Address Number |
| AddNum_Suf | `ca:HNS` | Address Number Suffix |
| AddNum_Cmp | `cdx2:HNC` | Address Number Complete |
| St_PreMod | `ca:PRM` | Street Name Pre Modifier |
| St_PreDir | `ca:PRD` | Street Name Pre Directional |
| St_PreTyp | `cae:STP` | Street Name Pre Type |
| St_PreSep | `cdx1:STPS` | Street Name Pre Type Separator |
| St_Name | `ca:RD` | Street Name |
| St_PosTyp | `ca:STS` | Street Name Post Type |
| St_PosDir | `ca:POD` | Street Name Post Directional |
| St_PosMod | `ca:POM` | Street Name Post Modifier |
| Site | `cdx2:SITE` | Site |
| SubSite | `cdx2:SUBSITE` | SubSite |
| Structure | `ca:BLD` | Structure |
| Wing | `cdx2:WING` | Wing |
| Floor | `ca:FLR` | Floor |
| UnitPreTyp | `cdx2:UNIT_PRETYPE` | Unit Pre Type |
| UnitValue | `cdx2:UNIT_VALUE` | Unit Value |
| Room | `ca:ROOM` | Room |
| Section | `cdx2:SECTION` | Section |
| Row_ | `cdx2:ROW` | Row |
| Seat | `ca:SEAT` | Seat |
| Addtl_Loc | `ca:LOC` | Additional Location Information |
| Place_Type | `ca:PLC` | Place Type |

*Columns with no PIDF-LO counterpart are not emitted on the wire and are not populated from it: `MSAGComm` and the `LSt_*` legacy street name fields (legacy MSAG constructs, outside CLDXF-US), `AddCode`, `FloorIndex`, and `Unit` where the provisioned schema carries a complete form alongside `UnitPreTyp`/`UnitValue`. They remain available to §6.5 scoring where the record carries them; they simply have no wire representation.*

***✔ Settled — the address number is an integer, and a query that cannot supply one loses the element rather than the request.*** *STA-004.2 §3.3.3.5 types Address Number as a non-negative integer, narrowing RFC 5139's string typing; since this service is CLDXF-US-scoped (§3.1), the integer typing governs and `Add_Number` is correctly an integer throughout. Decomposition of a complete address number into prefix, integer, and suffix is likewise STA-004.2's own rule, not this document's invention (§3.3.4, §3.3.5). Where a query supplies an address number the wire layer cannot reduce to a non-negative integer, the element is dropped and the request proceeds without it (decision 63).*

# 4. Geocode — Stage 0: Request Admission

## 4.1 Body, Content-Type, and Schema Validation

***✔ Settled (Session 3):** Schema validation failure — malformed body, invalid XML, a document that is not a PIDF-LO, or a PIDF-LO whose structure fails the envelope schemas (RFC 3863 / RFC 4119) — returns 454 on both operations, with a human-readable reason in the response body as this implementation’s convention. 468 is not used for this: it asserts a search was performed. 454 remains a poor fit — it tells the caller nothing and the normative YAML does not even list it for /ReverseGeocode, leaving a schema-invalid reverse request with no defined error code at all — but it is the only available bucket, and returning it on both operations follows the YAML’s evident intent over its asymmetry. The underlying deficiency (i3 gives its services no vocabulary for “your request was malformed”) and the 454 asymmetry are §16 rows.*

*Implementation detail, retained as a plain statement: validation runs against one combined schema (`schemas/gcs-pidflo.xsd`) importing the PIDF envelope (RFC 3863 / RFC 4119), the civic namespaces, the GML/GeoShape subset, and RFC 7459 confidence, before admission. The RFC 4479 data-model wrapper is the one deliberately unvalidated region — decision 105.*

## 4.2 Multiple Location Handling

i3 §4.5 states that if the PIDF-LO in the request contains more than one location, the return MUST contain only one result, which is the conversion of the first location in the PIDF-LO. This is one of the few unambiguous normative rules in §4.5 and is implemented exactly.

***✔ Settled (Session 5):** i3 §4.5 is explicit and leaves no discretion: where the request PIDF-LO carries more than one location, the response must contain exactly one result, being the conversion of the first location. Rejecting a multi-location request as an error was considered and rejected — it would add a restriction i3 does not impose, which decision 2’s corollary bars as firmly as adding capability.*

***What “first” means.***\* i3 does not say, but RFC 5491 Rule #8 does, and it is a typed precedence rather than raw document order: priority goes to the first `<device>` element containing a location; failing that, to the first `<tuple>` element containing a location; and locations carried in `<person>` elements are used only as a last resort. This document adopts Rule #8 directly. (Editorial note, Session 11: an earlier revision of this paragraph lost the three element names to a rendering defect, leaving text that misstated the precedence; the code has always implemented device → tuple → person.) A structural consequence worth recording (decision 105): RFC 3863's content model is a sequence of `tuple*`, `note*`, then `xs:any ##other*`, so a `<dm:device>` must appear AFTER every `<tuple>` in a valid document — document order and Rule #8 order point in opposite directions for device-versus-tuple by construction, which is precisely why Rule #8 has to be a typed precedence rather than "the first one you meet."\*

***Type is not consulted in the selection.***\* Because i3 says “the first location” without qualification, the selection is literal: the Rule #8 precedence elects one location, and if that location does not carry the chunk the operation requires — a civic chunk for Geocode, a geodetic chunk for ReverseGeocode — the request returns 468 rather than continuing through the document in search of a more convenient one. Walking past an elected location to find a better-typed one was considered and rejected: it would have the GCS infer intent the caller did not express, and silently produce a result derived from a location the standard did not nominate. Note that chunk order within a single cannot be used for type selection in any case — RFC 5491 Rule #7 requires the coarse element first in a compound location, so ordering there encodes coarseness rather than relevance.\*

***The discard is reported, not silenced.***\* i3’s rule mandates discarding every location after the first with no mechanism to tell the caller it happened. The i3 interface therefore carries no indication, as required. The enhanced interface (§3.9.2) reports how many locations the request carried and that only the elected one was converted — which is precisely the deficiency the second interface exists to expose. §16 row.\*

***Symmetry.***\* i3 states this rule for Geocode only. This document applies it identically to ReverseGeocode (§9), since no reading makes a multi-location reverse request meaningfully different. The asymmetry in the source text is a §16 row.\*

***✔ Settled (Session 11, decision 102 — resolves Appendix C.4 Q17):** A well-formed, schema-valid document carrying no location whatsoever — a `<presence>` whose tuples have status and no `<geopriv>`, which RFC 3863's optional content model admits — returns 468. It is the same shape of failure as an elected location lacking the required chunk: nothing convertible, in a request that is not malformed. 454 would assert malformation this request does not have; the objection that 468 asserts a search was performed applies equally to the chunk-check 468 decision 50 already settled, and the closed set offers no third code. Consistency between the two nothing-convertible cases governs.*

***✔ Settled (Session 11, decision 105 — resolves Appendix C.4 Q15):** The RFC 4479 presence data model elements (`dm:device`, `dm:person`) are admitted through RFC 3863's lax `xs:any` without a schema of their own in the validation set — a documented validation-scope boundary, accepted rather than closed. What escapes validation is the `dm:*` container structure only, never the location content: lax processing validates any element whose declaration the combined schema knows, so a `gp:geopriv` inside a malformed `dm:device` is still fully validated wherever it appears, and a malformed wrapper can affect only Rule #8's container classification. The closure path — adding RFC 4479's data-model schema to the wrapper — is named and deliberately not taken.*

## 4.3 Profile Check

***✔ Settled (Session 11, decision 102 — resolves Appendix C.4 Q16):** There is no separate profile gate, and this section deliberately carries no rule of its own — §4.2's election-then-check sequence is the whole of profile handling. A document carrying only the wrong profile has its ELECTED location fail the chunk check and returns 468, with no walking of the document for a better-typed location. A document carrying both profiles selects by namespace within the elected `<location-info>`, never by position, because RFC 5491 Rule #7 makes position encode coarseness rather than relevance. A standalone profile check would be a gate i3 does not ask for, which §5 forbids adding.*

# 5. Geocode — Structural Conformance

***✔ Settled (Session 1):** There is no Gate 1. i3 §4.5 imposes no structural precondition on Geocode; requiring one would add a restriction the standard does not have (§1.2.1). A street-level query with no HNO is accepted and answered at rung 3 (§3.3). The honesty burden moves to uncertainty (§7.4), which is where RFC 5491 already provides the vocabulary.*

The adjacent case is more dangerous and is allowed for the same reason: an HNO is submitted, no address-level match exists — new construction, or an address not yet provisioned — but the street matches. Falling back to rung 3 is useful and silently degrades precision without the client having asked. It is permitted; the uncertainty must carry the degradation, and on the i3 interface it is the only signal available (§2.2).

# 6. Geocode — Candidate Identification

## 6.1 Layer Search Order

*SSAP is searched first and RoadCenterLine second, per the §3.3 ladder and following i3 §4.5's own ordering — **"site/structure address points or road centerlines."** Search order is a starting sequence, not a preference among answers; the rule below governs which rung's candidates the response actually carries.*

***✔ Settled (decision 70):** Search order is not acceptance order. The response carries one rung's candidates, but the winning rung is chosen by comparing each rung's best candidate on blended confidence (§7.4), not by taking the first rung that produced anything. A rung-1 best at or above the INTERPOLATED_POINT ceiling (75) ends the search — no road answer can beat it, so the well-provisioned common case never scores the RCL layer. Ties go to the more precise rung.*

## 6.2 Candidate Set

***✔ Settled:** There is no progressive filter. Every temporally-valid record in the searched layer is scored against the query on every request; no record is excluded from scoring on the basis of any civic element (decision 61). Amended by decision 69 — SSAP house-number identity is now a hard gate, not a scored field. Road interpolation is unaffected. See also decision 71 (§6.5): a candidate whose street name is neither phonetically equivalent nor edit-similar to the query's is disqualified after scoring — every record is still scored and its breakdown computed, so §6.2's "discards nothing unseen" property holds; the disqualification zeroes the total rather than skipping the record.*

***✔ Settled (decision 82, supersedes 81) — no A1/Country gate; §6.2's rule stands unamended for administrative fields.** Decision 81 briefly made A1 and Country pre-scoring exact-match candidate-set gates; decision 82 reverts that before implementation. Against a single-state data export, a hard A1 gate empties the candidate set for a caller who names the wrong state — a real border scenario (Fargo/Moorhead, Pembina at the Canadian line), and decision 80's Lincoln-for-Bismarck caller at the state level — turning a query the weighted terms would have answered correctly into a 468. A1 and Country remain weighted terms, compared as binary exact-match after normalization rather than by edit distance; see §6.5 and decision 82. The only candidate-set gates are Add_Number (decision 69) and UnitValue (decision 75), where a differing value names a different building, not a caller's administrative confusion.*

*Two exclusions are not part of this rule and remain in force. §3.4's temporal filter is a correctness test, not a narrowing one — a record outside its Effective/Expire window is wrong rather than merely unlikely, and is excluded before scoring. `GCS_MIN_MATCH_SCORE` (§6.4) applies after every record has been scored, so it discards nothing unseen.*

*No **\<**valid**\>**/**\<**invalid**\>** accounting is maintained; **\<**unchecked**\>** semantics feed §7.4.*

## 6.3 Ambiguity and Tie-Breaking

***✔ Settled (Session 1):** The ambiguity test is geometric, not combinatorial. Where surviving candidates agree horizontally and differ vertically, they are merged unconditionally and the vertical uncertainty spans the extent — the extent is the answer (§3.7.3). Where they differ horizontally beyond tolerance, 468 is returned: two **“State Street”** matches forty miles apart are not a location, and merging them yields a position in a field with a 32 km uncertainty that a consumer ignoring uncertainty will treat as an answer.*

*✔ Settled (Session 2) — Duplicate GIS records (two points with identical attributes but different GUIDs) are a data-hygiene defect that should be caught before the GCS ever receives the data, not a geometric merge case, and are out of scope here. The real case the merge logic exists for is a generic query — no unit, floor, or other distinguishing element supplied — that legitimately resolves to two or more distinct SSAP candidates on one large parcel (e.g. a farmhouse and a machine shed sharing an address). For that case: the i3-improved interface returns both candidates, ranked and scored on their merits (§6.5) — the honest answer to an underspecified query is a real candidate list, not a synthetic blended point. The i3 interface, constrained to a single pidfLoGeo, returns a centroid/average position across the qualifying candidates with uncertainty sized to their extent, consistent with §3.7.3’s minimise-maximum-error principle. The averaging approach on the i3 interface is this implementation’s own choice and is not proposed to NENA; the underlying gap — i3 has no vocabulary for a legitimately multi-point answer — is recorded in §16 and is NENA-facing. Vertical agreement still merges unconditionally per the original rule; only the horizontal case was reworked.*

*✔ Settled (Session 9) — resolves Q33. Confidence does not degrade for a merge. The Circle's radius already carries the measured extent; confidence remains the matchScore/locationType dial decision 31 defined, and stays orthogonal to it by design, matching RFC 7459's own confidence/pdf separation as this implementation applies it (§7.4, decision 88). No code change — the mechanism was already correct.*

## 6.4 No-Candidate Conditions

***✔ Settled (Session 11, editorial — the enumeration the drafting note asked for, as implemented):** Every path to zero candidates maps to 468, and no coverage test distinguishes them (§3.6.2). The paths: the searched layers hold no record in force at the request instant (§3.4); no record clears `GCS_MIN_MATCH_SCORE` after scoring; every clearing record is disqualified by decision 71's street-name gate; every surviving record is unlocatable (decision 55 — no usable geometry); a house-number query matches no SSAP identity (decision 69) and falls within no segment's asserted range; or §6.3's ambiguity test fails beyond tolerance. A consumer cannot tell these apart — so the implementation does not distinguish them either, beyond the log.*

***✔ Settled (Session 14, decision 114):** As of this session 468 does carry a body field, but it does not reopen the sentence above: the field's value is fixed and identical across every path listed here, never the path-specific internal reason. A consumer still cannot tell these apart from the response alone — only whether a result was derivable at all.*

## 6.5 Scoring

*✔ Settled (Session 2) — One scoring function, not a two-stage exact-then-fuzzy pipeline. Prior art (PostGIS Tiger geocoder’s rate_attributes, Nominatim’s ranking) converges on a single per-field similarity comparison evaluated across a continuum, with an exact match simply occupying the top of that scale rather than taking a separate code path. Each candidate is scored by comparing fields (street name, type, direction, etc.) with a similarity measure; an exact match scores at the ceiling of the same function a fuzzy match scores lower in. This is this implementation’s own scoring logic — proprietary, not proposed to NENA. What is standardizable is the element model only — which fields exist and how they map to STA-006.3 — never the comparison mechanism itself.*

***✔ Settled (Session 3):** The per-field similarity results are not internal-only: they are surfaced on the i3-improved interface as the matchScore per-field breakdown (§7.4), following HERE’s fieldScore precedent — so a consumer can see which field dragged a candidate down. The comparison mechanism itself remains proprietary; only the output shape (field names, score ranges) appears on the interface and in the NENA-facing extension proposal.*

***✔ Settled (Session 5) — the mechanism, not the tuning (decision 66).***\* matchScore is a weighted average of per-field similarity restricted to the civic elements the QUERY populated (`CivicAddress.populated()`), renormalized by the weight actually used. An unsupplied County, A1, or Country therefore costs the candidate nothing — it is excluded from both numerator and denominator rather than scored as a mismatch or padded with a default, consistent with §6.2's rule that `populated()` reflects what the caller actually asserted rather than what the schema permits.\*

*Each field's weight is a base editorial weight — validated statewide by decision 89, not retuned — multiplied by a discriminative factor MEASURED from the currently loaded GIS layer (`src/gis/field_stats.py`): 1 minus the share of records holding that field's single most common value, recomputed on every GIS load and reload. A field uniform across the deployment (a statewide export whose Country column reads "US" on every row) costs near nothing regardless of the editorial weight; a field that is mostly but not entirely uniform would be weighted in proportion to how often it actually varies, so a query that does supply state and disagrees with a border record would still be told apart from one that agrees — though direct verification against the currently loaded ND export found A1 uniformly "ND" with no border-parcel variation at all, so in THIS deployment A1 reads discriminative_factor 0.0, same as Country; see decision 68. This is not a second guess stacked on the first — it is the one part of the weight that is read off the provisioned data rather than authored, and it is silent on which fields matter editorially in the first place.*

*Community/municipality is resolved via a cascade before comparison — A3 (incorporated municipality) → A4 (unincorporated community) → Post_Comm (postal), first populated wins — the same shape as the Z-precedence chain (decision 51/55) and the horizontal-position precedence (decision 55), applied here to "what is this address's community" rather than "where is this address." This is deliberate: accuracy investment is headed toward the admin elements (A3/A4) over the postal ones, and the cascade means matching shifts onto better-provisioned sources automatically as that improves, with no spec change needed later. See decision 66. MSAGComm was originally a fourth cascade tier and is removed by decision 76 — see below; the field's discriminative factor is likewise no longer computed. The weight applied to Community is the discriminative factor of whichever field actually resolved the comparison value for that record — not a single fixed field's statistics regardless of which tier resolved it — per decision 76.*

***✔ Settled (Session 5) — Add_Number is a gate, not a scored field (decision 69).***\* House number is not part of the weighted average above for SSAP (rung 1) candidates. It is instead a hard equality gate applied in candidate identification (§6.2) before scoring runs at all: a query that supplies Add_Number only reaches this scoring function against SSAP records whose Add_Number already matches exactly. The matchScore breakdown still reports `Add_Number: 100.0` for transparency when the query supplied one, but that entry is fixed and takes no part in the weighted average — it would only ever contribute a constant among survivors. General-purpose edit-distance similarity (decision 28) is the wrong tool for an identity field: two house numbers differing by one digit are two different buildings, not a near-miss of the same one, and scoring them as ~67% similar let false proximity smuggle wrong-address candidates into the surviving set. Road interpolation (RCL, rungs 2/3) never had an Add_Number similarity term and is unaffected — §7.2's range/parity containment already resolves house number as a correctness test, not a comparison.*

***✔ Settled (decision 75) — UnitValue is a conditional identity gate, mirroring decision 69 with a sparseness carve-out.** Where the query supplies a unit value AND the SSAP candidate also carries one, the two must match exactly (after trim/casefold normalization; UnitPreTyp — "Apt"/"Unit"/"Suite" — is not part of the gate, only the value itself) for the candidate to qualify at all. A candidate carrying no unit at all is NOT gated out even when the query supplies one — decision 61's "sparseness costs score, not candidacy" governs here, since most SSAP records (85%+ in the provisioned data) have no unit populated at all and are ordinary single-unit addresses, not non-matches. Where the query supplies no unit, the gate does not apply regardless of what candidates carry. UnitValue takes no part in the weighted average, the same as Add_Number.*

***✔ Settled (decision 76, amends 66) — MSAGComm dropped from the Community cascade; discriminative factor follows the resolved field, not a fixed one.** The cascade shortens to A3 → A4 → Post_Comm, first populated wins; MSAGComm is a legacy pre-NG9-1-1 field this GCS does not rely on. Both score_ssap and score_rcl's Community weight term now look up field_stats' discriminative factor for whichever field in the cascade actually resolved that record's comparison value, rather than a single field fixed in code (previously f("A3") for SSAP, f("Post_Comm") for RCL, regardless of which tier actually produced the value being compared).*

***✔ Settled (decision 80, supersedes 77) — Community is a weighted term with a bounded mismatch penalty, not a qualification gate.** Decision 77's hard gate (matchScore forced to 0 on a disqualifying Community mismatch) is reverted: a caller confident of the street address but unsure of the administrative community name may legitimately name the wrong town (e.g. "Lincoln" for an address actually in Bismarck) without being wrong about the address itself, and a hard gate excluded that caller's true match entirely rather than merely ranking it lower. Community returns to decision 76's ordinary weighted-average treatment for qualifying values. For a candidate whose Community fails decision 77's original test (not Soundex-equivalent AND below `_COMMUNITY_QUALIFY_MIN_EDIT_SIM`), the Community term's similarity is clamped as a ceiling to `_COMMUNITY_MISMATCH_SIMILARITY_CAP` (0.15) rather than the natural Soundex/edit-distance blend — a `min()`, so a pair the blend already scored lower than the cap keeps its lower value. On RCL, the cap applies after §7.2 side selection, so side choice runs on the uncapped blend and the cap, the reported score, the weight, and the field lookup all commit to the same side. A record with no resolvable Community value is unaffected by either the qualifying path or the cap: sparseness costs score, not candidacy (decision 61). A dedicated sweep found the cap mechanism cannot meaningfully lower a wrong_community score at any value tested (mean 91.63-92.18 across cap 0.0-0.50, 100% still clearing GCS_MIN_MATCH_SCORE) — Community is one of seven averaged terms, so even zeroing it leaves the other six, which score 100 in a wrong-community pair by construction, dominating the result. The cap is retained as a genuine improvement in kind over the old gate (a caller naming the wrong town is no longer categorically excluded) but does not deliver a wrong_community score materially closer to the admission floor; see decision 80 and Appendix C item (d) for the open question of a whole-score penalty as a further step.*

***✔ Settled (decision 72) — similarity is a Soundex/edit-distance blend for free-text fields.** The per-field similarity for hand-typed name fields (Street Name, Street Type, Street Direction, Community, County) is an equal blend of normalized edit-distance similarity and a binary Soundex comparison, with an exact match short-circuiting at the ceiling before either runs. Pure edit distance overcredits short unrelated names — "Del Rio" vs. "El Paso" scores 42.9% on character operations alone despite sharing no sound — and no editorial weight can correct that, because the inflation is inside the field score itself. Country and A1 are excluded from the blend (edit distance only): they are 2-3 character controlled-vocabulary codes, not names a caller misspells, and Soundex on a two-letter token is noise. Decision 82 resolves the categorical question fully: Country and A1 (and the directionals) are compared as binary exact-match after normalization, out of edit distance entirely; A2 stays in the blend as hand-typed. Appendix C.4 Q30 is closed.*

***✔ Settled (decision 82, supersedes 81) — three comparison classes, and every civic element belongs to exactly one.** This decision closes the per-field comparison-mechanism questions as a set rather than one field at a time. **(1) Identity gates** — Add_Number (decision 69) and UnitValue (decision 75), unchanged: a differing value names a different building. **(2) Controlled-vocabulary binary terms** — St_Dir, A1, and Country: exact match after normalization scores 1.0, anything else scores 0.0; weighted terms in the average, never gates. No edit distance and no Soundex — string similarity on a closed vocabulary is not just unhelpful but actively wrong: measured against the live similarity code, "NE" vs. "NW" scored 0.889 under the blend (NORTHEAST and NORTHWEST are edit-similar and Soundex-identical, both N632), near-full credit for opposite quadrants, and "SD" vs. "ND" scored 0.50 on one shared character (Q30's original complaint). Binary scores both at 0. This matches the PostGIS TIGER geocoder's practice: parsed pre/post directionals are compared as discrete categorical attributes with a fixed penalty on mismatch, with soundex/levenshtein fuzzy matching reserved for street names and places. **(3) Hand-typed name blend** — St_Name (with decision 71's qualification), St_Type, Community (with decision 80's cap), and A2: decision 72's Soundex/edit-distance blend, unchanged.*

*St_Dir remains ONE weighted term covering both directional slots (St_PreDir and St_PosDir), compared best-of-both-sides against the record: the query's directional is checked against both of the record's slots and the best result taken. A position swap — "Main Street North" spoken for a street formally named "North Main Street" — therefore scores full credit, deliberately: the caller named the right street in spoken order, the TIGER normalizer itself reassigns pre/post freely during parsing, and on a term weighted 8 of ~82 any graduated swap penalty would be invisible in the final score (decision 80's dilution lesson). A genuinely wrong directional ("N" for a street carrying only "S") scores 0.0 on the term — a real but bounded ranking cost, at most ~10 points off a perfect score, which drops the candidate below a directional-correct competitor without excluding it. Decision 81's gates are reverted before implementation: A1 and Country return to `_BASE_WEIGHTS` as ordinary weighted terms with the binary comparison above; no candidate-set filtering occurs on either field (see §6.2). Q30 is fully closed.*

***✔ Settled (decision 71) — street name qualifies candidacy.** When both the query and a record assert a street name, the candidate is disqualified (matchScore forced to 0) unless the names are phonetically equivalent (Soundex) or reach a minimum edit similarity — a name failing both is a different street, not a typo of this one, and no accumulation of town-constant fields (street type, community, county) can carry it back into the response. The per-field breakdown is still computed and reported, so the disqualification is visible rather than silent at a floor of 0. A record with no provisioned street name is not disqualified: sparseness costs score, not candidacy (decision 61). This matches production geocoder practice — the PostGIS TIGER geocoder retrieves candidate streets through a Soundex-indexed name lookup, so a phonetically unrelated name never becomes a candidate at all, with edit distance ranking only the qualified.*

***✔ Settled (decision 73) — digit-leading street names split into an exact-match digit gate and a fuzzy letter suffix.** Soundex has no representation for digits — it encodes letters only, a property of the algorithm itself and not of this implementation — so a token like "2nd" and "22nd" reduce to the same surviving letters ("ND") and share a Soundex code despite naming different streets. Where either side of a street-name comparison begins with one or more digits, the token is split into its digit run and letter suffix ("22nd" → "22" + "ND"). The digit runs must match exactly for the candidate to qualify at all — an identity gate in the shape of decision 69's house-number gate, not a similarity term, since two differing digit runs are two different streets, not a typo of one. Soundex is never consulted for a digit-leading token. Once the digit gate is passed, the letter suffix is compared by edit-distance similarity alone against decision 71's qualification threshold — again no Soundex, since a two-to-three-letter ordinal suffix (ST/ND/RD/TH) is too short for Soundex to say anything meaningful, the same reasoning decision 72 already applies to Country/A1. A token where neither side is digit-leading is unaffected and continues through the existing Soundex/edit-distance blend unchanged.*

***✔ Settled (decision 74) — edit distance is transposition-aware everywhere it's used.** The edit-distance primitive underlying `_normalized_similarity` (and decision 73's suffix comparison) is Damerau-Levenshtein restricted to adjacent transpositions only (the "optimal string alignment" form): swapping two adjacent characters counts as one edit rather than the two a plain Levenshtein distance charges it. This applies everywhere edit distance is used — as written, the free-text Soundex/edit-distance blend, the digit-leading suffix comparison, and (at the time) the pure-edit-distance categorical fields Country and A1 — not just the case that surfaced it. **Decision 82 has since removed that third site:** Country, A1, and St_Dir are compared as binary exact-match and run no edit distance at all, so this decision's live scope is now the blend and the digit-leading suffix only. The primitive itself is unchanged. Qualification thresholds, blend weights, Soundex logic, and decision 73's digit-identity gate are unchanged; only the distance primitive itself is replaced. A transposition still scores below an exact match — it is priced more accurately, not forgiven.*

***✔ Settled (Session 9) — the base weights are validated, and the factor lookup follows the value.*** A statewide pairwise ranking sweep (431,239 SSAP records) confirms `_BASE_WEIGHTS`' editorial ordering survives multiplication by the measured discriminative factors: every empirically testable field pair ranks correctly, unanimously, across two independent samples (decision 89). An earlier six-county extract appeared to invert Community against St_Type; that was an artifact of one metro dominating a small footprint, not a defect in the weights or the formula. Where the two-slot terms (St_Dir, St_Type) are concerned, the discriminative factor is read from the slot that actually produced the compared value, extending decision 76's per-record lookup from the Community cascade to the directional and street-type slots (decision 90). Shared-suffix normalization for A2 is considered and declined: every ND county name carries the literal token "County", which lifts every wrong-county comparison above the mismatch floor, but a correct county still outscores a wrong one by roughly nine points in every pair measured, so the inflation compresses a gap it never inverts (decision 91).*

# 7. Geocode — Position Derivation

## 7.1 SSAP-Derived Position

*✔ Settled (Session 2) — Z precedence chain: geometry Z wins; if the geometry carries no Z, Altitude is the fallback; if neither is available, Elevation (ground-level HAE, STA-006.3 §5.43) is the last resort. All three are confirmed to sit on the same WGS84/HAE datum — Elevation is HAE at ground level, Altitude is HAE at the point’s own height, Height (§5.50) is just their difference (AGL) — so the chain reconciles values on one consistent vertical reference rather than mixing datums. No discrepancy-report mechanism is triggered on disagreement; the chain resolves silently. §16 row retained for the underlying STA-006.3 gap (four places a Z can live, transitional fields per Table 8-1).*

***✔ Settled (Session 11, editorial — the remaining specifics the drafting note listed, all settled elsewhere and gathered here):** CRS handling is §3.7 / decision 55 — EPSG::4326 or ::4979 as a per-answer property of the matched geometry's admitted dimensionality, with every RCL-derived answer 2D (decision 85). Coordinate ordering: the engine works in (x, y) longitude-first because that is what its geometry library means; RFC 5491 / GML serialise latitude-first, and the swap happens exactly once, in the wire layer. Precision: coordinates serialise at 8 decimal places (≈1 mm), heights and radii at 3 (1 mm), and enhanced-interface scores at 3 — precision beyond the positional accuracy of any provisioned GIS data, chosen so serialisation never becomes the binding precision.*

## 7.2 RCL-Derived Position — Address Range Interpolation

*✔ Settled (Session 2) — Interpolation is proportional to address number, walked along the segment’s actual vertex geometry (bends and curves), not a straight chord between endpoints. A configurable endpoint margin, GCS_RCL_ENDPOINT_MARGIN_M, trims this distance off each end of the segment’s usable geometry before interpolation runs; the full address range then compresses to fit the shortened path (e.g. HNO 100 lands at the margin-in point rather than the true segment start, HNO 200 at length-minus-margin). This exists because perpendicular offset direction (§7.3) is unstable near a joint or sharp bend close to a segment’s start/end, and excluding that geometry from interpolation entirely avoids ever deriving a position — and therefore an offset — from the unstable zone.*

***✔ Settled (Session 5) — zero-length ranges.***\* Where a side’s range has From equal to To, the interpolation fraction (HNO − From) / (To − From) is 0/0 and undefined. Such a segment asserts exactly one address on that side and says nothing about where along the block it sits. The result is the midpoint of the segment, on the matched side, with the §7.3 setback applied, tiered INTERPOLATED_POINT at ceiling 75. The endpoint margin (GCS_RCL_ENDPOINT_MARGIN_M) does not participate, a midpoint being nowhere near an endpoint. Returning the segment line at STREET_SEGMENT was considered — it would follow §7.4’s geometry-as-answer reasoning — but the midpoint gives a dispatcher a position rather than a corridor, and §3.7.3’s minimise-maximum-error principle supports it directly: the midpoint bounds the worst-case error at half the segment length, which is the best available bound when the address is known to be somewhere on the block.\*

*The reverse direction has no corresponding defect, and the asymmetry is worth stating. Reversing computes From + fraction × (To − From), which for a zero-length range yields the single asserted number for any fraction — no rounding, no parity forcing, no synthesis. §11.2 therefore produces its most trustworthy output on precisely the record that breaks the forward direction, and the round trip holds exactly: the midpoint projects back to roughly half-way, which maps to the same number it started from.*

***✔ Settled (Session 5) — single-address ranges.***\* No separate rule is required. In well-formed data a side’s parity is consistent with its endpoints, so a side carrying a single address expresses it as From equal to To and is handled by the rule above. A side with two distinct endpoints — From 100, To 102, parity even — carries two addresses and interpolates normally: 100 lands at the segment start and 102 at the end, with GCS_RCL_ENDPOINT_MARGIN_M drawing each inward, which is the condition that margin exists for.\*

***✔ Settled (Session 5) — parity mismatches.***\* Parity_L/R governs two things and no others: which side of the segment a house number belongs to, and the parity to which a synthesised number is forced in the reverse direction (§11.2). It never blocks a forward match. Where the parity field contradicts the range it labels — a side marked even whose range is 100 to 101, or a query for 101 against that side — the asserted range governs and the match proceeds. A caller asking for a number the data contains receives it. A parity field inconsistent with its own endpoints is a GIS data-quality defect for the SI to correct, which is the position §11.3 and §11.4 already take on record-level defects, and the GCS does not silently repair it on the wire.\*

***✔ Settled (decision 87, adopts 67) — the forward direction has exactly one side-selection rule, and it is parity.***\* The side of a segment on which a house number falls is determined by the query's Add_Number parity against the record's Parity_L/Parity_R. That single rule is consulted at two points in the pipeline — by §6.5's scoring, which needs a side to compare administrative and postal attribution against and necessarily runs before position derivation (decision 67), and by this section and §7.3, which need a side to interpolate along and to offset from. They are the same rule applied to the same inputs at different moments, not two mechanisms that could disagree, and no cross-check between them is required or meaningful. The reverse direction resolves side by projecting the origin onto the segment (§11.2, §11.3) for the only reason available: a reverse request carries no house number from which parity could be derived. The directions differ in input, not in policy.\*

***The two ends fall back differently, and deliberately so.***\* Where parity does not resolve a side, §6.5's scoring compares both sides per element and keeps the better similarity (decision 67) — it never commits to a wrong side because it does not commit at all, taking a maximum instead. This section, needing an actual position rather than a comparison, falls back to the asserted range as stated above. The two can therefore land on different sides for one record, with a visible consequence: decision 80 has scoring commit to a side for reporting, so the per-field breakdown would describe one side while the returned position derives from the other. This is accepted rather than reconciled. The divergence requires a record whose parity field is null or contradicts its own range — a GIS data-quality defect this section already declines to repair, on the same grounds §11.3 and §11.4 decline to repair sparse attribution — and aligning the two fallbacks would import a range-containment cascade into the scorer to serve only malformed records, at the cost of a mechanism the well-formed case never exercises. Where the data is correct, the two ends agree by construction.\*

***✔ Confirmed (Appendix C.4 R2):** The field names in the provisioned schema are FromAddr_L/R, ToAddr_L/R, Parity_L/R, and `Valid_L`/`Valid_R` — the "Validation_L/R" name this note once hypothesised does not exist. On Z: the interpolation primitive carries whatever dimensions the vertices have (§3.7.1), but no RCL-derived answer propagates it — decision 85 settles every RCL answer as 2D, the layer not being a declared 3D-capable class.*

## 7.3 Setback and the Access Point Problem

*✔ Settled (Session 2) — A single flat configurable offset distance (e.g. GCS_RCL_OFFSET_M), applied perpendicular to the centerline on the side determined by the matched address parity (left/right). The offset MUST never place the returned position exactly on the centerline itself. Google’s distinct navigation-point/entrance concept and STA-006.3’s silence on setback are both noted, but this implementation resolves it as a single configurable perpendicular distance rather than a richer access-point model. §16 row retained — STA-006.3 models neither an access point nor a setback convention.*

## 7.4 Uncertainty and Confidence

***✔ Settled (Session 2) — Return the actual geometry of the matched feature as the answer, rather than synthesizing an uncertainty shape around a point. Rung 1 (SSAP match) → Point. Rung 2 (HNO interpolated within a known range) → Point — the interpolated, offset position. Rung 3 (no HNO, street-level match only) → the segment’s actual line geometry, since there is no basis to collapse it to one position; the line itself is the honest representation of what is known, without inventing a Circle or Ellipse. Future work: a building footprint match → Polygon; a 3D space match → Prism (RFC 5491 §5 GeoShape vocabulary, already in §1.4’s namespace table). The GCS does not evaluate or reason about uncertainty/confidence of the input when deriving a response — the response follows from the matched geometry alone. Both interfaces additionally carry a confidence/uncertainty value alongside the returned geometry, per RFC 7459 (see §1.1) — consistent between the i3 and i3-improved interfaces — as an honesty signal about the returned location, separate from and in addition to the geometry-as-answer approach above; the i3-improved interface also carries the scoring results from §6.5.***

***✔ Settled (Session 3) — the three-field quality model.***\* Industry research (Esri, Google, HERE, Pelias, Bing, AWS, PostGIS Tiger) shows a strong two-axis consensus: match quality and positional precision are carried as separate orthogonal fields, and the one design that blends them into a single number — PostGIS Tiger’s rating — is the least informative of the set. Esri pairs a 0–100 match score with an Addr_type precision tier; Google carries no score at all, only a granularity enum (ROOFTOP / RANGE_INTERPOLATED / GEOMETRIC_CENTER / APPROXIMATE); HERE pairs an overall queryScore with a per-field fieldScore breakdown and a resultType; Pelias carries confidence, match_type, and accuracy as three separate properties. Esri’s composite-locator experience also demonstrates the cost of forcing one ordering: a point match with an acceptable score elevated above a street match with a perfect score confuses consumers in both directions.\*

*Accordingly, each candidate on the i3-improved interface carries three fields. **matchScore** is the §6.5 output — pure field similarity, with a per-field breakdown — answering only “did we find the right record.” **locationType** is an ordered precision tier keyed to the matched geometry class, not the rung number: SPACE_3D → FOOTPRINT_2D → ADDRESS_POINT → INTERPOLATED_POINT → STREET_SEGMENT — answering only “how precisely does that record locate anything,” and extending to future tiers by insertion rather than renumbering. **confidence** is a derived convenience dial: matchScore scaled to the tier’s ceiling weight — SPACE_3D 100, FOOTPRINT_2D 90, ADDRESS_POINT 80, INTERPOLATED_POINT 75, STREET_SEGMENT 50 — computed from the two primary fields and never stored independently, so it can never disagree with them. The confidence value populates the RFC 7459 element on both interfaces, satisfying the Session 2 both-interfaces decision; it is the one thing that fits a single element. The tier ceilings are fixed in this specification rather than configured, so that two GCS implementations reading it cannot disagree about what a confidence value means.*

***✔ Corrected (Session 4) — reachability of the upper tiers.***\* Version 4 asserted that the upper tiers were unreachable because the data model had no layer for them. Direct reading of NENA-STA-006.3-2026 shows that to be wrong as written, and the corrected statement is sharper. The data model carries Site/Structure Address **Polygons** (§4.2.2) with their own Extent Method registry (§6.2: Structure, Site, Parcel, Interior, Other), so FOOTPRINT_2D is reachable today — but as a **Recommended** rather than Required feature class, meaning it is reachable only where a given SI has opted in. The Placement Method registry (§6.1) has likewise grown interior-aware values — InteriorAccess, ExteriorAccess, and InteriorCentroid, the last being precisely this document’s §7.5 convention — though these describe address **points** representing interior spaces, not volumes, so they raise the informational quality of an ADDRESS_POINT match without changing its tier. SPACE_3D remains genuinely unreachable: no volumetric feature class exists. The practical consequence is that the confidence a caller receives for the same real-world address varies by jurisdiction according to whether the SI provisions an optional layer — which is a materially different NENA-facing point from a missing layer, and is recorded as such in §16.\*

*Default ranking is by blended confidence, so a shaky point match can rank below a perfect street match — for 9-1-1, precision that cannot be trusted is a dispatcher sent to the wrong building — while both primary axes travel so a consumer can re-rank on either. A configurable floor, GCS_MIN_MATCH_SCORE, excludes candidates below threshold from the response entirely, which removes most pathological orderings before they arise.*

***✔ Settled (Session 11, decision 97 — resolves Appendix C.4 Q5):** RFC 7459's decimal form is `minExclusive="0.0"` / `maxExclusive="100.0"`, so a confidence of exactly 100 — a perfect matchScore on a SPACE_3D match, once a volumetric class exists — cannot be carried as a number on the PIDF-LO path. A value at or beyond either bound serialises as the token `"unknown"`, which RFC 7459 defines for precisely the case where the schema cannot carry what the producer knows; clamping to 99.9 would report a number the service did not compute. The tier-ceiling table ending at 100 is correct as written: 100 is the top of the internal confidence scale, and the inexpressibility is a wire-schema constraint, not a scale defect. The enhanced JSON path is unaffected — decision 92 declares its bounds inclusive 0–100, since that extension is not bound by RFC 7459's XML schema. The bottom of the scale is moot: GCS_MIN_MATCH_SCORE floors admission well above 0.*

## 7.5 Three-Dimensional Spaces

***✔ Settled (Session 1):** A multi-storey structure is correctly modelled as the individual spaces that comprise it — discrete 3D features — not as one solid extruded to roof height. The returned position for a space is its centroid (§3.7.3). No layer exists for this in STA-006.3. Deferred to future work; the design must accommodate it without rework. §16 row.*

*A consequence worth stating: stacked address points are tempting only because no 3D space layer exists, and modelling spaces as volumes makes STA-006.3 Table 8-1's topology objection moot. That reframes the missing layer from a wishlist item to the missing piece the data model's own future-work list is circling without naming — the §16 row's recommended action says as much.*

***✔ Settled (Session 3):** “Centroid” of a space means the footprint centroid for X/Y and the vertical midpoint for Z — not the centroid of the solid. A volumetric centroid of an irregular space (an L-shaped room with a double-height section) drifts toward the taller portion and can fall outside the occupiable area; the footprint-plus-midpoint form keeps X/Y exactly where a 2D match of the same space would land, so the horizontal answer is unchanged when data graduates from footprint to volume — only Z improves — and the Z half is precisely the value §3.7.3’s minimise-maximum-error rationale reasons about.*

# 8. Geocode — Response Assembly

## 8.1 The i3 Interface — GeodeticData

***✔ Settled (Session 1):** pidfLoGeo carries the geodetic representation only. i3 §4.5 says Geocode **“returns a PIDF-LO containing a geodetic representation for the same location”** and **“constructs a PIDF-LO with the geodetic location”**; ReverseGeocode symmetrically returns the civic form. Each direction returns the converted form and nothing else. The matched civic address is NOT echoed. RFC 5491 describes what a PIDF-LO may contain; it has no opinion on what a Geocode response should contain, and **“the format permits it”** is not **“the standard asks for it”** (§1.2.1). Consequence: a fuzzy match is indistinguishable from an exact match on this interface. This is the deficiency, carried faithfully.*

***✔ Settled — the indistinguishability claim is about the GeodeticData object, not the whole response.*** *RFC 7459 confidence is emitted inside the PIDF-LO payload on this interface as well as the enhanced one (§7.4, decision 65). That does not mint i3 vocabulary: confidence is an IETF element defined for PIDF-LO generally, carried within the location object, and `GeodeticData` gains no property — it still carries exactly one `pidfLoGeo` string and nothing else. The claim above is therefore precise as stated about the response object, and narrower than it first reads about the response as a whole: `matchScore`, `locationType`, rank, and the existence of other candidates remain wholly unexpressible here, which is the deficiency §16 records. What a consumer can recover on the strict interface is a coarse confidence, and nothing about why.*

***✔ Settled (Session 14, decision 116):** `GeodeticData` still carries exactly one `pidfLoGeo`, unchanged — only its wire encoding is corrected, from a JSON object to real `application/xml` with `pidfLoGeo` as a CDATA-carrying child element. See §3.9.1's correction note for the reasoning.*

***✔ Settled (Session 3):** The object is named GeodeticData per the normative YAML; the published text’s “GeodecticData” is a typo. Serialisation and field casing per §3.9.1.*

## 8.2 The i3-improved Interface

***✔ Settled (Session 1):** Returns the full matched PIDF-LO record per candidate — civic and geodetic together — not a bare geometry. A client that queried **“101 Main St”** and matched **“101 Mayne St”** can see the substitution by diffing the returned record against its query. Same for ReverseGeocode.*

## 8.3 PIDF-LO Construction

***✔ Settled (Session 1):*** \*\<**method**\>\*\* (RFC 4119 §2.2.3) is not emitted, on either interface. The element describes how the location information was derived or discovered, and RFC 4119 requires implementations to limit its values to the IANA registry — pre-populated with GPS, A-GPS, Manual, DHCP, Triangulation, Cell, and 802.11, all device-positioning methods. The GCS does not observe how the location was derived; it matches a GIS record whose own provenance is frequently unavailable and, where available, does not map to any registered token. Emitting one would be a guess presented as metadata. The provenance concept has a legitimate home in STA-006.3’s Placement Method ID (§6.1 registry), which is data passed through rather than vocabulary minted, and is carried on the i3-improved interface (§3.2).\*

***✔ Settled (Session 3) — the PIDF envelope.***\* i3 §4.5 is silent on the envelope, but the IETF solved the same problem for the LIS, which also produces PIDF-LOs without a verified presentity. RFC 5985 §6.6: identity parameters are omitted or carry unlinked pseudonyms, and the LIS SHOULD generate a unique, unlinked presentity URI for the mandatory entity attribute; RFC 6753 §6.2 hardens this to MUST for location servers absent Rule Maker policy. The GCS convention follows that precedent with one refinement available to it that a LIS lacks: the GCS receives a PIDF-LO whose entity attribute is already populated. Where the input carries an entity attribute, it is echoed onto the response — the location still belongs to that presentity; the GCS transformed its representation, not its ownership. Where the input entity is absent or unusable, the GCS generates a HELD-style unlinked pseudonym URI, exactly as a LIS does. retransmission-allowed is passed through from the input unchanged: the GCS never acts as a Rule Maker, and i3 §3.1 notes that NG9-1-1 FEs normally ignore retransmission-allowed within the ESInet for emergency calls in any case. i3’s silence where HELD had to speak is a §16 row.\*

***✔ Settled (Session 14, decision 115):** The embedded PIDF-LO is indented (2-space, one element per line), and so is the JSON wrapper around it (§3.9.1, §8.1, §12.1) — on all four resources, on every status code that carries a body. Neither is a wire-format departure: i3 has no opinion on incidental whitespace, only on fields and status codes (§1.2.1), so a JSON parser and an XML parser see exactly the same document either way. Fixed a genuine bug in passing: `usage-rules`, when the input carried one, is a deep copy of an element parsed out of the CALLER's request and therefore still carries that request's own whitespace — enough to make lxml's naive `pretty_print` silently give up reformatting the `<gp:geopriv>` subtree around it. `etree.indent()` now runs first and recomputes every structural whitespace node from scratch, which does not depend on which payload elements were freshly built and which were copied in. See decision 115 in Appendix B for the full reasoning and where it lives in code.*

## 8.4 Status Code Selection

***✔ Settled (Session 3):** The set is closed to the five in §2.1, now fully assigned: 200 on a derived result; 307 with Location header where GCS_REFERRAL_URI is configured and conversion fails (§3.6.2); 454 for schema validation failure and residual internal errors, on both operations, with a body reason (§4.1); 468 where the request was valid but no result is derivable, including ambiguity beyond tolerance (§6.3); 469 not emitted (§2.1).*

***✔ Settled (Session 14, decision 114):** 468 carries a body too, as of this session — a fixed, non-distinguishing reason string identical on every 468 regardless of which §6.4 path produced it, closing the shape gap against 454 (which has carried a caller-specific reason since decision 36) without reopening §6.4's "the paths are not distinguished" invariant. See decision 114 for the two options weighed and why the fixed string won over exposing the path-specific reason text.*

# 9. ReverseGeocode — Stage 0: Request Admission

***✔ Settled (Session 4):** All eight RFC 5491 §5 GeoShape forms are accepted on input — Point, Polygon, Circle, Ellipse, ArcBand, Sphere, Ellipsoid, and Prism. i3 §4.5 says only that the request contains “a geodetic representation” and cites RFC 4119, 5139, and 5491 without narrowing the shape vocabulary, so accepting only a Point would be a restriction i3 does not impose — which decision 2’s corollary forbids as firmly as it forbids adding capability.*

*A single search origin is derived from whatever shape arrives, using the §7.5 centroid convention already settled: the footprint centroid for X/Y and the vertical midpoint for Z. A Point supplies itself. This generalises without shape-specific code paths — a Circle yields its centre, a Polygon its footprint centroid, a Prism its footprint centroid at mid-height — and hands §10 exactly one origin regardless of input form. Admission otherwise mirrors §4: body and Content-Type per §3.9.1, schema validation per §4.1 returning 454, and the §4.2 first-location rule applies unchanged where the input PIDF-LO carries more than one location.*

*The input’s extent is not discarded. It is carried forward into §10.3 as the containment test and into §10.6 as the damping term on the spatial-fit score, so that a query expressing two kilometres of uncertainty does not score as though it expressed two metres.*

***⚠ Note — this revises §7.4’s input-uncertainty rule, in scope.***\* §7.4 (Session 2) states that the GCS does not evaluate or reason about the uncertainty or confidence of its input. That rule stands on the Geocode side, where an input’s uncertainty is metadata attached to a civic address and properly ignored. It cannot stand here: on the reverse side the input geometry is the query itself, so its extent is not metadata about the question but the substance of it. The rule is therefore scoped to Geocode rather than silently contradicted.\*

# 10. ReverseGeocode — Nearest Feature Search

***⚠️ Recommended Best Practice — No Current Standards Guidance:** i3 §4.5 refers to **“the ‘nearest’ point algorithm employed”** as though it were a defined thing. It is not defined in i3, in STA-006.3, or in any referenced RFC. The entire content of this chapter is a recommended best practice.*

## 10.1 Search Structure — One Pass

***✔ Settled (Session 4):** One pass. A single proximity search is issued from the §9 origin out to GCS_REVERSE_SEARCH_RADIUS_M, producing one candidate set that is then ordered by the rules in §10.3 through §10.5. There is no separate containment pass and no separate 3D pass; both are expressed as terms in the ordering rather than as gates in front of it. This revises §3.7.2 (decision 18) and follows the same reasoning decision 28 applied to scoring: where a distinction can be expressed as a position on one continuous ordering, it should not be reimplemented as a second code path that can readmit what the first rejected.*

## 10.2 Search Radius

***✔ Settled (Session 4):** A maximum search distance is mandatory — without one, a point in open water reverse-geocodes to whatever unfortunate address is nearest and returns 200. The limit is a single configurable value, GCS_REVERSE_SEARCH_RADIUS_M, applying uniformly to all layers and to both the horizontal and (where present) vertical components of the search. Where no candidate falls within it, the response is 468 (§12.3). The default is deferred to implementation, as with the other configurable distances.*

***✔ Settled (Session 11, decision 96 — resolves Appendix C.4 Q4):** The uniform radius's vertical component never binds in practice, and this is a stated consequence rather than an accident. At any horizontally useful value — the proposed 250 m, or 50 m in a dense urban deployment — the vertical band the same figure nominally constrains spans an 80-storey (respectively 16-floor) structure, so no plausible input Z is ever excluded by it. This is decision 39's recorded surrender (a single pass gives up a separate radius per pass) showing up in practice, and it is accepted: reintroducing a separate vertical bound would need a tolerance constant §10.5 has twice declined for want of a defensible default (decision 60), against a condition that is unreachable anyway while no provisioned class carries a vertical extent. Revisit if a volumetric feature class makes the vertical axis load-bearing.*

***On units.***\* The value is metres — true geodesic distance on the WGS84 spheroid — not decimal degrees, notwithstanding that EPSG:4326’s native units are degrees. A degree is not a distance: a degree of latitude is approximately 111 km everywhere, while a degree of longitude is that figure scaled by the cosine of latitude, which across the US-only scope of this document ranges from roughly 100 km at the Florida Keys to 76 km at Bismarck to 36 km on the North Slope. A radius expressed in degrees is therefore an ellipse that stretches east-west as latitude increases, and the same configured value means materially different things in different jurisdictions. Worse, it would corrupt §10.5: ranking candidates by degree-space distance at Bismarck’s latitude would require an east-west neighbour to be roughly 1.45 times closer in reality than a north-south one to rank ahead of it, letting the CRS’s units silently overrule the algorithm. Fidelity to EPSG:4326 is properly satisfied at the storage and interchange layer — data remains in 4326 and coordinates serialise as degrees — and a degree-space bounding box remains available as an internal spatial-index pre-filter ahead of exact distance computation. That is an implementation optimisation, not a configured unit. With this settled, the document uses metres for every horizontal quantity, and GCS_RCL_ENDPOINT_MARGIN_M and GCS_RCL_OFFSET_M cease to look like exceptions to a degrees-based rule.\*

## 10.3 Candidate Ordering — Containment, Tier, Distance

***✔ Settled (Session 4):** Ordering is lexicographic, not arithmetic. Candidates are ordered by containment first, then by precision tier (§7.4’s locationType), then by distance from the origin. Nothing is blended into a single number, so this does not reintroduce the mixed-axis problem the three-field model was built to avoid: distance is a tiebreaker within a tier, never a competitor to it.*

***Containment.***\* Where the input shape has extent, any feature falling within that shape is contained, and contained candidates order ahead of uncontained ones. Containment is a flag carried on the candidate, not a gate in front of the search — it occupies the top of the same continuous ordering rather than forming a separate pass, exactly as exact match occupies the top of the §6.5 similarity scale under decision 28. This applies to address points, address points with Z, and prospectively to building footprints, room footprints, and volumes as those feature classes become available. The flag surfaces on the enhanced interface; on the i3 interface it is invisible, as everything else is.\*

***Tier, and what governs when containment cannot fire.***\* A Point input has no area and therefore contains nothing, so the commonest input in the system never reaches the containment rule. Tier precedence is accordingly scoped to contained candidates: among candidates inside the input shape, a higher precision tier wins regardless of distance, so a contained address point beats a nearer road. Where nothing is contained — including every Point input — the ordering is nearest-by-distance regardless of layer. A point 200 m from an address point and 5 m from a centerline is on the road, and the honest answer is the segment’s interpolated address, not the distant structure. Layer precedence is thus a consequence of containment rather than an independent rule: containment is what licenses preferring precision, and absent it, proximity is all that is known.\*

***Ordered tier and reported tier can differ, for centerlines.***\* A RoadCenterLine candidate's true precision tier is not knowable at search time: §11.2 determines it by projecting the origin, selecting the side, and reading that side's address range, and a segment asserting no range on the projected side yields a street-level address rather than an interpolated one. Resolving that during the search would collapse §11.2's front half into §10 and contradict §10.1's single pass. Centerline candidates are therefore tiered uniformly as INTERPOLATED_POINT for ordering purposes, and the tier reported on the answer is whatever §11.2 determines — which may be lower. The consequence, stated rather than concealed: within a contained candidate group, a segment that turns out to be rangeless may have outranked an interpolable one. Tier participates only among contained candidates, so no Point input is affected (decision 59).\*

## 10.4 Tie-Breaking

***✔ Settled (Session 4):** Ties are resolved by continuing down the lexicographic sequence of §10.3, which resolves the overwhelming majority of them: two candidates equidistant from the origin are separated by containment or tier before distance is ever consulted. Where candidates remain genuinely indistinguishable — same containment state, same tier, same distance to the precision of the computation — the tie is broken deterministically on the matched feature’s stable identifier, ascending. This is arbitrary, and deliberately so: an arbitrary rule applied identically by every implementation satisfies the requirement that two GCS instances provisioned from the same SI data return identical results, which is the requirement that makes this document worth writing. §3.7.3’s minimise-maximum-error principle does not apply here — unlike the Geocode side, there is no averaging a set of civic addresses, so one candidate must be elected rather than synthesised.*

## 10.5 Distance Metric

***✔ Settled (Session 4) — horizontal.***\* Distance is true geodesic distance on the WGS84 spheroid, in metres (§10.2), measured from the §9 origin to the matched feature’s geometry as that geometry actually exists — no synthetic adjustment is applied to any layer before comparison.\*

*This carries a known and deliberate bias, stated rather than corrected. Distance to an SSAP is distance to a notional point whose placement convention varies per record; distance to an RCL is perpendicular distance to a centerline, and a road is not its centerline. Someone standing at the curb of a twelve-metre road is six metres from the centerline but zero metres from the road, so the comparison systematically favours address points by roughly half a carriageway width — in precisely the marginal cases where §10.3’s nearest-by-distance rule decides the answer. The alternative considered was subtracting a configurable nominal half-width from RCL distances before comparison, which was rejected: it would require inventing a road width that STA-006.3 does not model, and the bias favours the more precise answer in any case. The honest disclosure is that raw distances travel on the enhanced interface, so a caller can see how close the call was.*

*Direct reading of the STA-006.3 §6.1 Placement Method registry sharpens this further. Its values — Structure, Site, Parcel, Geocoding, ExteriorAccess, InteriorAccess, InteriorCentroid, PropertyAccess, Unknown — describe placements that sit at very different distances from the same building: a Parcel centroid, a Structure point, and a PropertyAccess driveway are not interchangeable measurements. The noise in the SSAP-versus-RCL comparison is therefore larger than a raw distance suggests. This argues for surfacing Placement Method on every enhanced candidate so the caller can weigh it, not for adjusting the rule; the GCS does not second-guess the placement the SI recorded.*

***✔ Settled (Session 4) — vertical.***\* Where the input carries a Z, vertical participation is lexicographic, not Euclidean. A naive three-dimensional Euclidean distance treats a metre as a metre in both axes, which badly understates vertical error: three metres up is a different floor and a different dwelling, while three metres sideways is nothing. Candidates whose vertical extent contains the input’s Z are therefore ordered ahead of those whose extent does not, and horizontal distance orders candidates within a band. The alternative considered was a weighted metric of the form sqrt(h² + (k·v)²) with k configurable; it was rejected because no defensible default for k can be supplied from data that barely exists yet — the same objection that ruled out a nominal carriageway half-width above. Where the input carries no Z the ordering degrades to pure horizontal distance, which is the normal path today (§3.7.2).\*

***The band is inert on every currently provisioned feature class.***\* Ordering by whether a candidate's vertical *extent* contains the input's Z presumes a candidate that has an extent, and none does: SiteStructureAddressPoint is the only 3D-capable provisioned class and carries a point Z — a slot, not a range — while no volumetric class is provisioned at all (§7.4 as corrected). RoadCenterLine is not declared 3D-capable. The band can therefore fire only on exact equality between the input's Z and a candidate's, which the provisioned data does not produce, so the vertical term is inert and the ordering is pure horizontal distance in every real case. This is stated rather than left to be discovered: §3.7.2 predicts the outcome, but the rule above reads as though the band does work, and an implementer will otherwise look for the case that exercises it. The band is retained as structure for the volumetric classes §7.4 anticipates. Widening it with a vertical tolerance was rejected for the same reason the weighted metric was — it needs a constant no data available today can justify (decision 60).\*

## 10.6 Spatial-Fit Scoring

***✔ Settled (Session 4):** The §7.4 three-field quality model carries over to the reverse direction unchanged in shape, with one slot refilled. locationType and confidence work exactly as on the forward side: the tier follows from the matched geometry class, and confidence remains matchScore scaled to the tier ceiling. But matchScore on the forward side is per-field similarity against a query address, and a reverse request has no query address to compare against — there is nothing to decompose into street, HNO, and community.*

*The slot is therefore filled by a spatial-fit score occupying the same field, the same range, and the same per-component breakdown shape on the enhanced interface, with different components: distance from the origin normalised against GCS_REVERSE_SEARCH_RADIUS_M, containment sitting at the top of that scale exactly as exact match does under decision 28, and a damping term for the extent of the input shape so that a two-hundred-metre circle does not score as a point does. A candidate whose Placement Method is Geocoding is damped additionally: an address point whose own position was derived by geocoding, then reverse-geocoded back to an address, is a round trip through two approximations, and the score should say so.*

***What extent damps, and what it does not.***\* Extent damps the score only; it does not weaken containment within the ordering. The two mechanisms are separable because §10.3 orders lexicographically, so the score can honestly report “we found something contained, but your query was vague” without disturbing rank order. Weakening containment itself was considered and rejected on the merits. Containment only affects the ordering when it splits the candidate set: for a two-kilometre circle containing forty address points, every candidate is contained, all forty sit at the same tier, and they order by distance from the centroid — which is the order pure proximity would have produced anyway, so weakening containment there changes no answer. The only cases it would change are those where some candidates are inside the shape and others outside, and there preferring the contained candidate is correct even for a large shape: a point 1.9 km from the centroid but inside the caller’s stated circle is a better answer than one 2.1 km away and outside it, because the caller has asserted the target lies within that circle. Weakening containment would thus degrade exactly the cases where containment carries information and do nothing in the rest — and would require a threshold constant for which no defensible default exists. The vagueness of a large query is an epistemic fact and the score is the field built to report epistemic facts; the ordering reports geometry.\*

***✔ Settled (Session 5, decision 66) — one radius, one new constant.***\* The distance and extent-damping terms both reuse GCS_REVERSE_SEARCH_RADIUS_M (§10.2) as their scale rather than introducing a second constant: distance is normalized against it directly, and extent damping is `radius_m / (radius_m + extent_m)`, which is 1 for a Point (zero extent) and falls toward 0 as the query shape's extent grows relative to the search radius. The Geocoding-placement damping is the one component that could not avoid a new constant — `GCS_GEOCODED_PLACEMENT_PENALTY` — whose value is settled by decision 83 below.*

***✔ Settled (decision 83) — `GCS_GEOCODED_PLACEMENT_PENALTY` stays 0.9, as a deliberate editorial default rather than an untuned strawman, and is not sweepable.** The constant is retained at 0.9 and reclassified: it is a settled, deployment-tunable value, not an open tuning question. Two facts fix this. First, the penalty cannot change any answer the service gives. §10.3 orders lexicographically on containment, then tier, then distance; spatial fit is not a term in the ordering, exactly as the extent-damping discussion above already establishes for its sibling component. The penalty therefore moves one reported number on the enhanced interface (and confidence, which is that number scaled to the tier ceiling) and moves nothing else — it never reorders candidates, never admits or excludes one, and never converts a 200 into a 468. Second, and consequently, there is no ground truth to sweep it against. A sweep of the kind decisions 79 and 80 ran needs a labeled outcome the constant can be scored against — wrong-pair separation, threshold clearance — and no such outcome exists here: STA-006.3's registry records *that* a placement was derived by geocoding, never the error magnitude of that derivation, which is a property of whatever geocoder the SI ran against whatever reference data it held. A future session should not re-open this looking for a sweep; the sweep cannot be built, and its absence is not an oversight.*

*What 0.9 means, stated so it is not mistaken for measurement: a Geocoding-placement candidate reports roughly a tenth less spatial fit than an otherwise identical candidate placed by survey, structure, or parcel — visible in the number, deliberately short of implying a known error magnitude. It prices the circularity §3.3's drafting note identifies against the STA-006.3 registry: an address point whose own position was derived by geocoding, then reverse-geocoded back to an address, is a round trip through two approximations, and one of them is this service's own forward operation. Because the honest value depends on the quality of the SI's geocoding rather than on anything the GCS can observe, the environment binding is the answer rather than a better default — a deployment that knows its geocoded placements are poor lowers it, one that knows they are good raises it toward 1.0, and the shipped default assumes neither. The constant is already bound through `runtime_state` at registration time, so nothing further is required of the implementation.*

# 11. ReverseGeocode — Civic Derivation

## 11.1 SSAP-Derived Civic Address

***✔ Settled (Session 4):** The civic address is read directly off the matched SSAP record’s fields. No derivation, inference, or synthesis occurs at this rung: the record already holds a civic address, and the GCS reports it.*

## 11.2 RCL-Derived Civic Address

***✔ Settled (Session 4) — the house number is synthesised, not withheld.***\* The origin is projected onto the segment, the side of projection is determined, side-specific attribution is selected (§11.3), and the house number is produced by inverting §7.2’s interpolation: the proportional position along the segment maps back into the segment’s address range. The inverse almost never lands on an integer, and the number it produces need not exist — a projection at 47.3% of a 100–200 range yields 147.3, which must be rounded, and rounded to the parity of the side on which the origin fell, so 147 or 149 but never 148. The result is a syntactically valid civic address that may correspond to no structure, no parcel, and no record anywhere in the provisioned data; an LVF handed that same address would likely fail it.\*

*The alternative considered was omitting HNO and returning a street-level civic address only — the reverse-side analogue of rung 3. It was rejected. The objection to synthesis was that a computed guess would be presented as a civic address with no way to mark it as computed, which is the same objection that kept silent under decision 12. That objection no longer holds: a synthesised number now arrives tagged INTERPOLATED_POINT with a confidence ceiling of 75 and a raw distance, so the enhanced interface states plainly that the value is derived. The three-field model exists precisely so that a computed answer can be labelled rather than withheld. And withholding is worse in practice — a coordinate on a rural highway is the case where reverse geocoding most earns its keep, and “Highway 83, Burleigh County” is nearly useless to a dispatcher where “approximately 1470 Highway 83” is actionable. Degrading every consumer to guard against a disclosure deficiency that exists on only one interface, and is already recorded in §16, is the wrong trade.*

***Two guardrails.***\* The synthesised number is clamped to the segment’s asserted range, so it can never fall outside what the data claims; and it is forced to the parity of the side on which the origin fell. The inversion walks the same endpoint-margin-shortened path that §7.2’s forward interpolation uses (GCS_RCL_ENDPOINT_MARGIN_M) — if the two directions traverse different paths, §14.1’s round-trip consistency breaks by construction rather than by data quality.\*

***The gap this exposes is deeper than i3.***\* RFC 5139 gives HNO no way to mark itself approximate. A validated address point and an inversely-interpolated guess serialise identically on the civic side of a PIDF-LO, so the strict i3 response cannot distinguish them even in principle — this is a limitation of the civic schema itself, not merely of i3’s silence. §16 row.\*

## 11.3 Administrative Element Sourcing

***✔ Settled (Session 4):** The administrative elements above the street — state, county, municipality, community, and the remainder of the CLDXF-US hierarchy — are taken from the matched record’s own fields. The provisioned boundary layers are not consulted for a matched SSAP.*

*Two provisioned sources can disagree here. The matched record carries its own civic attribution; the boundary layers carry polygons the origin could be tested against, and point-in-polygon is how the ECRF decides jurisdiction, which gives it a real claim to authority. The decision follows §7.1’s precedent — declare a precedence chain, do not consult the lower source, and do not report a discrepancy — for a reason specific to this document: §14’s round-trip requirement. A forward geocode matched the query against the record’s own fields, so reversing must hand those same fields back, or a coordinate that geocoded from an address will not reverse to it. Records whose attribution disagrees with the polygon containing them are a GIS data-quality problem for the SI to resolve, not something the GCS silently corrects on the wire.*

***Side-specific attribution for RCL matches.***\* Centerline segments carry left and right attribution separately. The side on which the origin projected — the same side already determined by §7.3’s setback convention and by §11.2’s parity rule — selects the attribute set. This applies to the administrative elements as well as to the street name fields.\*

***Why this direction projects rather than reading parity (decision 87).***\* §7.2 establishes that the forward direction resolves side from the query's Add_Number parity, one rule consulted at both scoring and position derivation. This direction cannot use it: a reverse request supplies an origin point and no house number, so there is no parity to read. Projection is not a competing policy but the only mechanism the available input supports, and the resulting side then feeds §11.2's synthesis, where parity re-enters — as the constraint the synthesised number is forced to, having been derived from the side rather than deriving it. The two directions therefore run parity and geometry in opposite order, which is a consequence of what each is given rather than an inconsistency.\*

## 11.4 Element Population and Omission

***✔ Settled (Session 4):** An element with no source is omitted, not emitted empty. RFC 5139 gives an empty element no defined meaning, so emitting one asserts nothing while inviting a consumer to read it as an assertion.*

*The harder case is a matched record that is missing something structurally necessary. STA-006.3 permits sparse attribution, so a valid SSAP may carry no municipality, or no street type where local convention omits it. The GCS then constructs a civic address that is well-formed XML but incomplete as an address — and an LVF handed that same address would likely fail it, which means the GCS can emit an address its sibling service would reject, from data both were provisioned with.*

*Such records are returned anyway. This is consistent with §11.3: the GCS reports what the authoritative record says, and sparseness is the SI’s data-quality problem rather than the GCS’s to repair. A partial address still narrows a dispatch. The alternative — treating a record too sparse to form a usable address as no answer, falling through to the next candidate and returning 468 if none qualifies — was rejected because it would have the GCS invent a completeness standard i3 never gave it, and silently skip records the SI considers valid. The resulting divergence between LVF validity and GCS output is a §16 row: i3 states no completeness contract between the two services, so they can legitimately disagree about the same record.*

# 12. ReverseGeocode — Response Assembly

## 12.1 The i3 Interface — CivicAddress

***✔ Settled (Session 4):** Per the normative YAML read in Session 3, the response object is CivicAddress carrying a single pidfLoAddress string — the published §4.5 text’s “PIDFLOAddress” is not the schema’s casing. Serialisation follows §3.9.1. The object carries one civic address and nothing else: no rank, no score, no distance, no containment flag, no Placement Method, and no indication that a house number was interpolated rather than read. Everything §10 and §11 computed is discarded at this boundary, with the single exception of RFC 7459 confidence, which travels inside the PIDF-LO payload rather than as a property of `CivicAddress` (§7.4, decision 65). That is the deficiency, carried faithfully.*

***✔ Settled (Session 14, decision 116):** `CivicAddress` still carries exactly one `pidfLoAddress`, unchanged — only its wire encoding is corrected, from a JSON object to real `application/xml` with `pidfLoAddress` as a CDATA-carrying child element. See §3.9.1's correction note for the reasoning.*

## 12.2 The i3-improved Interface

***✔ Settled (Session 4):** POST …/ReverseGeocodeEnhanced (§3.9.2) returns the ordered candidate list from §10.3, each candidate carrying the full matched PIDF-LO civic record, the three-field quality model with spatial-fit in the matchScore slot (§10.6), the containment flag, the raw geodesic distance from the origin, the matched feature’s Placement Method where present, and the §10.31 match type token.*

***Match type mapping.***\* Direct reading of the i3 §10.31 registry gives seven tokens — Address, RoadCenterline, PoliticalBoundary, MsagCommunity, CoverageRegion, Hybrid, and Other — and only two are usable here. Address is emitted for every point-tier match; RoadCenterline for every road-tier match. Hybrid is not emitted, since one candidate matches exactly one feature. CoverageRegion is LoST-specific and out of scope per §3.1. The registry is materially coarser than this document’s locationType: RoadCenterline covers both a street-level match and a house number interpolated from a range without distinguishing them, and no token exists for an interior or volumetric match at all. Both fields therefore travel — the registry token for consumers that speak i3 vocabulary, locationType for those that need the distinction i3 cannot express. This is the substance of the existing §16 row on match-quality vocabulary, now confirmed against the registry rather than inferred.\*

## 12.3 Status Code Selection

***✔ Settled (Session 4):** Mirrors §8.4 with the reverse-side triggers. 200 where a candidate was derived. 307 with the referral URI in the Location header where GCS_REFERRAL_URI is configured and no candidate was derived (§3.6.2, §13). 454 for schema validation failure and residual internal errors, with a human-readable body reason (§4.1) — noting that the normative YAML omits 454 from /ReverseGeocode entirely, an asymmetry this document declines to follow and records in §16. 468 where the request was valid but no candidate fell within GCS_REVERSE_SEARCH_RADIUS_M, carrying the same fixed §8.4/decision 114 reason body as the forward side. 469 is not emitted (§2.1).*

# 13. Referral

The GCS neither recurses nor redirects on its own initiative (§3.1). i3 §4.5 provides no recursion mechanism: there is no recursive flag by which a client could request it, and no response field capable of carrying a path — nothing analogous to LoST’s / (RFC 5222 §8.5). The absence of an audit trail is the tell; recursion without one is an omission rather than a design.

The asymmetry with i3’s LoST-based elements is worth stating. A LoST server can absorb a hop — recurse to its parent and return the result as its own — and the client never knows. A GCS structurally cannot. Every referral is visible to the client, and the client must implement referral-chasing or the referral is dead letter. The GCS “tree” is not a tree the service walks; it is a chain the client walks, if it chooses to.

Referral behaviour is specified in §3.6.2. 307 is not emitted (§2.1).

# 14. Cross-Element and Round-Trip Consistency

***✔ Settled (Session 1):** The claim is scoped to address-level results. An address that geocodes at rung 1 or rung 2 (§3.3) SHOULD validate as conforming against an LVF provisioned from the same SI data, and a civic address produced by ReverseGeocode SHOULD validate as conforming. A rung-3 result has no LVF analog and is therefore not comparable rather than inconsistent. Fuzzy candidates (§6.5) are excluded from the claim by construction.*

If this holds, the two functional elements cannot disagree about what exists in the jurisdiction — which is precisely the failure mode the standards stack is silently vulnerable to, since nothing in i3 requires GCS and LVF answers to be consistent despite both being provisioned from the same SI. Consider a shared cross-FE regression corpus.

## 14.1 Round-Trip Consistency

***✔ Settled (Session 4):** The round trip MUST hold for any address with an SSAP record, and MAY fail for rung-2 and rung-3 results. It is not guaranteeable in general — i3 says as much in noting that reverse geocoding is typically less accurate — but the conditions under which it does hold are testable and make an excellent regression suite.*

*Two decisions this session were made specifically to keep the rung-1 guarantee true rather than aspirational. §11.3 sources administrative elements from the matched record’s own fields rather than from boundary polygons, because a forward geocode matched against those fields and reversing against a different source would break the trip on every record whose attribution disagrees with the polygon containing it. And §11.2’s inverse interpolation walks the same endpoint-margin-shortened path as §7.2’s forward interpolation; if the two directions traversed different paths, the rung-2 trip would fail by construction rather than by data quality, which would make the MAY meaningless as a diagnostic.*

# 15. Complete Algorithm Pseudologic

The following pseudologic summarizes the complete algorithm for implementation reference. It is a **summary of decisions made elsewhere in this document and makes none of its own**; where this section and a numbered section disagree, the numbered section governs and the discrepancy is a defect in this one. Every step cites the section that settles it, so a reader who needs the reasoning rather than the sequence knows where to go.

Two structural facts shape both listings. There is **one algorithm per direction**, not two: the interface split of §2.2 is a serialisation concern that takes effect only at response assembly, so the strict-i3 and i3-improved paths are identical until the final step and diverge only in what they are permitted to say. And **`populated()` means what the caller asserted**, not what the schema permits — an element the request omitted is excluded from scoring's numerator and denominator alike (§6.5, decision 66) rather than scored as a mismatch.

## 15.1 Geocode

```
GEOCODE(request):

  ─── Stage 0: Request Admission (§4) ────────────────────────────────
  1. Validate body, Content-Type, and schema — full XSD set plus the
     RFC 3863 / RFC 4119 PIDF envelope schemas.            (§4.1)
     FAIL -> 454, human-readable reason in body.
  2. Elect ONE location by RFC 5491 Rule #8 typed precedence:
     first <location-info> with a location, else first <geopriv>,
     tuples last.                                          (§4.2)
     Locations after the elected one are discarded — silently on the
     i3 interface as i3 requires; the enhanced interface reports the
     count and that only the elected location was converted.
  3. The elected location must carry a civic chunk. If it does not,
     return 468 — do NOT walk past it seeking a better-typed
     location.                                             (§4.2, §4.3)

  ─── Structural Conformance (§5) ────────────────────────────────────
  4. No Gate 1 exists. A civic address with no Add_Number is admitted
     and answered at rung 3. An Add_Number with no address-level match
     falls back to rung 3 rather than failing. Precision degradation is
     carried by uncertainty (§7.4), never by rejection.     (§5)

  ─── Stage 1: Candidate Identification (§6) ─────────────────────────
  5. Filter every layer to temporally-valid records.        (§3.4)
     There is NO progressive filter: every temporally-valid record is
     scored on every request. Nothing is discarded unseen.  (§6.2, dec 61)

  6. SSAP pass (rung 1):
     a. Apply the identity gates — these run BEFORE scoring and are
        the only fields that gate candidacy:                (§6.2)
          - Add_Number: where the query supplies one, the record's
            must match exactly.                             (dec 69)
          - UnitValue: where the query supplies one AND the record
            carries one, they must match exactly (UnitPreTyp is not
            part of the gate). A record carrying no unit is NOT
            gated out.                                      (dec 75)
        No other field gates candidacy. A1, Country, Community,
        St_Dir, St_Type and A2 are weighted terms only.     (dec 80, 82)
     b. Score each surviving record (§6.5) -> SCORE_RECORD below.
     c. Disqualify (matchScore forced to 0, breakdown still reported)
        any candidate failing street-name qualification.     (dec 71, 73)

  7. Evaluate whether the RCL pass is needed:               (§6.1, dec 70)
     If the best rung-1 candidate's blended confidence is at or above
     the INTERPOLATED_POINT ceiling (75), STOP — no road answer can
     beat it, and the well-provisioned common case never touches RCL.
     Otherwise run the RCL pass and compare each rung's BEST candidate
     on blended confidence. Search order is not acceptance order.
     Ties go to the more precise rung.

  8. RCL pass (rungs 2/3): score centerline records (§6.5). Add_Number
     has no similarity term here — §7.2's range/parity containment
     resolves house number as a correctness test, not a comparison.
     Side-specific attribution is selected before scoring commits, so
     the cap, the reported score, the weight and the field lookup all
     commit to the same side.                               (§7.2, dec 80)

  9. Drop candidates below GCS_MIN_MATCH_SCORE entirely.    (§7.4)

  10. Resolve ambiguity among survivors:                    (§6.3)
      - Agree horizontally, differ vertically -> merge unconditionally,
        vertical uncertainty spans the extent.              (§3.7.3)
      - Differ horizontally beyond tolerance -> 468. Two "State Street"
        matches forty miles apart are not a location.
      - Legitimate multi-point answer (generic query, one parcel, e.g.
        farmhouse + machine shed): enhanced interface returns both
        ranked; the i3 interface returns the centroid with uncertainty
        sized to their extent (§3.7.3 minimise-maximum-error).
  11. Zero candidates by ANY path -> 468. No coverage test
      distinguishes the paths.                              (§6.4, §3.6.2)

  ─── Stage 2: Position Derivation (§7) ──────────────────────────────
  12. Rung 1 (SSAP): read the position off the record. Z by precedence
      chain — geometry Z, else Altitude, else Elevation (all WGS84/HAE,
      so no datum mixing). The chain resolves silently.     (§7.1, dec 51/55)
      locationType = ADDRESS_POINT, ceiling 80.

  13. Rung 2 (RCL, HNO within an asserted range):           (§7.2)
      a. Trim GCS_RCL_ENDPOINT_MARGIN_M off each end of the segment's
         usable geometry; the full range compresses to fit.
      b. Interpolate proportionally to address number along the
         segment's ACTUAL vertex geometry — bends and curves — not a
         straight chord between endpoints.
      c. Zero-length range (From == To): the fraction is 0/0. Return
         the segment MIDPOINT on the matched side. The endpoint margin
         does not participate.                              (dec, Session 5)
      d. Parity_L/R selects the side and forces reverse-side synthesis
         parity — it NEVER blocks a forward match. Where parity
         contradicts the range it labels, the asserted range governs.
      e. Apply the GCS_RCL_OFFSET_M perpendicular setback on the
         matched side. The result MUST NOT sit on the centerline.  (§7.3)
      locationType = INTERPOLATED_POINT, ceiling 75.

  14. Rung 3 (street-level, no HNO or no range on the matched side):
      return the segment's ACTUAL LINE geometry. Do not collapse it to
      a point and do not synthesise a Circle or Ellipse — the line is
      the honest representation of what is known.           (§7.4)
      The line is 2D, EPSG:4326: RoadCenterLine is not a declared
      3D-capable class, so its per-vertex Z is an export artifact and
      is dropped, same as rung 2. Emit srsName explicitly. (dec 85)
      locationType = STREET_SEGMENT, ceiling 50.

  15. Compute the three-field quality model for every candidate: (§7.4)
        matchScore   = §6.5 output, with per-field breakdown
        locationType = SPACE_3D > FOOTPRINT_2D > ADDRESS_POINT >
                       INTERPOLATED_POINT > STREET_SEGMENT
                       (keyed to matched GEOMETRY CLASS, not rung number)
        confidence   = matchScore scaled to that tier's ceiling
                       (100 / 90 / 80 / 75 / 50)
      Rank by blended confidence, so a shaky point match can rank below
      a solid street match — for 9-1-1, precision that cannot be
      trusted sends a dispatcher to the wrong building. Both primary
      axes travel so a consumer may re-rank on either.

  ─── Stage 3: Response Assembly (§8) ────────────────────────────────
  16. i3 interface:      200, GeodeticData carrying one pidfLoGeo.
      Everything else computed above is discarded at this boundary,
      except RFC 7459 confidence which travels inside the PIDF-LO.
      Coordinate order is lat/lon per RFC 5491 / GML.        (§8.1, §8.3)
  17. i3-improved:       200, ranked candidate list; per candidate the
      full matched PIDF-LO record, the three-field model with per-field
      breakdown, tie disclosure, multi-location disclosure, the §10.31
      match type token, and Placement Method where present. (§8.2)
  18. Status codes: 200 derived; 307 + Location where GCS_REFERRAL_URI
      is set and nothing was derived; 454 schema/internal; 468 valid
      request, no candidate.                                (§8.4, §13)


SCORE_RECORD(query, record):                                (§6.5)

  matchScore is a weighted average over the elements the QUERY
  populated, renormalized by the weight actually used.       (dec 66)

  Per-element weight = base editorial weight
                     x discriminative factor MEASURED from the loaded
                       GIS layer (1 - share of records holding that
                       field's most common value, floor of 30 records,
                       recomputed on every GIS load).        (dec 66, 68)
    A field uniform across the deployment costs near nothing regardless
    of its editorial weight — in the current ND export A1 and Country
    both read discriminative_factor 0.0.

  Community is resolved by cascade BEFORE comparison:
    A3 -> A4 -> Post_Comm, first populated wins. The weight applied is
    the discriminative factor of whichever tier actually resolved the
    value for THAT record.                                   (dec 76)

  Compare each element by its class — every element belongs to exactly
  one, and the three classes are exhaustive:                 (dec 82)

    (1) IDENTITY GATES — Add_Number, UnitValue. Handled in step 6a
        above; they never reach this function as scored terms. The
        breakdown reports 100.0 for transparency, contributing a
        constant among survivors.                            (dec 69, 75)

    (2) BINARY CONTROLLED-VOCABULARY TERMS — St_Dir, A1, Country.
        Normalize (casefold/trim, plus the directional expansion
        table), then exact match -> 1.0, anything else -> 0.0. No edit
        distance, no Soundex: on a closed vocabulary, string similarity
        is actively wrong — "NE" vs "NW" scored 0.889 under the blend
        and "SD" vs "ND" scored 0.50. These are weighted terms, never
        gates: a hard A1 gate against a single-state export would empty
        the candidate set for a border-area caller.          (dec 82)
        St_Dir is ONE term spanning both St_PreDir and St_PosDir,
        compared best-of-both-sides — a pre/post swap ("Main Street
        North" for "North Main Street") therefore scores full credit.

    (3) HAND-TYPED NAME BLEND — St_Name, St_Type, Community, A2.
        Equal blend of normalized edit-distance similarity and binary
        Soundex, with exact match short-circuiting at the ceiling
        before either runs.                                  (dec 72)
        Edit distance is Damerau-Levenshtein restricted to adjacent
        transpositions, everywhere it is used.               (dec 74)

  Street-name qualification (applied within class 3):        (dec 71)
    Where both sides assert a street name, the candidate is
    DISQUALIFIED (matchScore forced to 0, breakdown still computed and
    reported) unless the names are Soundex-equivalent or reach
    _STREET_QUALIFY_MIN_EDIT_SIM. A record with no provisioned street
    name is NOT disqualified — sparseness costs score, not candidacy.
    Digit-leading tokens split into digit run + letter suffix
    ("22nd" -> "22" + "ND"): the digit runs must match EXACTLY (an
    identity gate — two digit runs are two streets), then the suffix is
    compared by edit distance alone. Soundex is never consulted for a
    digit-leading token, having no representation for digits. (dec 73)

  Community mismatch cap (applied within class 3):           (dec 80)
    A Community failing the qualification test is CAPPED at
    _COMMUNITY_MISMATCH_SIMILARITY_CAP (0.15) via min(), not zeroed and
    not gated. A caller may legitimately name the wrong town while
    being right about the address. Note the measured limit: because
    Community is one of seven averaged terms, the cap cannot move a
    wrong-community score materially closer to the admission floor at
    ANY value — see decision 80 and Appendix C item (d).
```

## 15.2 ReverseGeocode

```
REVERSE_GEOCODE(request):

  ─── Stage 0: Request Admission (§9) ────────────────────────────────
  1. Validate as §4.1 — FAIL -> 454, human-readable reason.  (§4.1, §9)
  2. Elect ONE location by RFC 5491 Rule #8, exactly as forward.
     i3 states the multi-location rule for Geocode only; this document
     applies it identically here, and records the asymmetry as a §16
     row.                                                    (§4.2)
  3. The elected location must carry a GEODETIC chunk; if not, 468.
     Do not walk past it.                                    (§4.2)

  ─── Stage 1: Nearest Feature Search (§10) ──────────────────────────
  4. ONE pass over all layers, not per-layer passes.         (§10.1)
     Where the input carries Z, run the 3D pass first and fall back to
     a 2D pass if it finds nothing.                          (§3.7)
  5. Bound the search by GCS_REVERSE_SEARCH_RADIUS_M — true geodesic
     metres on the WGS84 spheroid, NOT decimal degrees. A degree-space
     radius is an ellipse that stretches with latitude and would let
     the CRS's units silently overrule the algorithm. A degree-space
     bounding box remains available as an index pre-filter ahead of
     exact distance computation — an optimisation, not a unit. (§10.2, §10.5)
     Nothing within the radius -> 468.
  6. Order candidates LEXICOGRAPHICALLY — containment, then tier, then
     distance. Nothing is blended into a single number.      (§10.3)
     a. Contained candidates order ahead of uncontained ones.
        Containment is a flag on the candidate, not a gate in front of
        the search.
     b. Tier precedence is scoped to CONTAINED candidates only: among
        candidates inside the input shape, higher precision wins
        regardless of distance. A Point input has no area and contains
        nothing, so the commonest input never reaches this rule.
     c. Where nothing is contained — including every Point input —
        order purely by distance regardless of layer. A point 200 m
        from an address point and 5 m from a centerline is ON THE ROAD,
        and the honest answer is the segment's interpolated address.
     d. RCL candidates are tiered uniformly as INTERPOLATED_POINT for
        ORDERING; the tier actually REPORTED is whatever §11.2
        determines, which may be lower.                      (§10.3)
     e. Vertical participation is lexicographic, never Euclidean:
        candidates whose vertical extent contains the input Z order
        ahead of those whose extent does not. Note this band is inert
        on every currently provisioned feature class.        (§10.5, dec 60)
  7. Break residual ties on the feature's NGUID, ascending —
     deterministically arbitrary, so two GCS instances provisioned from
     the same SI data return identical results. A null NGUID makes a
     record ineligible and is reported as NGUID_MISSING.      (§10.4)

  ─── Spatial-Fit Scoring (§10.6) ────────────────────────────────────
  8. The §7.4 three-field model carries over with the matchScore slot
     REFILLED — a reverse request has no query address to compare
     against, so there is nothing to decompose into per-field
     similarity. The slot holds spatial fit instead:          (§10.6)
       base    = 100 if contained,
                 else 100 x (1 - min(distance / radius, 1))
       damping = radius / (radius + origin_extent)
                 -> 1 for a Point, falling as the query shape grows
       penalty = GCS_GEOCODED_PLACEMENT_PENALTY (0.9) where the
                 record's Placement Method is Geocoding, else 1.0
       spatial_fit = base x damping x penalty
     Extent damps the SCORE only; it never weakens containment within
     the ordering. The two are separable precisely because §10.3 orders
     lexicographically, so the score can honestly report "we found
     something contained, but your query was vague" without disturbing
     rank order.                                              (§10.6)
     The Geocoding penalty likewise sits OUTSIDE the ordering: it moves
     a reported number and no answer.                         (dec 83)

  ─── Stage 2: Civic Derivation (§11) ────────────────────────────────
  9. SSAP match: read the civic address directly off the record's
     fields. No derivation, inference, or synthesis — the record
     already holds a civic address and the GCS reports it.    (§11.1)

  10. RCL match — synthesise the house number, do not withhold it: (§11.2)
      a. Project the origin onto the segment; determine the side.
      b. Select side-specific attribution (§11.3) — this governs the
         administrative elements as well as the street name fields.
      c. Invert §7.2's interpolation along the SAME endpoint-margin-
         shortened path the forward direction walks. If the two
         directions traverse different paths, §14.1's round-trip
         consistency breaks by construction rather than by data.
      d. Guardrails: CLAMP the result to the segment's asserted range,
         and FORCE it to the parity of the side the origin fell on.
      e. Note the asymmetry with the forward direction: a zero-length
         range yields the single asserted number for ANY fraction —
         no rounding, no parity forcing, no synthesis. The reverse
         direction is most trustworthy on precisely the record that
         breaks the forward one.                              (§7.2)
      The synthesised number is tagged INTERPOLATED_POINT with a
      ceiling of 75 and a raw distance, so the enhanced interface
      states plainly that the value is derived. RFC 5139 gives HNO no
      way to mark itself approximate, so the strict i3 response cannot
      distinguish a validated point from an interpolated guess even in
      principle — §16 row.

  11. Administrative elements come from the MATCHED RECORD's own
      fields. The provisioned boundary layers are NOT consulted, even
      though point-in-polygon is how the ECRF decides jurisdiction and
      thus has a real claim to authority. §14's round-trip requirement
      governs: a forward geocode matched against the record's own
      fields, so reversing must hand those same fields back. No
      discrepancy is reported.                                (§11.3)

  12. An element with no source is OMITTED, never emitted empty —
      RFC 5139 gives an empty element no defined meaning, so emitting
      one asserts nothing while inviting a consumer to read it as an
      assertion.                                              (§11.4)
      A record too sparse to form a complete address is returned
      ANYWAY. The GCS may thus emit an address its sibling LVF would
      reject, from data both were provisioned with; that divergence is
      disclosed rather than repaired, because the alternative has the
      GCS invent a completeness standard i3 never gave it.

  ─── Stage 3: Response Assembly (§12) ───────────────────────────────
  13. i3 interface:  200, CivicAddress carrying a single
      pidfLoAddress string (NOT the published text's "PIDFLOAddress" —
      the schema's casing governs). No rank, no score, no distance, no
      containment flag, no Placement Method, and no indication that a
      house number was interpolated rather than read. Everything §10
      and §11 computed is discarded at this boundary, except RFC 7459
      confidence travelling inside the PIDF-LO.               (§12.1)
  14. i3-improved:   200, the ordered candidate list; per candidate the
      full matched PIDF-LO civic record, the three-field model with
      spatial fit in the matchScore slot, the containment flag, the raw
      geodesic distance, Placement Method where present, and the
      §10.31 match type token — Address for every point-tier match,
      RoadCenterline for every road-tier match. Hybrid is never
      emitted, one candidate matching exactly one feature.    (§12.2)
  15. Status codes mirror §8.4 with reverse-side triggers: 200 derived;
      307 + Location where GCS_REFERRAL_URI is set and nothing was
      derived; 454 schema/internal — noting the normative YAML omits
      454 from /ReverseGeocode entirely, an asymmetry this document
      declines to follow and records in §16; 468 valid request but
      nothing within the radius. 469 is not emitted.          (§12.3)
```

# 16. Known Gaps and Recommended Actions

The formal gap register described in §1.3. Rows are added as gaps are discovered and are never silently removed; a resolved gap is marked resolved and cites the resolving document. This table is the primary artifact intended for NENA standards development.

| **Gap**                                                                           | **Description**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | **Recommended Action**                                                                                                                                                                                                                                                          |
|------------------------|------------------------|------------------------|
| i3 §4.5 defines no conversion algorithm                                           | STA-010.3f-2021 §4.5 defines two endpoints, two response objects, and five status codes across approximately two pages. It specifies no candidate identification logic, no interpolation method, no uncertainty representation, and no tie-breaking. Two conformant implementations can return materially different coordinates for the same address, and neither is non-conformant.                                                                                                                                                                                                                                                                                                                                | A future i3 revision, or a companion NENA information document, should specify the GCS conversion algorithm normatively — as INF-027 attempted for the LVF.                                                                                                                     |
| No uncertainty or confidence representation                                       | i3 §4.5 acknowledges that conversion introduces error and depends on a “nearest point algorithm”, but requires no expression of that error in the returned PIDF-LO. A surveyed address point and a position interpolated across a half-mile rural segment are returned as identical bare gml:Points and are indistinguishable to the consumer.                                                                                                                                                                                                                                                                                                                                                                      | A future i3 revision should require the GCS to express conversion uncertainty using RFC 5491 shapes and confidence.                                                                                                                                                             |
| No matchType carrier for the GCS                                                  | i3 §3.4.10 offers language written for exactly this problem — that it is helpful to indicate “what type of match was used by the LVF’s geocoding logic” and to warn when a match is “of lesser quality than might be expected” — and provided tokens in the §10.31 Match Type registry.                                                                                                                                                                                 | A future i3 revision should provide a matchType carrier in GeodeticData / CivicAddress, reusing the existing §10.31 registry rather than defining new tokens.                                                                                                                   |
| §8.1/§12.1 indistinguishability versus RFC 7459 confidence                        | i3 §4.5's response objects carry a single PIDF-LO string and no quality vocabulary, which is what makes a fuzzy match indistinguishable from an exact one. RFC 7459 confidence nonetheless travels inside that PIDF-LO, so the strict interface does carry one coarse quality signal — by way of the IETF's payload vocabulary, not i3's. i3 says nothing about whether a GCS should populate it, so two conformant implementations may differ on whether any quality signal reaches the caller at all.                                                                                                                                                                                                                                                                    | A future i3 revision should state normatively whether a GCS populates RFC 7459 confidence, and on which resources. Absent that, the one quality signal the strict interface can carry is optional by omission. |
| No scoring or multi-candidate disclosure                                          | i3 defines no scoring concept anywhere, and GeodeticData carries a single pidfLoGeo. A geocoder is conventionally a ranked multi-candidate service. Two equally perfect matches — two address points, or two road segments — collapse to one coordinate with no indication the other existed. A fuzzy match returns 200 and a coordinate byte-for-byte indistinguishable from an exact match, on the interface a PSAP is most likely to consume.                                                                                                                                                                                                                                                                    | A future i3 revision should define ranked candidates with scores, or state normatively that the GCS is a single-answer service and accept the consequences. The i3-improved interface (§2.2) is offered as a working demonstration of what the current contract cannot express. |
| 468 conflates distinct failure conditions                                         | 468 “No Address Found” is the only code available for: no matching record; ambiguous match beyond tolerance; and a location outside the provisioned data entirely. These require different client behaviour. The §10.29 Status Codes registry already contains better vocabulary that §4.5 does not use — 333 Iterative Refer, 453 Not Available Here No Referral Available, and 470 Unknown Service/Database (“Not Ours”). NOT resolved by decision 114 (Session 14): 468 now carries a body reason for shape-consistency with 454, but that reason is deliberately fixed and invariant across every cause — it narrows nothing this row describes, and the underlying need for distinct status codes stands as stated.                                                                                                                                                                                                                                                                                         | A future i3 revision should extend the GCS status code set from the existing §10.29 registry rather than minting new codes.                                                                                                                                                     |
| gcsReferralUri required where no referral is knowable                             | i3 §4.5 requires gcsReferralUri whenever conversion does not succeed. A GCS correctly scoped to its own ESInet does not know another GCS’s URI — that knowledge belongs to the ECRF and the Service/Agency Locator. The requirement is therefore unsatisfiable by design for a correctly-scoped GCS. The Policy Store (§3.3.1.2.1) already defines 453 “Not Available Here, No Referral Available” for precisely this condition. This implementation returns 468 without gcsReferralUri (§3.6.2) — a knowing departure.                                                                                                                                                                                             | A future i3 revision should add 453 to the GCS status code set, or make gcsReferralUri conditional on a referral being knowable.                                                                                                                                                |
| No discovery or coverage mechanism for the GCS or MDS                             | The ECRF/LVF have LoST-Sync (RFC 6739), the Forest Guide, and a specified coverage model. The GCS has none, despite being provisioned from the same SI and deployed in the same ESInet, and is nonetheless required to refer. The MDS is in the same position. The absence forces manual provisioning of referral targets, which does not scale and has no consistency guarantee against the GIS data it purports to describe.                                                                                                                                                                                                                                                                                      | A future i3 revision should define GCS and MDS coverage derivation and exchange — preferably by reusing the concepts already proven for the ECRF/LVF rather than defining a parallel mechanism.                                                                                 |
| Service/Agency Locator record cannot carry the GCS URI                            | i3 §4.15 requires every service on the ESInet to be listed in the S/AL with its record URI in the ECRF, and §4.15.2 specifies the lookup. The §10.11 serviceNames registry contains “GCS”; the §10.30 Interface Names registry contains “Geocode” and “ReverseGeocode”. But the §4.15.4 record schema has no field for the GCS interface URI — the MDS received two dedicated fields (mdsFeatureIntefaceUri, mdsImageIntefaceUri, both missing an “r” relative to the correctly-spelled eidoInterfaceUri and emergencySipInterfaceUri), the GCS received none. The MCS is missing for the same reason. A client that follows the specified discovery path arrives at a record that cannot tell it where the GCS is. | A future i3 revision should add an OPTIONAL gcsInterfaceUri to the §4.15.4 record, carrying the base URI to which /Geocode and /ReverseGeocode are appended, and an equivalent for the MCS. Correct the mds\* spellings while doing so.                                         |
| 469 “Unknown MCS/GCS” condition undefined                                         | The condition this status code describes is not stated, and is not apparent for a request that carries no service identifier and addresses a specific GCS by URI.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | A future i3 revision should define the condition or remove the code from the GCS status set.                                                                                                                                                                                    |
| No 3D space layer                                                                 | STA-006.3 §4.2.1 declares SSAP 3D-capable with Z = Altitude = HAE, but provides no layer for the individual spaces that comprise a multi-storey structure. Table 8-1 simultaneously records that “stacked address points will result in topology errors and goes against existing GIS data standards” and defers the issue — stacked points being the only available means of representing vertically-separated addresses. The data model supports 3D points and disowns the sole way to use them for a building. Stacking is tempting only because no space layer exists; modelling spaces as volumes makes the topology objection moot.                                                                           | A future STA-006.3 revision should define a 3D space/volume layer and provision it to the GCS, resolving the stacked-point topology question in the same action.                                                                                                                |
| RCL 3D support unstated                                                           | STA-006.3 §4.2.1 declares only SSAP 3D-capable. RCL geometry carrying Z is neither required nor forbidden, so whether a rung-2 result can be three-dimensional depends on undocumented local practice. The same address may geocode 3D via SSAP and 2D via RCL.                                                                                                                                                                                                                                                                                                                                                                                                                                                     | A future STA-006.3 revision should state whether RoadCenterLine geometry may or must carry Z.                                                                                                                                                                                   |
| Z precedence undefined                                                            | SSAP carries Elevation (§5.43), Altitude, and Height (§5.50) as attributes plus Z in the geometry — four places a vertical value can live. Table 8-1 calls the attributes transitional and states that Altitude (Z) will join X and Y in the geometry. No rule governs disagreement between them.                                                                                                                                                                                                                                                                                                                                                                                                                   | A future STA-006.3 revision should state precedence explicitly, or complete the transition and retire the attribute fields.                                                                                                                                                     |
| No access point / setback model                                                   | An address point represents where a structure is; it does not represent where a responder enters, and an RCL-interpolated position sits in the roadway. STA-006.3 models neither an access point nor a setback convention. Commercial geocoders model this explicitly (Google exposes navigation points and building entrances as first-class concepts distinct from the geocode result).                                                                                                                                                                                                                                                                                                                           | A future STA-006.3 revision should consider an access point representation distinct from the address point position.                                                                                                                                                            |
| SiteStructureAddressPolygon not provisioned to the GCS                            | STA-006.3 classifies SiteStructureAddressPolygon as Recommended and assigns it to MDS only. Polygon extent is geometrically more precise than a point and would yield a defensible uncertainty region where a bare point yields none. Table 8-1 already carries an open question on how the functional elements should use it.                                                                                                                                                                                                                                                                                   | A future STA-006.3 revision should consider elevating SiteStructureAddressPolygon for GCS provisioning and defining its position in the ladder.                                                                                                                                 |
| PIDF-LO envelope presupposes a presentity                                         | RFC 4119 requires `<presence>` to carry an entity attribute identifying the presentity, and requires `<usage-rules>`, within which retransmission-allowed defaults to “no” and MUST be emitted as “no” absent a Rule Maker preference. A geocode result has no presentity and no Rule Maker. A strict reading has the GCS emitting retransmission-allowed=“no” on every response inside a system built to pass location to responders. i3 §4.5 says “returns a PIDF-LO” and never addresses using a presence format as a plain location container.                                                                                                                                                                                              | A future i3 revision should state what the GCS populates for entity and usage-rules — RFC 5985/6753’s unlinked-pseudonym convention is the available precedent — or specify a non-presence location container for conversion results.                                           |
| No IANA method token for geocode derivation                                       | RFC 4119 §2.2.3 constrains `<method>` values to an IANA registry pre-populated with GPS, A-GPS, Manual, DHCP, Triangulation, Cell, and 802.11 — all device-positioning methods. None describes a position derived by matching a civic address to a GIS record. This implementation omits `<method>` (§8.3). The registry is open on a first-come-first-serve basis.                                                                                                                                                                                                                                                                                                                                                                       | NENA should consider registering method tokens describing GCS derivation, or i3 should point to STA-006.3 Placement Method (§6.1 registry) as the provenance carrier.                                                                                                           |
| First-location rule stated for Geocode only                                       | i3 §4.5 requires a multi-location Geocode request to return only the conversion of the first location, and is silent on the same question for ReverseGeocode.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | A future i3 revision should state the rule for both functions, and define “first” and the treatment of locations of the wrong profile.                                                                                                                                          |
| GeodecticData / PIDFLOAddress naming                                              | “GeodecticData” is a typographical error for “GeodeticData” in the published text, and the two response field names use inconsistent casing (pidfLoGeo vs PIDFLOAddress). The object name is unlikely to reach the wire; the field names certainly do. Per §2.8 the GitHub YAML is authoritative over the text, so the text is not dispositive.                                                                                                                                                                                                                                                                                                                                                                     | RESOLVED for this implementation (Session 3): the YAML is read and controls — GeodeticData, pidfLoGeo, pidfLoAddress adopted (§3.9.1). The row remains NENA-facing: a future i3 revision should correct the text so text and schema agree.                                      |
| No relationship defined between GCS and LVF results                               | GCS and LVF are provisioned from the same SI data and answer overlapping questions about the same address space, but no standard requires their answers to be consistent. An address may geocode successfully and fail validation, or vice versa, with no conformance violation.                                                                                                                                                                                                                                                                                                                                                                                                                                    | A future i3 revision should state the required consistency relationship between GCS conversion results and LVF validation results for an FE set provisioned from a common SI.                                                                                                   |
| Address point placement convention                                                | STA-006.3 provides Placement Method ID with a registry (§6.1), so the convention is discoverable per record — but does not mandate one, and Table 8-1 carries open placement questions. The LVF is indifferent because it compares attributes only; the GCS output is the coordinate.                                                                                                                                                                                                                                                                                                                                                                                                                               | A future STA-006.3 revision should resolve the open placement questions and consider whether Placement Method should be mandatory where the GCS is provisioned.                                                                                                                 |
| Text and normative YAML contradict on referral carriage                           | i3 §4.5’s text requires gcsReferralUri in the response body whenever conversion does not succeed. The normative OpenAPI YAML defines no such property on GeodeticData; the referral URI travels in the Location header of a 307. The two readings are irreconcilable, and §2.8 makes the YAML controlling — leaving the text’s MUST pointing at a field that does not exist.                                                                                                                                                                                                                                                                                                                                        | A future i3 revision should correct the §4.5 text to match the YAML (307 + Location header) or amend the YAML, so that text and schema agree.                                                                                                                                   |
| Normative YAML content types are incoherent | RESOLVED (Session 14, decision 116). The YAML declares the request body application/json with schema type string, and the 200 response application/xml referencing a JSON-shaped object wrapper (GeodeticData / CivicAddress). Sessions 1-13 read an XML content type as unable to carry the declared JSON object schema and emitted application/json for the response instead. That reading did not account for OpenAPI 3.0's own default XML serialization (an object's properties become child elements named after the property, absent an `xml:` annotation — confirmed against the OpenAPI 3.0.3 specification directly), under which `application/xml` and `{pidfLoGeo: string}` both hold: `<GeodeticData><pidfLoGeo><![CDATA[...]]></pidfLoGeo></GeodeticData>`. The YAML as published was implementable all along; the defect was in this document's prior reading of it, not in the published artifact. | NONE — no action needed from NENA. Superseded by decision 116; this row is retained per §16's own no-silent-deletion rule, and as a record that the original "recommend NENA fix their YAML" framing was itself mistaken. |
| No malformed-request vocabulary; 454 asymmetric                                   | i3 gives its web services no status code meaning “your request was malformed” — 468 asserts a search occurred and 469 is undefined, leaving only 454 Unspecified Error, which tells the caller nothing and invites pointless retries. The normative YAML compounds this: /Geocode lists 454 and /ReverseGeocode does not, so a schema-invalid reverse request has no defined error code at all.                                                                                                                                                                                                                                                                                                                     | A future i3 revision should add a malformed-request code to the GCS status set (the §10.29 registry is the natural source) and correct the YAML asymmetry.                                                                                                                      |
| i3 silent on the constructed PIDF-LO envelope                                     | i3 §4.5 says the GCS “constructs a PIDF-LO” without stating what the mandatory entity attribute or usage-rules contain for a document with no presentity and no Rule Maker; implementations will diverge. The IETF already solved this for the LIS: RFC 5985 has the producer generate an unlinked pseudonym for entity, and RFC 6753 makes it MUST-level absent Rule Maker policy.                                                                                                                                                                                                                                                                                                                                 | A future i3 revision should specify the GCS envelope convention, adopting the RFC 5985/6753 unlinked-pseudonym precedent (or input echo where an input entity exists) rather than inventing new mechanism.                                                                      |
| Input uncertainty is unrepresentable in the reverse response                      | A caller who expresses a two-kilometre wireless uncertainty circle receives a civic address indistinguishable from one derived from a surveyed point. i3 gives the reverse response no way to say “this address is merely the nearest thing to a large region,” so the extent of the question is lost in the answer. This document carries it as a spatial-fit score on the enhanced interface only (§10.6).                                                                                                                                                                                                                                                                                                        | A future i3 revision should define a reverse-side quality or fit indicator on CivicAddress, so that the precision of the question is recoverable from the response.                                                                                                             |
| Multi-location discard is mandated but unsignallable                              | i3 §4.5 requires that a request carrying more than one location yield exactly one result, being the conversion of the first — but provides no element, header, or status by which the response can indicate that other locations were present and discarded. A caller cannot distinguish a single-location request from a multi-location request whose remainder was dropped.                                                                                                                                                                                                                                                                                                                                       | A future i3 revision should define a warning or count element on the response objects indicating how many locations were present and which was converted.                                                                                                                       |
| Multi-location rule stated for Geocode only                                       | i3 §4.5 states the first-location rule in the Geocode description and says nothing equivalent for ReverseGeocode, leaving multi-location reverse requests without a specified behaviour. This document applies the Geocode rule symmetrically (§4.2, §9); another implementation could legitimately do otherwise.                                                                                                                                                                                                                                                                                                                                                                                                   | A future i3 revision should state the rule once for both operations, or restate it explicitly under ReverseGeocode.                                                                                                                                                             |
| RFC 5139 cannot mark HNO approximate                                              | An inversely-interpolated house number (§11.2) and a house number read from a validated address point serialise identically. The civic schema itself provides no approximation or derivation marker, so the strict i3 response cannot distinguish a guess from a fact even in principle. This is deeper than i3’s silence — it is a limitation of the civic address format.                                                                                                                                                                                                                                                                                                                                         | An IETF revision of RFC 5139 (or an i3-level extension element) should provide a per-element derivation or approximation marker, so that interpolated civic elements can be identified as such.                                                                                 |
| No completeness contract between LVF validity and GCS output                      | STA-006.3 permits sparse attribution, so a GCS reverse response constructed faithfully from a valid SSAP record (§11.4) may be an address the LVF, provisioned from the same SI data, would fail. Nothing in i3 requires the two services to agree about the same record, and neither behaviour is non-conformant.                                                                                                                                                                                                                                                                                                                                                                                                  | A future i3 revision should state a completeness contract for GCS output relative to LVF validity, or require the SI to enforce the attribution minimum that makes the two consistent.                                                                                          |
| Match Type registry is coarser than achievable precision                          | The §10.31 registry offers Address and RoadCenterline as the only usable tokens (confirmed by direct read). RoadCenterline cannot distinguish a street-level match from a house number interpolated within a range, and no token describes an interior or volumetric match. A GCS therefore cannot express in registry vocabulary the precision distinctions it is capable of computing.                                                                                                                                                                                                                                                                                                                            | A future i3 revision should extend the §10.31 registry with tokens distinguishing interpolated from exact address matches and covering interior/volumetric matches, rather than leaving implementations to invent private vocabularies.                                         |
| Address polygons are Recommended, not Required — precision varies by jurisdiction | STA-006.3-2026 carries Site/Structure Address Polygons (§4.2.2) with an Extent Method registry (§6.2), so footprint-level precision is achievable — but only where an SI has opted into an optional feature class. The confidence a caller receives for the same real-world address therefore varies by jurisdiction according to a provisioning choice, not according to anything about the address. No volumetric feature class exists at all (§7.5).                                                                                                                                                                                                                                                             | A future STA-006.3 revision should consider elevating Site/Structure Address Polygons from Recommended to Required, and should add a volumetric feature class for individual spaces within a structure.                                                                         |
| /Versions response schema reference is unresolvable | The normative YAML's `/Versions` 200 body is `$ref: 'i3-common.yaml#/components/schemas/VersionsArray'`, and no `i3-common.yaml` exists in the published NENA911/Geocode-Conversion-Service repository — the reference cannot be resolved from the published artifact. Not blocking for this implementation (the i3 §4.12 body shape is well known), but a defect of the same class as the content-type incoherence above (decision 95, Appendix C.4 Q2). | A future revision of the GitHub definition should include `i3-common.yaml` in the repository or inline the VersionsArray schema. |
| No GCS LogEvent type | i3 §4.12.3.7 defines 44 LogEvent types and none covers GCS conversions — confirmed by direct read of the full registry. LostQueryLogEvent/LostResponseLogEvent are scoped by their own definitions to ECRF/LVF LoST traffic, and LocationQueryLogEvent/LocationResponseLogEvent to LSRG/LPG ALI traffic. Yet §4.5 places a payload-logging MUST on the GCS (“the input and output objects”), leaving the service an obligation to log with no registered type to log as (decision 104, Appendix C.4 Q10). | A future i3 revision should register GcsQueryLogEvent / GcsResponseLogEvent on the LostQuery/LostResponse pattern (whole payload, queryId/responseId correlation, direction, responseStatus), and should state the privacy posture the payload-logging MUST implies. |

# Appendix A — i3 Infrastructure and Protocol Requirements

This appendix enumerates normative MUST/SHALL requirements from NENA-STA-010.3f-2021 that apply to a GCS implementation but are outside the scope of this algorithm document. Implementation of these requirements is the responsibility of the deploying organization. Each item notes the i3-fe-core module that discharges it, so the appendix doubles as the core wiring checklist.

## A.1 Versions Entry Point

***i3 citation: NENA-STA-010.3f-2021 §2.8.3, §4.12***

Every web service has a major/minor version; any change to the YAML changes the version, backwards-compatible changes increment minor. Implementations MUST ignore data structure elements they do not understand and MUST return 404 for web interfaces they do not provide as a server. i3-fe-core web_service.versions provides make_versions_route() / build_version_entry(). Resolved (Session 3): one web service — the normative YAML defines a single specification with one server base and one /Versions entry point covering both operations. The Versions vendor parameter is the discovery hook for the enhanced interface (§3.9.2). Resolved (Session 11, decision 95): the entry point lives at `/Gcs/Versions`, one segment above the versioned base, per the YAML's own `servers` override — unversioned by design, since a client must reach version discovery before it knows which versions exist. The YAML's `/Versions` response `$ref` to `i3-common.yaml` is unresolvable from the published repository (§16); i3-fe-core's §4.12 body shape stands in.

## A.2 NTP Client Interface

***i3 citation: NENA-STA-010.3f-2021 §4.3.5***

Time-of-day is an input to the logging interface and to temporal filtering (§3.4). i3-fe-core time.ntp.

## A.3 Logging (LogEvent Interface)

***i3 citation: NENA-STA-010.3f-2021 §4.5, §4.12***

i3 §4.5 states directly that the service logs the invocation of the function, as well as the input and output objects. This is stricter than the LVF’s obligation — the GCS is explicitly required to log the payloads, not merely the event. i3-fe-core logging.

***✔ Settled (Session 11, decision 104 — resolves Appendix C.4 Q10):** Confirmed by direct read of the full §4.12.3.7 registry (44 defined types): i3 defines no GCS-specific LogEvent type. The nearest analogues — LostQueryLogEvent/LostResponseLogEvent (scoped to ECRF/LVF traffic) and LocationQueryLogEvent/LocationResponseLogEvent (scoped to LSRG/LPG ALI traffic) — do not cover GCS conversions. §16 row. This document proposes GcsQueryLogEvent / GcsResponseLogEvent on the LostQuery/LostResponse pattern: whole payload carried in the event, a globally unique queryId/responseId pair correlating the two, direction incoming/outgoing, and responseStatus preserving the malformed/no-response cases a single combined event could not represent. A privacy consequence of §4.5's payload-logging MUST is stated rather than inherited silently: every logged Geocode request contains a civic address and every logged response a coordinate, so the Logging Service accumulates a complete queryable record of which addresses were asked about. Deployments should weigh that when configuring Logging Service retrieval policy (LogServiceAllowedToRetrieve).*

***✔ WIRED (decision 110):** `GcsQueryLogEvent`/`GcsResponseLogEvent` as proposed above are implemented and emitted at every return path of both `/Geocode` and `/ReverseGeocode` — success, no-result, error, and admission failure alike. The query event fires unconditionally, before admission, so the privacy consequence stated above is realized in full: a malformed request is logged too, not only a valid one.*

## A.4 ElementState Event Notification

***i3 citation: NENA-STA-010.3f-2021 §4.5, §4.3.5***

Each FE in the GCS MUST implement the server-side of the ElementState event notification package and MUST promptly report changes in its state to subscribed elements — including GIS data unavailability (§3.5) and loss of NTP synchronisation. i3-fe-core state.element_state + notify.sip_notifier.

***✔ WIRED (decision 109):** The SIP transport is implemented via `src/notify/sip_notifier.py`, a real `SipWireAdapter` ported from lvf-service's maintained reference (UDP+TCP, real SIP message parsing).*

***✔ WIRED (decision 113):** `logging_client` is now passed through, matching every other GCS core component — a `SubscribeLogEvent` is emitted for every processed SUBSCRIBE. `validate_target_uri` remains deliberately unimplemented: no reference posture exists in LVF or MCS to port from, and decision 113 declines to have GCS originate a novel security-adjacent design ahead of its own reference implementations. Parked, not dropped.*

## A.5 ServiceState Event Notification

***i3 citation: NENA-STA-010.3f-2021 §4.5***

The set of GCS FEs within an ESInet MUST implement the server-side of the ServiceState event notification package. Where multiple ESInet levels exist within a state, it is RECOMMENDED that the state-level GCS implement ServiceState as a single service rather than one per level. i3-fe-core state.service_state.

***✔ WIRED (decision 109):** Carried over the same SIP transport as §A.4 — one `SipWireAdapter` serves both event packages.*

## A.6 Discrepancy Reporting

***i3 citation: NENA-STA-010.3f-2021 §3.7, §4.9***

i3 §10 lists a GCS entry in the XACML permissions registry, implying a GCS interface subject to DR. i3-fe-core discrepancy provides the responding service and the filing client. (A historical note: §6.3 and §7.1 once proposed filing DRs for data conditions the GCS detects; both later settled the other way — decisions 29 and 45.)

***✔ Settled (Session 11, decision 98 — resolves Appendix C.4 Q6):** The DR web service's canonical base is `/dr`, giving §4.12's required Versions entry point a home at `/dr/Versions`. The root-mounted aliases for Reports/Resolutions/StatusUpdates are retained deliberately against the same instance, because i3 §3.7.1–3.7.3 name the resources with no base path and i3-fe-core's conformance suite probes them at the root. `/dr` is the path a client should be given; the aliases are withdrawable if a future i3 revision states a base path.*

***✔ Settled (Session 11, decision 99 — resolves Appendix C.4 Q7):** The GCS files discrepancy reports about structural provisioning defects only — conditions under which it cannot perform behaviour this specification requires — and never about attribution content. The triggers: GIS load/reload failure; null NGUID (R3 — ineligible for §10.4's deterministic tie-break); multi-part RoadCenterLine segment (decision 53 — no defined traversal order); no usable geometry (decision 55 — cannot be a located match). These are exactly the conditions the engine's data-quality flags already record; the flag vocabulary is the filing vocabulary.*

***✔ WIRED (decision 111):** The filing side is implemented in `src/discrepancy/discrepancy_report.py`, ported from lvf-service with its LoST-report half dropped, and wired into all four trigger sites named above. `GCS_DR_ENDPOINT` unset leaves it a local-log-only no-op, matching lvf-service's own default posture.*

## A.7 SI/SDPI Data Feed Interface

***i3 citation: NENA-STA-010.3f-2021 §4.5, §4.3.3, §3.6***

i3 §4.5 states the GCS is provisioned by layer replication from the master SI, the same mechanism as ECRF and LVF. This document specifies the algorithm applied to data once loaded, not the mechanism by which it is received. A future major version of i3 will deprecate the current SI in favour of the SDPI.

## A.8 Security

***i3 citation: NENA-STA-010.3f-2021 §2.8.1; NENA-STA-040.2-2024***

HTTPS mandatory; HTTP/1.1 MUST, HTTP/2 SHOULD; TLS 1.2 MUST, TLS 1.3 MAY, TLS 1.0/1.1 MUST NOT; perfect forward secrecy within the ESInet. Credentials traceable to the PCA. i3-fe-core security.tls / security.peer_auth, both wired as of decision 108; see §3.9.3.

***✔ History (decisions 107, 108):** Between Session 11 and Session 13 this row named core modules that were not actually in use, a false claim decision 107 withdrew and decision 108 subsequently closed by wiring them for real, verified by observed handshake behaviour rather than by configuration inspection. Retained as a reminder that this appendix's rows were re-verified against imports once, and are worth re-verifying again rather than trusted by default.*

# Appendix B — Decision Register

Decisions reached in working sessions, with the reasoning that produced them. This register exists because a materially higher share of GCS rules are novel contributions with no normative citation to anchor them, so the reasoning has nowhere natural to live beside the rule. Entries are not removed; a reversed decision is superseded by a later entry that cites it.

### 1 — §1, 3.1

**Decision:** US civic addresses only (CLDXF-US). CLDXF-CA out of scope for v1.

**Reasoning:** Consistent with LVF v79 §1; GCS inherits the boundary with the shared element model.

### 2 — §1.2.1

**Decision:** Strict reading. Algorithm gaps filled; wire vocabulary not invented. Status codes limited to §4.5’s five; no added fields on i3 response objects; no invented messages.

**Reasoning:** The GCS interface is materially less complete than LoST, so the line must be drawn explicitly. Deficiencies are carried and documented rather than patched. Corollary: restrictions i3 lacks are not added either.

### 3 — §1.5

**Decision:** Shared element model with LVF; divergent gates and terminal conditions. Packaging deferred until code exists.

**Reasoning:** The filter is a small loop each FE wants to wrap differently; the element hierarchy and field mapping are what make §14 provable. Root cause of divergence: LVF is flexible in reporting and can afford rigid matching; GCS has no partial-success vocabulary and can only degrade in the search.

### 4 — §3.1, 3.6

**Decision:** GCS is scoped to its ESInet and its provisioned data. No coverage region, no recursion, no redirection on its own initiative.

**Reasoning:** Discovery is the ECRF’s and S/AL’s job. Collapses coverage derivation, referral topology, and loop prevention out of the document entirely.

### 5 — §3.6.2

**Decision:** gcsReferralUri is statically provisioned. 468 without a referral where none is configured.

**Reasoning:** The deficit is data, not vocabulary — the GCS lacks a URI to publish, not a way to express one, so inventing a message would not help. Knowing departure from the §4.5 MUST.

### 6 — §3.6.3

**Decision:** Referral is a scope referral, not failover.

**Reasoning:** Every other 307 in i3 is a scope referral (IS-ADR, Policy Store, S/AL Search). i3’s idiom for FE redundancy is client-side multi-instance configuration with health out-of-band via ElementState/ServiceState.

### 7 — §2.2

**Decision:** Two interfaces: the i3 interface and the i3-improved interface.

**Reasoning:** A geocoder must be scored, ranked, and multi-candidate; i3 has no vocabulary for any of it. Two interfaces satisfy the standard and the requirement without compromising either.

### 8 — §2.3

**Decision:** One engine. The engine always produces a ranked scored candidate list; the i3 interface takes rank 1 and drops what §4.5 cannot carry.

**Reasoning:** Keeps §15 to one algorithm, makes the i3 answer provably the same answer, and means fuzzy matching informs both interfaces or neither.

### 9 — §2.2, 8.1

**Decision:** No score floor on the i3 interface. The deficiency is carried faithfully.

**Reasoning:** A floor would hide the defect behind our own judgment. Carrying it makes the two interfaces a controlled comparison with the i3 contract as the variable — a stronger argument to the working group than any gap row.

### 10 — §8.1

**Decision:** i3 interface: pidfLoGeo carries the geodetic representation only. The matched civic address is not echoed.

**Reasoning:** §4.5 says the response contains the converted form; RFC 5491 describes what a PIDF-LO may contain and has no opinion on what a Geocode response should. “The format permits it” is not “the standard asks for it”.

### 11 — §8.2

**Decision:** i3-improved interface returns the full matched PIDF-LO record per candidate, not a bare geometry.

**Reasoning:** The client can see a fuzzy substitution by diffing the returned record against its query. LVF’s completeLocation is very nearly this function already.

### 12 — §8.3

**Decision:** omitted on both interfaces.

**Reasoning:** RFC 4119 constrains values to an IANA registry of device-positioning methods. The GCS matches a GIS record whose provenance it did not observe and often cannot see; emitting a token would be a guess presented as metadata. Placement Method ID is the legitimate provenance carrier.

### 13 — §1.2.1

**Decision:** PIDF-LO conformance travels with the format, not the interface.

**Reasoning:** Extensions ride in the i3-improved envelope; embedded PIDF-LO records stay RFC 4119 / RFC 5491 conformant. Being non-i3 buys freedom in our envelope and none inside a PIDF-LO.

### 14 — §5

**Decision:** No Gate 1. HNO is not required; street-level queries are accepted and answered at rung 3.

**Reasoning:** i3 §4.5 imposes no structural precondition; requiring one would add a restriction the standard does not have. The honesty burden moves to uncertainty, where RFC 5491 supplies the vocabulary.

### 15 — §3.3

**Decision:** Three-rung precision ladder, not a two-layer fallback.

**Reasoning:** Rung 3 is a different kind of answer, not a less precise one — it is the whole segment. Matches the industry shape (Google location_type) and i3’s own §10.31 Match Type registry.

### 16 — §3.7

**Decision:** Vertical datum is HAE (EPSG:4979). CRS is per-response, determined by the matched feature.

**Reasoning:** STA-006.3 §4.2.1: Z of the geometry corresponds to Altitude, which is Height Above Ellipsoid. Not a choice this document makes.

### 17 — §3.7.1, 7.2

**Decision:** Geocode carries Z through from the matched feature; it does not compute or search in 3D. Position derivation is one interpolation carrying whatever dimensions the vertices have.

**Reasoning:** SSAP: Z of the point. RCL: Z along the line at the interpolated position. 3D space: centroid. One code path, dimensionality determined by the data.

### 18 — §3.7.2

**Decision:** ReverseGeocode searches in 3D where the input carries Z, then falls back to a 2D flattened pass if nothing is found.

**Reasoning:** Given STA-006.3 disowns stacked address points and defines no 3D space layer, the 2D pass is the productive one in most jurisdictions today — the fallback is the normal path, not an edge case.

### 19 — §3.7.3

**Decision:** Minimise maximum error: return the position minimising worst-case error across surviving candidates; size uncertainty to their extent.

**Reasoning:** Vertically, the midpoint of a 20-storey structure bounds the error at 30 m where naming floor 1 permits 60 m, and gives sensor-based vertical determination room to converge from either direction. Horizontally, the same principle yields a position between candidates rather than an arbitrary election. §6.3 and §7.4 are applications of this, not independent rules.

### 20 — §6.3

**Decision:** Ambiguity is tested geometrically, not combinatorially. Vertical agreement merges unconditionally; horizontal disagreement beyond tolerance returns 468.

**Reasoning:** LVF counts candidates because it cannot attribute validity; GCS measures them because a position between two nearby candidates is a better answer than 468. Two matches 40 miles apart are not a location.

### 21 — §7.5

**Decision:** A multi-storey structure is modelled as the individual spaces that comprise it, not one extruded solid. Deferred to future work; design must accommodate without rework.

**Reasoning:** Makes the centroid meaningful (mid-space is where people are, mid-building is not) and moots STA-006.3’s stacked-point topology objection. Also relocates the merge case: a query naming the unit returns one space at full precision — merging is a response to an underspecified query, not to the data being 3D.

### 22 — §14

**Decision:** §14 consistency is scoped to address-level results. Rung 3 is not comparable rather than inconsistent.

**Reasoning:** A street-level result has no LVF analog, so it cannot disagree with one.

### 23 — §3.6.1

**Decision:** S/AL gap fix proposes gcsInterfaceUri following the existing per-interface field pattern rather than a general interfaces array.

**Reasoning:** Align with the standard as written rather than architecting something more graceful in a gap row.

### 24 — §1, 1.2

**Decision:** Interfaces standardized; algorithm proprietary. Document is an internal working record; only §16’s gap register and its proposed extensions are shared with NENA.

**Reasoning:** Unlike LVF, cross-implementation agreement on matching/scoring logic is not the goal for a geocoder — that logic is competitive design. What must interoperate is the contract: request/response shape, status codes, and confidence vocabulary.

### 25 — §1.5, 14

**Decision:** §1.5 trimmed. LVF is a source-code/directory-structure reference and a source of reusable pieces (e.g. completeLocation), not a model the GCS mirrors or diverges from.

**Reasoning:** The Session 1 gate-by-gate LVF comparison over-indexed on LVF as a model to diverge from. LVF’s own interface is LoST-based and not relevant to how a GCS does its work. Output should still agree where the two overlap (§14), as a design-time consequence of shared data/element model, not a runtime cross-check.

### 26 — §4.2

**Decision:** §4.2 strict reading confirmed: use the first location exactly as spec states, no fallback for malformed/wrong-profile locations.

**Reasoning:** Consistent with §1.2.1’s strict-reading posture — skipping to a second location for any reason would be an invented behaviour i3 does not ask for.

### 27 — §6.3

**Decision:** Multi-candidate merge reframed: i3-improved returns ranked candidates; i3 interface averages/centroids with extent-sized uncertainty. Averaging is internal-only; the underlying gap is NENA-facing.

**Reasoning:** Duplicate identical-attribute records are a data-hygiene defect out of scope. The real case (generic query, distinct structures on one parcel) is a legitimate multi-candidate answer, best served by the ranked list already built into the one-engine design (§2.3) rather than a synthetic geometric compromise.

### 28 — §6.5

**Decision:** One scoring function for §6.5, not a two-stage exact-then-fuzzy pipeline.

**Reasoning:** Research into PostGIS Tiger geocoder (rate_attributes) and Nominatim confirms real-world precedent is one unified per-field similarity comparison, with exact match as the ceiling of the same scale, not a separate code path.

### 29 — §7.1

**Decision:** Z precedence chain: geometry → Altitude → Elevation. No discrepancy report.

**Reasoning:** Confirmed via direct read of STA-006.3 §5.43 that Elevation, Altitude, and geometry Z are all on the same WGS84/HAE datum, just at different vertical reference points — so the chain reconciles consistent values rather than mixing datums.

### 30 — §7.2, 7.3, 7.4

**Decision:** RCL interpolation: proportional along actual vertex geometry, plus a configurable endpoint margin (GCS_RCL_ENDPOINT_MARGIN_M) that compresses the range onto a shortened path. Setback: configurable perpendicular offset (GCS_RCL_OFFSET_M), never on the line. Geocode response returns the matched feature’s actual geometry (Point/Point/Line by rung; future Polygon/Prism), not a synthesized uncertainty shape. Confidence/uncertainty value still carried on both interfaces, per RFC 7459.

**Reasoning:** The margin avoids deriving position/offset from geometry near a joint where perpendicular direction is unstable. Returning true geometry replaces synthetic uncertainty shapes with an honest representation of what was actually matched — rung 3’s line-instead-of-point is itself the uncertainty signal.

### 31 — §7.4, 3.9.2, 6.5

**Decision:** Confidence resolves as the three-field quality model: matchScore (per-field breakdown), locationType (ordered geometry-class tier), and confidence derived as matchScore × tier ceiling (100/90/80/75/50), populating the RFC 7459 element on both interfaces. GCS_MIN_MATCH_SCORE floors admission; default ranking is by blended confidence.

**Reasoning:** Industry research (Esri, Google, HERE, Pelias, Bing, AWS vs. PostGIS Tiger) shows a two-axis consensus: match quality and positional precision are orthogonal, and the one blended-single-number design is the least informative. The derived dial preserves the earlier score-times-ceiling intent as a convenience computed from the primaries, never stored independently. Tiers keyed to geometry class rather than rung number extend to SPACE_3D/FOOTPRINT_2D without renumbering; the currently reachable maximum of 80 is a deliberate statement about the missing data layers.

### 32 — §7.5

**Decision:** Space “centroid” = footprint centroid for X/Y, vertical midpoint for Z — not the solid’s volumetric centroid.

**Reasoning:** Volumetric centroids of irregular spaces drift toward taller portions and can exit the occupiable area. Footprint-plus-midpoint keeps the horizontal answer identical across the 2D-to-3D data graduation and makes the Z half exactly the quantity §3.7.3 reasons about.

### 33 — §8.3

**Decision:** PIDF envelope: echo the input entity attribute where present; generate a HELD-style unlinked pseudonym where absent (RFC 5985 §6.6, RFC 6753 §6.2). retransmission-allowed passes through unchanged.

**Reasoning:** The IETF solved the producer-without-presentity problem for the LIS; the GCS additionally holds an input whose entity it can honestly preserve — ownership of the location is unchanged by transforming its representation. The GCS never acts as Rule Maker, and i3 notes FEs normally ignore retransmission-allowed within the ESInet.

### 34 — §2.1, 3.6.2, 3.9.1, 8.1, A.1, 16

**Decision:** Normative YAML read and adopted as controlling per §2.8: one web service, one /Versions; GeodeticData naming; pidfLoAddress casing; referral via 307 Location header, no gcsReferralUri body field. Defects logged: text/YAML referral contradiction, content-type incoherence, 454 asymmetry.

**Reasoning:** The YAML supersedes the §4.5 text and answers the questions the text left open — and contains defects of its own worth showing NENA. Wrapper emitted as application/json, the only implementable reading of the declared schemas.

### 35 — §3.9.2, 2.2

**Decision:** Enhanced interface as sibling resources /GeocodeEnhanced and /ReverseGeocodeEnhanced on the same service, discovered via the /Versions vendor parameter.

**Reasoning:** Uses i3’s own sanctioned vendor-capability hook; leaves the strict paths byte-for-byte conformant; keeps one service (Q6) and one engine (§2.3); and makes the NENA-facing extension proposal expressible as a literal additive diff against the published v1 YAML.

### 36 — §4.1, 8.4

**Decision:** Schema validation failure returns 454 on both operations with a human-readable body reason.

**Reasoning:** 468 asserts a search occurred; 469 is undefined; 454 is the only remaining bucket. Applying it to both operations follows the YAML’s evident intent over its /ReverseGeocode omission. The deficiency itself is NENA-facing (§16).

### 37 — §9

**Decision:** ReverseGeocode accepts all eight RFC 5491 §5 shapes; a single search origin is derived from any of them by the §7.5 centroid convention.

**Reasoning:** i3 says only “a geodetic representation” and narrows nothing, so restricting to Point would add a restriction i3 does not impose — barred by decision 2’s corollary as firmly as adding capability. One origin means no shape-specific code paths.

### 38 — §7.4, 9, 10.6

**Decision:** §7.4’s rule that the GCS does not reason about input uncertainty is scoped to Geocode.

**Reasoning:** On the reverse side the input geometry is the query, so its extent is the substance of the question rather than metadata about it. Scoping the rule is preferable to leaving two settled statements in silent contradiction.

### 39 — §10.1, 3.7.2

**Decision:** One search pass, not two. Vertical selectivity and containment are terms in the candidate ordering, not gates in front of it. Revises decision 18.

**Reasoning:** Two passes allowed a candidate rejected by the first to be re-admitted by the second — the same redundancy decision 28 collapsed for scoring. Intent of decision 18 is preserved in the vertical band ordering; only the per-pass radius capability is surrendered.

### 40 — §10.2, 10.5

**Decision:** Single configurable maximum, GCS_REVERSE_SEARCH_RADIUS_M, in metres as true geodesic distance — not decimal degrees. 468 where nothing falls within it.

**Reasoning:** A degree is not a distance: longitude compression varies from ~100 km to ~36 km across the US scope, so a degrees radius is a latitude-dependent ellipse, and degree-space ranking would require an east-west neighbour to be ~1.45× closer in reality than a north-south one at Bismarck’s latitude — the CRS overruling the algorithm. EPSG:4326 fidelity belongs at storage and interchange; a degree bounding box remains an index pre-filter.

### 41 — §10.3, 10.4

**Decision:** Ordering is lexicographic: containment, then precision tier, then distance. Tier precedence applies only among contained candidates; where nothing is contained, nearest-by-distance regardless of layer.

**Reasoning:** Lexicographic ordering keeps the axes unblended, so distance is a tiebreaker within a tier rather than a competitor to it. A Point input contains nothing, so containment cannot govern the commonest input — containment is what licenses preferring precision, and absent it proximity is all that is known. A point 5 m from a centerline and 200 m from a structure is on the road.

### 42 — §10.5

**Decision:** Distance is measured to geometry as it exists; no nominal carriageway half-width correction. Vertical participation is lexicographic (band then horizontal), not weighted Euclidean.

**Reasoning:** Correcting the centerline bias would require inventing a road width STA-006.3 does not model, and the bias favours the more precise answer. A weighted metric would need a defensible k that no available data supports — the same objection. Raw distances travel on the enhanced interface so the closeness of the call is visible.

### 43 — §10.6

**Decision:** Reverse-side matchScore slot is filled by a spatial-fit score (normalised distance, containment at the ceiling, input-extent damping, additional damping for Placement Method = Geocoding). Extent damps the score only, never containment in the ordering.

**Reasoning:** There is no query address to decompose, so field similarity has no reverse analogue; the field, range, and breakdown shape are preserved with different components. Weakening containment is a no-op where all candidates are contained and actively wrong where the set splits — a candidate inside the caller’s stated circle is the better answer even at greater distance — and would need an unsupportable threshold constant.

### 44 — §11.2, 14.1

**Decision:** RCL reverse yields a synthesised house number, clamped to the segment range and forced to the side’s parity, inverted along the same margin-shortened path as §7.2.

**Reasoning:** The decision 12 objection — a computed value with no way to mark it computed — no longer applies: the value arrives tagged INTERPOLATED_POINT with ceiling 75 and a raw distance. “Approximately 1470 Highway 83” is actionable where “Highway 83, Burleigh County” is not. Path symmetry is required or §14.1’s rung-2 diagnostic fails by construction.

### 45 — §11.3, 14.1

**Decision:** Administrative elements come from the matched record’s fields, not point-in-polygon against boundary layers. Side of projection selects left/right attribution for RCL matches.

**Reasoning:** Follows §7.1’s precedent of a declared chain with no discrepancy report, and is required by §14’s round trip: a forward geocode matched the record’s fields, so reversing against a different source breaks the trip wherever attribution and containing polygon disagree. Attribution errors are the SI’s to fix, not the GCS’s to mask.

### 46 — §11.4

**Decision:** Sparse records are returned rather than skipped; elements with no source are omitted rather than emitted empty.

**Reasoning:** RFC 5139 gives an empty element no meaning. Skipping sparse records would have the GCS invent a completeness standard i3 never gave it and silently discard records the SI considers valid; a partial address still narrows a dispatch. The LVF/GCS divergence is NENA-facing rather than ours to resolve.

### 47 — §7.4, 16

**Decision:** §7.4’s “unreachable ceiling” claim corrected: FOOTPRINT_2D is reachable where an SI provisions the Recommended address polygon class; SPACE_3D remains unreachable.

**Reasoning:** Direct reading of STA-006.3-2026 shows Site/Structure Address Polygons (§4.2.2) and an Extent Method registry (§6.2) do exist. The NENA-facing point sharpens from “the model lacks the layer” to “the layer is optional, so precision varies by provisioning choice.”

### 48 — §7.2, 11.2

**Decision:** Zero-length RCL range (From = To) returns the segment midpoint on the matched side with setback applied, tiered INTERPOLATED_POINT. Single-address ranges collapse into this rule; no separate case.

**Reasoning:** The fraction is 0/0 and undefined, so a rule is required or an implementer invents one. The midpoint is what §3.7.3 prescribes when an address is known to be on a block but not where — it bounds worst-case error at half the segment. The reverse direction has no defect here and round-trips exactly, since any fraction maps back to the single asserted number.

### 49 — §7.2, 11.2

**Decision:** Parity governs side selection and reverse synthesis only; it never blocks a forward match whose number falls within the asserted range.

**Reasoning:** A caller asking for a number the data contains should receive it. A parity field contradicting its own endpoints is a data-quality defect belonging to the SI, consistent with the position taken in §11.3 and §11.4; the GCS does not repair records silently.

### 50 — §4.2, 9, 16

**Decision:** §4.2 follows i3 literally: RFC 5491 Rule #8 precedence elects one location; if it lacks the chunk the operation requires, 468. No error for multi-location requests. Enhanced interface reports the discard.

**Reasoning:** i3 §4.5 mandates one result from the first location, so rejecting multi-location requests would add a restriction i3 lacks (decision 2 corollary). Rule #8 supplies the ordering i3 omits. Walking past the elected location to find a better-typed one would infer intent the caller did not express; RFC 5491 Rule #7 also makes chunk order encode coarseness rather than relevance, so intra-element ordering cannot select type. The unsignallable discard is NENA-facing.

### 51 — §7.1, 3.7

**Decision:** Z-precedence chain (§7.1) admits a source only if it is non-null AND non-zero. Geometry Z of exactly 0.0 is treated as an unpopulated placeholder, not an asserted value, on the same basis as null. Chain falls through geometry Z → Altitude → Elevation under this test; if all three fail it, the response carries no Z, EPSG:4326.

**Reasoning:** On the provisioned dataset, geometry Z is uniformly 0.0 (present but synthetic) and Altitude is uniformly null, while Elevation holds real, non-zero data for 8.5% of records. The chain as originally written would report every address roughly 500 m underground rather than use the one source that actually carries information. Altitude and geometry Z are the same measurement per STA-006.3 §5.27 and §4.2.1 (both Height Above Ellipsoid), so treating a present-but-synthetic Z the same as a genuinely absent one is a consistent test, not a special case.

### 52 — §7.1

**Decision:** Horizontal position precedence (§7.1 extension): geometry wins over the Longitude/Latitude attribute columns on disagreement.

**Reasoning:** Mirrors the vertical chain's first term (decision 29). The provisioned SSAP layer carries Longitude/Latitude as separate attribute columns alongside the Point Z geometry with no stated rule governing disagreement between them; geometry is the more direct representation of the matched feature's position.

### 53 — §7.2, 11.2, 14.1

**Decision:** RCL geometry (§7.2, §11.2): single-part LineString is the normal case. A MultiLineString segment is a data-quality condition, logged via discrepancy reporting — not concatenated, averaged, or silently traversed in an assumed order.

**Reasoning:** The provisioned RoadCenterLine layer is MultiLineString Z, so a segment may be several disjoint parts with no specified traversal order, part boundary treatment for GCS_RCL_ENDPOINT_MARGIN_M, or stable left/right sense across parts. Guessing an order would make §7.2's forward interpolation and §11.2's reverse synthesis diverge silently, which breaks §14.1's round-trip guarantee by construction rather than by data quality. Most features are single-part; treating multi-part as an explicit, reported condition avoids inventing a traversal rule the standard does not supply.

### 54 — §6.3

**Decision:** GCS_AMBIGUITY_TOLERANCE_M is required with no specification-level default. The value is deployment-specific and lives in .env, not in this document.

**Reasoning:** §6.3 names no value and Appendix C item (a) does not list this among the deferred defaults, so there is no spec figure to fall back on. The choice is consequential in both directions — a tight value (city-block scale) pushes legitimate multi-structure matches to 468; a loose value approaching §6.3's own "forty miles apart" illustration merges cases that illustration exists to rule out. Picking silently would bury a real behavioural decision in a default; the deploying organization sets it deliberately per jurisdiction.

### 55 — §7.1, 3.7 (supersedes 51, 52)

**Decision:** Position on every axis comes solely from the matched feature's shape geometry. X and Y are taken from the geometry, never from the Longitude/Latitude attribute columns. Z is taken from the geometry where it carries a meaningful value and nowhere else: SiteStructureAddressPoint is a Z-geometry type, so every vertex has a Z slot, but a slot is not a value — a geometry Z of 0 is an empty slot, not an asserted height, and yields a 2D position (EPSG:4326) with no Z. The Altitude and Elevation attribute columns are not consulted for the returned coordinate. This supersedes decision 51's geometry Z → Altitude → Elevation fall-through and decision 52's geometry-over-columns framing: there is no fall-through and no competition, because the attribute columns are not position inputs. A record whose geometry is absent or unusable yields no position and cannot be returned as a located match; the condition is flagged as a data-quality defect (as with the decision 53 multipart flag), not repaired by reading the attribute columns.

**Reasoning:** The geometry is the authoritative representation of the feature's location, and STA-006.3 §4.2.1 states the geometry's Z corresponds directly to Altitude (Height Above Ellipsoid), so reading position from the geometry is reading it from the standard's own primary source. Decision 51's fall-through assumed the Altitude and Elevation columns were alternative Z sources to reconcile; they are better understood as transitional fields the SI may populate for other purposes, which the GCS may use later but does not treat as position inputs today. Decision 51's 8.5%-Elevation evidence is therefore no longer relevant to the coordinate returned: the geometry is authoritative even where an attribute column happens to hold data the geometry lacks. The non-zero test decision 51 established survives, narrowed to the geometry's own Z. Decision 52's Null Island concern (Longitude/Latitude of 0,0) is likewise moot, since those columns are not read for position.

### 56 — §7.2, 7.3 (resolves Q23)

**Decision:** A centerline segment too short to carry the endpoint margin — one whose usable length would be zero or negative after `GCS_RCL_ENDPOINT_MARGIN_M` is trimmed from each end (i.e. shorter than twice the margin) — returns the segment midpoint at INTERPOLATED_POINT, exactly as a zero-length range does under decision 48. The margin does not participate, and no proportional shrink or untrimmed interpolation is attempted.

**Reasoning:** This extends decision 48's rationale rather than introducing a new one. A segment this short cannot meaningfully distinguish positions along its length, and §3.7.3 bounds the worst-case error of a midpoint return at half the segment length — which is small precisely because the segment is short. The two rejected alternatives each cost more than they return: interpolating on the untrimmed geometry reintroduces the unstable-perpendicular-offset problem near joints that the margin exists to avoid; shrinking the margin proportionally invents a second rule with its own unstated constant. The midpoint needs no new constant and reuses machinery already present for decision 48. The case is called out separately from decision 48 only because it arises from a different condition (a short segment, not a single-address range) and §7.2 did not previously state it.

### 57 — §6.3, 7.4 (resolves Q25)

**Decision:** §7.4's prohibition on synthesising a Circle or Ellipse of uncertainty is scoped to single-match answers, where the matched feature's own geometry is the uncertainty statement and inventing an extent would assert precision that was never measured. The merged-candidate case of §6.3 is excluded from that prohibition: a merge measures a real extent across the qualifying candidates, so the merged answer returns a Circle centred on the averaged (centroid) position with radius equal to the greatest geodesic distance from that centroid to any merged candidate. Vertical extent, where present, is carried as a separate magnitude on the same basis. The geocode core emits the centre and the radius in metres (`MergedPosition.horizontal_uncertainty_m`); rendering the Circle as an RFC 5491 GeoShape is the wire layer's responsibility.

**Reasoning:** §7.4 and §6.3 are consistent in intent once the scope is made explicit: §7.4 objects to inventing an extent where none exists, and a merge is the one case where the service returns a position that is not any single feature's geometry and where an extent has genuinely been measured. A Circle centred on the average with a radius to the farthest merged candidate is the natural reading, and Circle rather than Ellipse is chosen because address-point merges on a shared parcel are approximately round in practice and a single radius matches what the code already carries; an Ellipse would add a second magnitude for a distinction that rarely arises. Keeping the shape choice at the wire layer preserves the separation the rest of the algorithm maintains between position computation and GeoShape serialisation.

### 58 — §1, 14 (supersedes 3, 25)

**Decision:** The GCS is specified as a standalone service. The LVF Algorithm Specification is retired as a reference document: the only remaining relationship to the LVF codebase is repository/folder structure and the shared i3-fe-core library, neither of which this specification needs to describe. Consequences applied document-wide: §1.5 removed; drafting notes that pointed at LVF v79 sections now state their requirements directly; Appendix C.1's LVF unread-source row removed; Q21 and Q24 reframed from blocked-on-reading-LVF to questions this specification answers on its own terms; §14 retitled. References to the LVF as an i3 functional element are retained where the text argues about the standards landscape — §16's gap rows, §11.2/§11.4's sibling-divergence arguments, §14's cross-element consistency claim, §A.3's logging-obligation comparison — because those are claims about i3's architecture, not about a reference implementation.

**Reasoning:** The GCS's element model, filter, and lifecycle behaviour are its own to specify; deferring any of them to a sibling document made this specification incomplete on its own terms and created false dependencies (Q24 read as blocked on an unread document when it was actually a decision available to make). Decision 3's shared-element-model framing and decision 25's source-code-reference framing both described a relationship that, in practice, reduced to folder structure and i3-fe-core — which the repository expresses and the specification need not. The distinction that survives is between the LVF as Jason's codebase (pruned) and the LVF as an i3 functional element (retained where the NENA-facing arguments require it): the gap register's claims — that i3 gave matchType to the LVF and not the GCS, that no consistency contract binds sibling elements provisioned from the same SI — are meaningless without naming the element.

### 59 — §10.3, 11.2 (resolves Q27)

**Decision:** RoadCenterLine candidates tier uniformly as INTERPOLATED_POINT for §10.3 ordering purposes, regardless of whether the projected side turns out to assert an address range. The tier reported on the answer is determined by §11.2 after projection and may therefore differ from the tier the candidate was ordered on: a segment whose projected side asserts no range is reported STREET_SEGMENT while having been ordered as INTERPOLATED_POINT. The search does not resolve side or ranges in order to tier.

**Reasoning:** §10.3's tier term and §11.2's tier determination are circularly dependent — a centerline's true tier is not knowable without projecting the origin, selecting the side, and reading the ranges, which is §11's work. The alternative, resolving that up front, collapses §11.2's front half into §10 and contradicts §10.1's one-pass structure, which exists precisely so that no second stage can readmit or reorder what the first produced. Ordering uniformly costs the narrow case Q27 identifies (within a contained group, a rangeless segment may outrank an interpolable one) and buys structural coherence; the exposure is bounded because tier participates only among contained candidates, so every Point input — the common case — is unaffected. Stating plainly that ordered tier and reported tier can differ is more honest than a second pass that would conceal the same circularity behind extra machinery.

### 60 — §10.5 (resolves Q26)

**Decision:** §10.5's vertical band is scoped explicitly to feature classes carrying a vertical extent, and it is stated in the text that no currently provisioned class does. A point Z is a slot, not a range; the band fires only on exact equality between the input's Z and a candidate's, which is not a case the provisioned data produces. The ordering therefore degrades to pure horizontal distance in every real case today, and the band is retained as forward-looking structure for the volumetric classes §7.4 anticipates. No vertical tolerance is admitted.

**Reasoning:** §10.5 as written reads as though the band does work, and an implementer will look for the case that exercises it. Saying so directly costs nothing and prevents a reader from inferring a defect where there is only an inert branch — §3.7.2 already predicts this outcome. Admitting a tolerance to make the band fire would reintroduce exactly the constant §10.5 declined when it rejected the weighted metric sqrt(h² + (k·v)²): no defensible default can be supplied from data that barely exists. This interacts with Q4 — a single radius serving both axes means the vertical component of the search constraint never binds either — which remains open.

### 61 — §6.2 (resolves Q24)

**Decision:** §6.2's progressive filter is removed. Every temporally-valid record in the searched layer is scored against the query on every request, and no record is excluded from scoring on the basis of any civic element — administrative, postal, place-name, street, or house number. §3.4's temporal filter is retained: it excludes records outside their Effective/Expire window, which is a correctness test rather than a narrowing one. `GCS_MIN_MATCH_SCORE` is retained: it applies after scoring and therefore discards nothing unseen. The section is retitled Candidate Set, the term "progressive filter" is retired, and Q24's filter-versus-scoring boundary question is dissolved rather than answered — there is no boundary, because there is no filter.

**Reasoning:** A filter exists to reduce scoring cost, and it pays for that reduction in accuracy: anything the filter excludes is excluded permanently, with no second pass, so every filtered element is one where a caller's typo or a record's own data defect produces a 468 rather than a low score. The service's priority is accuracy, not throughput, which makes that an unfavourable trade at any element list. The candidate lists considered before this decision each failed on the same point — strict administrative matching turns a misspelled county into a terminal failure; adding a fuzzy place-name tier to compensate requires a similarity constant no available data justifies, which is the objection §10.5 raised against `k` and §6.5 against its own formula; and a disjunctive A3-or-`Post_Comm` test narrows so little that it takes on miss-risk for almost no reduction. Scoring the full layer removes the failure mode entirely instead of managing it, and it is measurable: if full-layer scoring proves impractical at real request volumes, the evidence for where a filter earns its keep will exist, which it does not today. The decision also retires a dependency: §6.2 previously deferred its mechanics to a document outside this specification, and decision 58 made that deferral untenable.

### 62 — §3.10, 6.5, 11.1 (resolves Q21, part 1)

**Decision:** The engine's element model carries STA-006.3 column names throughout; translation to and from PIDF-LO `ca:` element names occurs once, at the wire layer, in both directions. The mapping is transcribed into §3.10 from NENA-STA-004.2-2024, which states it element by element as "CLDXF-US name (PIDF-LO name)"; STA-004.2 governs on any disagreement with the transcription. Columns with no PIDF-LO counterpart — `MSAGComm` and the `LSt_*` legacy street name fields, `AddCode`, `FloorIndex`, and a complete-form `Unit` where `UnitPreTyp`/`UnitValue` are carried separately — are neither emitted to nor populated from the wire, but remain available to §6.5 scoring where the record carries them.

**Reasoning:** Q21 recorded that the mapping "has to exist somewhere, and it is not in this specification," which was true of this document but not of the standards set: STA-004.2 supplies it, and §1.1 already pointed there. Transcribing it settles the question without authoring anything, and naming STA-004.2 as controlling means the transcription can be corrected against its source rather than becoming a competing definition. Keeping column names inside the engine and confining translation to the wire layer is what makes §11.1 a field-for-field copy rather than a second mapping table maintained in the reverse direction, and it keeps §6.5 comparing like-named fields. Appendix C.2 question 7 (packaging of the element model) is unaffected: what the model contains is now written down, where the code for it lives is still open.

### 63 — §3.10, 4.1, 6.5 (resolves Q21, part 2)

**Decision:** `Add_Number` is a non-negative integer, per STA-004.2 §3.3.3.5, which narrows RFC 5139's string typing; the CLDXF-US typing governs within this service's US-only scope. The wire layer decomposes a complete address number into `AddNum_Pre` / `Add_Number` / `AddNum_Suf` per STA-004.2 §3.3.4–§3.3.5 — `701B` yields `Add_Number` 701 and `AddNum_Suf` "B" — and preserves the caller's original form in `AddNum_Cmp`. Where a supplied address number cannot be reduced to a non-negative integer by that decomposition, the address number element is dropped, the request is admitted and proceeds without it, and the drop is reported on the enhanced interface. The request is not rejected.

**Reasoning:** The decomposition is STA-004.2's own rule and its examples cover the cases Q21 raised — "A" in "123A Main Street" and "123-A Main Street", "½" in "194-03½ 50th Avenue" — so no local convention is being invented; `AddNum_Cmp` exists precisely to hold what an integer cannot, including the leading zeros STA-004.2 §3.3.3.8 notes an integer cannot represent. Dropping rather than rejecting follows decision 61's posture: an element the service cannot use should cost precision, not candidacy, and a caller supplying a malformed house number still has a street name and administrative elements that can be matched. The consequence is stated rather than hidden — without a usable address number the answer degrades to a street-level match at rung 3 and `matchScore` reflects the absent element — and the enhanced interface reports the drop so that a caller receiving a segment can see why. Rejecting outright is defensible on the letter of CLDXF-US, but for an emergency service a hard failure on a recoverable input is the worse error. *Amended by decision 64: STA-004.2 §3.3.3.8's "enter 0" rule governs record authoring, not query interpretation, so no zero is substituted on the drop path.*

### 64 — §3.10, 4.1 (resolves Q28, amends 63)

**Decision:** STA-004.2 §3.3.3.8's instruction that "0" must be entered where a complete address number has no integer portion governs the authoring of a GIS record, not the interpretation of a caller's query. On the query path, decision 63's drop applies unchanged: an address number that yields no non-negative integer is dropped, the request proceeds without it, and the drop is reported on the enhanced interface. No zero is substituted. This carve-out is written into decision 63 rather than left to be inferred, since §3.10 makes STA-004.2 controlling and the literal reading would otherwise make decision 63's drop path unreachable.

**Reasoning:** The two sentences cannot both govern query interpretation: §3.3.3.8 requires "0" where there is no integer portion, and the same note warns that "zero should not be used to indicate there is no address number," offering 0 Prince Street, Alexandria as a valid address. The reconciliation is that the first sentence addresses a record author who must store some value in a non-nullable integer column, while a query has the option a record does not — to carry no address number at all. Substituting zero would convert "no usable number" into a search for a specific, real, different building, which is a wrong answer rather than a coarse one; dropping costs precision and degrades to the street-level match decision 63 already predicts. The distinction is worth reporting to NENA: §3.3.3.8 reads as a general rule and is stated where a reader looking for query behaviour would find it.

### 65 — §7.4, 8.1, 12.1 (resolves Q29)

**Decision:** RFC 7459 confidence is emitted on all four resources, strict and enhanced alike. §8.1's and §12.1's claims that the strict interfaces carry the converted form "and nothing else" are narrowed accordingly: they describe the `GeodeticData` and `CivicAddress` response objects, which gain no property, not the PIDF-LO payload those objects carry. §8.1's indistinguishability consequence is amended to say what survives — a coarse confidence, and nothing about why — and §16 gains a row recording that i3 says nothing about whether a GCS should populate the element at all.

**Reasoning:** §1.2.1's test is whether the service mints vocabulary. RFC 7459 confidence is IETF vocabulary defined for PIDF-LO generally and carried inside the location object, so emitting it adds nothing to i3's schema and leaves the strict paths conformant to the normative YAML. §7.4 and `schemas/confidence.xsd` already committed to populating it on both interfaces; the conflict was with prose written before that commitment, and prose is what yields. The narrowing is real rather than cosmetic: a fuzzy match now differs from an exact one on the strict interface by one coarse number, which weakens §2.2's controlled comparison slightly and is worth stating plainly instead of preserving a claim the implementation contradicts. That i3 leaves this optional — two conformant GCSs may differ on whether any quality signal reaches the caller — is a genuine gap and is recorded as one.

### 66 — §6.5, §10.6

**Decision:** Forward matchScore and reverse spatial-fit both compute a weighted average restricted to query-populated fields (renormalized by weight actually used), where each field's weight is base editorial weight × a discriminative factor measured from the currently loaded GIS layer (1 - max_frequency of that field's values, `src/gis/field_stats.py`, recomputed on every load/reload). Community/municipality is resolved via an A3 → A4 → Post_Comm → MSAGComm cascade before comparison, mirroring decision 55's resolution-chain shape.

**Reasoning:** A fixed weight table cannot distinguish a statewide deployment where Country and A1 are near-constant from one where they vary meaningfully, and guessing a fixed discount for "administrative fields are usually given" would be exactly the kind of unjustified constant §10.5 and §6.2 already declined to introduce elsewhere. Measuring the discriminative power directly off the provisioned data removes the guess without removing the field from consideration entirely — a border parcel that genuinely disagrees with the deployment's dominant state value still counts against a candidate that asserts it. Restricting the sum to query-populated fields (rather than scoring absence as a low similarity) is what makes an unsupplied county — the normal case per operational experience — cost nothing, consistent with §6.2's existing rule that `CivicAddress.populated()` reflects what the caller actually asserted. The community cascade reuses the same resolution-chain shape already settled for Z (decision 51/55) and horizontal position (decision 55) rather than inventing a new mechanism, and is forward-compatible with improving A3/A4 provisioning without a future spec change.

The base editorial weights themselves, the Geocoding-placement damping constant, and whether categorical fields (Country, A1, A2) should be compared by exact match rather than edit-distance similarity remain open — see the narrowed Appendix C item (d) and new Appendix C.4 questions below.

### 67 — §6.5, §7.2, §11.3

**Decision:** RCL forward scoring resolves a side hint from the query's Add_Number parity against the record's Parity_L/Parity_R where possible, independently of §7.2's geometric side selection (which scoring necessarily precedes). Where no side can be resolved — no Add_Number in the query, or the record's parity does not decide it — both sides are compared per element and the better similarity is kept.

**Reasoning:** Scoring happens before §7.2 interpolation picks a side geometrically, but the side is also derivable from the record alone via parity, so a query that supplies a house number can be compared against the correct side's administrative and postal attribution rather than an arbitrary or averaged one. This is this module's own judgment call rather than something §7.2/§11.3 already settled, and is recorded as such — see Appendix C.4 for the open question about whether §7.2/§11.3 should adopt this formally.

### 68 — §6.5, §10.6 (amends 66)

**Decision:** Two corrections to decision 66's mechanism, both found running the field-stats report against the real data.gpkg (78,237 SSAP / 19,703 RCL records). First, a minimum-population floor (`_MIN_POPULATION = 30` in `src/gis/field_stats.py`): a field measured against fewer than 30 populated observations reads discriminative_factor 1.0 (unmeasured) rather than a computed value, since single-digit populations (St_PosMod, Place_Type, RCL A4 in the current export) were producing a factor from a sample too thin to mean anything. Second, the A1 "border-parcel" scenario used to motivate the mechanism in §6.5 and in `field_stats.py`'s own docstring is corrected from an empirical claim to a hypothetical one: the real ND export carries A1 = "ND" on every record, zero variance, and the mechanism correctly discounts it to 0.0 — the same result as Country, not the intermediate case the illustration described.

**Reasoning:** The population floor is a sample-size judgment defensible from first principles (30 is a standard rule-of-thumb minimum), not a data-tuned constant like `_BASE_WEIGHTS` — it belongs alongside decision 66 rather than in Appendix C item (d)'s list of things still needing real tuning. The A1 correction matters because the mechanism's justification should not rest on an anecdote the actual deployment contradicts: the design is still sound — it measured reality instead of trusting the assumption, and reported the true answer — but the illustration needs to say so rather than assert a scenario that isn't present in this data. Whether the deployment is genuinely single-state or the export simply excludes adjoining counties is unresolved and does not need to be, since the mechanism's behavior is correct either way.

### 69 — §6, §6.5 (amends 61, 66)

**Decision:** SSAP (rung 1) candidates must match the query's Add_Number exactly to be considered at all — a hard gate in `ssap_candidates()`, applied before scoring, when the query supplies a house number. Add_Number is removed from §6.5's weighted average entirely (it would only ever contribute a constant among survivors) and reported in the matchScore breakdown as a fixed 100.0 for transparency. Road interpolation (RCL, rungs 2/3) is unaffected — it was never scored on Add_Number similarity and already uses §7.2's range/parity containment, a correctness test rather than a similarity comparison.

**Reasoning:** Building the tests/requests sample set surfaced that the general-purpose edit-distance similarity (decision 66) scores short house-number strings as falsely close — "415" and "416" at ~67% similar — which, at Add_Number's highest editorial weight, was pulling wrong-address candidates in from across town and spreading the surviving set past GCS_AMBIGUITY_TOLERANCE_M, producing exactly the silent-468 failure mode decision 61's own rationale warns a filter can cause — just triggered by false similarity rather than a missing record. House number is not a field where "close" is meaningful the way a street-name typo is: 415 and 416 are different buildings, not a fuzzy version of the same one. This is decision 31's principle (default ranking by blended confidence, so a shaky match ranks below a trustworthy one — "precision that cannot be trusted is a dispatcher sent to the wrong building," §7.4) taken to its conclusion for an identity field rather than applied as a rank penalty. Decision 61's general "no filter" policy still holds for every other civic element; this is a single, named, justified exception rather than a reversal.

### 70 — §3.3, 6.1 (amends 15, follows from 31 and 69)

**Decision:** The rung a response answers from is selected by comparing each rung's best candidate on blended confidence (§7.4), not by taking the first rung that produced any candidate. The response still carries exactly one rung's candidates — rungs are not blended (decision 15 stands on that point). Rung 1 ends the search without scoring the RCL layer when its best candidate's confidence reaches the INTERPOLATED_POINT ceiling (75, i.e. matchScore ≥ 93.75), since no road answer can exceed that; otherwise rungs 2 and 3 are computed and the rung with the highest best-candidate confidence wins, ties resolving to the more precise rung.

**Reasoning:** Live testing against the Bismarck data surfaced the failure: a query for 2800 Del Rio Drive, where 2800 exists only as a road-segment range (the street's address points jump 2728 → 2801), returned thirty-nine wrong-street address points and never mentioned Del Rio. Decision 69's gate checks identity on one field, so every address point in the deployment numbered 2800 survives to rung 1; with GCS_MIN_MATCH_SCORE set low, that rung is non-empty on house-number coincidence alone, and the previous existence test handed it the response before the exactly-matching segment — range and parity included — was ever scored. §7.4's own rationale (decision 31) already names the correct arbiter: default ranking is by blended confidence precisely so that a shaky point match ranks below a perfect street match, and the tier ceilings (ADDRESS_POINT 80, INTERPOLATED_POINT 75, STREET_SEGMENT 50) already price the precision difference between rungs. Letting the rungs compete on that same measure extends the principle across the rung boundary instead of stopping it at rung 1's edge: a genuine address-point match (100 × 0.8 = 80) still beats its own street's perfect interpolation (75), so nothing regresses for well-provisioned addresses, while a coincidental house-number survivor (45 × 0.8 = 36) loses to the road match (75) it was previously allowed to shadow. The dominance short-circuit preserves decision 61's performance posture for the common case — an exact address point on file still skips the full-layer RCL scan entirely. The alternative of raising GCS_MIN_MATCH_SCORE was rejected as the primary fix: it is a global floor that would have to be tuned to sit above every coincidental-survivor score and below every legitimate fuzzy match, a constant no available data justifies (the same objection §6.5 and §10.5 raised against their own constants), and it manages the failure rather than removing it.

### 71 — §6.5 (amends 28 and 61, follows from 70)

**Decision:** When both the query and a record assert a street name, the record qualifies as a candidate only if the names are phonetically equivalent (Soundex) or reach a minimum edit similarity (0.5, a strawman constant alongside §6.5's others). A record failing both keys has its matchScore forced to 0.0 — below any positive GCS_MIN_MATCH_SCORE — with the per-field breakdown still computed and reported, so the disqualification is observable at a floor of 0 rather than silent. Either side missing a street name leaves the candidate unaffected: sparseness costs score, not candidacy. Street name only; no other field gains a qualification gate without evidence from testing.

**Reasoning:** Decision 70 fixed which rung answers, and live testing then showed the surviving list itself was misleading: a query for Del Rio Drive returned El Paso Drive and Powder Ridge Drive as scored candidates, because the fields every record in town shares (street type, community, county) scored 100 and carried names that are not remotely the street the caller typed. That is not a ranking problem — the wrong-street candidates ranked below the right one — it is a roster problem: showing them at all asserts they are plausible readings of the query, and they are not. Production geocoders resolve this at candidate retrieval: the PostGIS TIGER geocoder looks up candidate streets through a Soundex-indexed name match (its documentation's own example: 'Hiland' does not match 'Highland' because the codes differ), and uses edit distance to rank only what qualified. The two-key test transplants that shape without PostGIS's false-negative exposure: Soundex alone rejects sound-breaking typos (a wrong first letter changes the code's literal first character), so edit similarity is an alternate key, not a tiebreaker — "Del Reo" qualifies phonetically, "Fel Rio" qualifies on similarity, "El Paso" fails both. Scoring stays a Soundex/edit-distance blend rather than going Soundex-only, which was considered and rejected: Soundex is binary and would erase ranking granularity among qualified candidates, and it degenerates on numbered streets. This is the third named exception to decision 61's no-filter posture, after temporal validity and decision 69's house-number identity, and it is justified the same way: for street identity, "close" has a real boundary, and past it a candidate is not a worse match but a different answer. Unlike decision 69's gate it lives in scoring (src/engine/scoring.py) rather than candidate identification, because deciding what counts as "the same street" requires the similarity primitives, which are §6.5's proprietary-tuning territory.

### 72 — §6.5 (amends 28 and 66; chronologically precedes 70 and 71)

**Decision:** `_normalized_similarity` blends normalized edit-distance similarity with a binary Soundex comparison, equally weighted, for free-text name fields (Street Name, Street Type, Street Direction, Community, County). An exact match after normalization short-circuits at 1.0 before either measure runs, preserving decision 28's exact-is-the-ceiling property. Country and A1 opt out of the blend (`phonetic=False`) and remain pure edit distance: they are 2-3 character controlled-vocabulary codes, not hand-typed names, and Soundex on a two-letter token is meaningless. A token with no letters (or either side empty after normalization) falls back to edit distance alone rather than fabricating a phonetic code. Recorded out of sequence: this change landed in the same live-testing session as decisions 70 and 71 and preceded both — decision 71's qualification gate reuses these same two measures as its two keys.

**Reasoning:** The first live test against the Bismarck data showed pure Levenshtein similarity overcrediting short, coincidentally-similar names: "Del Rio" vs. "El Paso" at 42.9% and vs. "Powder Ridge" at 41.7%, despite sharing no meaningful sound with either. That inflation sits inside the field score itself, so no reweighting of `_BASE_WEIGHTS` can compensate — doubling Street Name's weight moved the wrong candidates' matchScore by about two points. Edit distance answers "how many keystrokes apart" and Soundex answers "does it sound like the same word"; a candidate street should need at least partial credit on both to score as a plausible reading of the query, which the blend enforces — the El Paso field score fell from 42.9 to 21.4. Replacing edit distance with Soundex outright was rejected: Soundex is binary (all qualified names would tie, erasing ranking granularity), codes the first letter literally (a single wrong first letter zeroes a legitimate typo), and degenerates on numbered streets. The blend applies to every hand-typed field rather than Street Name alone because the failure mode — false similarity between short unrelated tokens — is a property of the strings, not of the field; the Country/A1 carve-out follows the opposite logic of the same principle, since a controlled code is never a misspelling. This narrows decision 28's "one mechanism" from one formula for every field to one formula per input character: hand-typed text gets the blend, controlled codes get edit distance, and Q30's exact-match question for categorical fields remains open on top of it.

### 73 — §6.5 (amends 71 and 72)

**Decision:** Street-name comparison tokenizes into a leading digit run and a trailing letter suffix whenever either side of the comparison begins with one or more digits ("22nd" → digits "22", suffix "ND"). If either side is digit-leading, the digit runs must match exactly for the candidate to qualify at all — an identity gate in the shape of decision 69's house-number gate, not a similarity term — and Soundex is never consulted for a digit-leading token. Once the digit gate is passed, the letter suffix is compared by edit-distance similarity alone (no Soundex) against decision 71's qualification threshold. A token where neither side is digit-leading (e.g. "Third", "Thirteenth") is unaffected and continues through decisions 71/72's existing Soundex/edit-distance blend unchanged.

**Reasoning:** Investigating a sample-set outlier ("802 12th Avenue NW" vs. "802 1st Avenue NW", matchScore 56.5, clearing this deployment's threshold) found both the qualification gate and `_soundex()` implemented correctly against decisions 71 and 72 as written — the defect is that Soundex has no representation for digits at all, a property of the classic algorithm itself (it strips non-alphabetic characters before coding), shared by every standard implementation, not a bug in this one. Two failure patterns followed from that gap. First, digit-leading tokens with differing digits but similar overall length pass the edit-similarity key on raw character overlap alone — "1st"/"12th" lands exactly on the 0.5 threshold — producing a low but non-zero, non-gating score for a genuinely different street. Second and more severe: ordinal pairs whose only difference is the digit run share an identical Soundex code, since Soundex only ever sees the surviving letters — "2nd" and "22nd" both reduce to "ND" — and qualify through the phonetic branch with full credit, producing higher confidence for the wrong street (92.75) than the flagged case ever reached (56.5). Neither pattern is visible to the existing 250-pair tuning sample (tools/sample_pairs.py), because its far-miss donor selection deliberately picks a different-Soundex donor to test the edit-similarity branch, which by construction excludes exactly the cases where the Soundex-match branch itself is the leak.

A digit-leading street name is identity-bearing in the same sense Add_Number is (decision 69): "2nd" and "22nd" are different streets, not a fuzzy version of one, and no accumulation of "close" language applies to the digit itself. But unlike a house number, a digit-leading street name also carries a letter suffix a caller can genuinely mistype ("1st" typed as "1ts", a transposition) — so an outright exact-match gate on the whole token was rejected as overcorrecting: it would wrongly disqualify a legitimate typo alongside the genuine mismatches. Splitting the token preserves decision 69's identity-gate reasoning for the digit, which deserves it, while preserving decision 71's typo tolerance for the suffix, which still needs it. Excluding Soundex from the suffix comparison follows decision 72's own carve-out logic for Country/A1: a two-to-three-character token (ST/ND/RD/TH) is too short for a phonetic code to mean anything.

### 74 — §6.5 (amends 72, 73)

**Decision:** Replace the plain Levenshtein edit-distance primitive used throughout `_normalized_similarity` (and decision 73's digit-leading suffix comparison) with a transposition-aware variant — Damerau-Levenshtein restricted to adjacent transpositions only (the cheaper "optimal string alignment" form), where swapping two adjacent characters counts as a single edit rather than two. Applies everywhere edit distance is used: the free-text Soundex/edit-distance blend fields (Street Name, Street Type, Street Direction, Community, County), decision 73's suffix comparison, and the pure-edit-distance categorical fields (Country, A1). The change is confined to the distance primitive itself — qualification thresholds, blend weights, Soundex logic, and decision 73's digit-identity gate are all unchanged.

**Reasoning:** Decision 73's own motivating example — "1st" mistyped as "1ts" — was implemented and tested, and the suffix comparison still disqualified it: plain Levenshtein charges an adjacent-key transposition as two edits (delete+insert, or two substitutions) rather than one, so "ST" vs "TS" scored 0% similarity, not "close." The fix is not specific to the digit-leading path: the same primitive underlies every edit-distance comparison in the file, so an ordinary alphabetic street name with a transposed letter pair ("Sait" vs "Sati") would take the identical unwarranted penalty. Restricting the fix to adjacent-only transpositions, rather than full Damerau-Levenshtein's arbitrary-distance transpositions, keeps the change cheap and keeps its scope matched to the actual typo class motivating it — a real transposition typo swaps two keys next to each other. The similarity ordering is preserved rather than collapsed: a transposition still costs strictly more than an exact match and is still ranked below one — the metric is more accurate, not more permissive, so a candidate found via transposition tolerance is not treated as equal to a perfect match, only scored closer to it than an unrelated pair of substitutions would be.

### 75 — §6, §6.5

**Decision:** SSAP candidates with a query-supplied unit value must match the candidate's own UnitValue exactly (normalized) to qualify — a hard gate in candidate identification, mirroring decision 69's Add_Number gate — EXCEPT that a candidate carrying no unit at all is exempt from the gate and proceeds to scoring normally (decision 61's sparseness posture), rather than being excluded for lacking something the query asked about. UnitPreTyp is not part of the gate. UnitValue takes no part in the weighted average, the same treatment as Add_Number.

**Reasoning:** Investigation traced a real response-path consequence of Unit never being read anywhere in scoring: at addresses with multiple units on file (85%+ of unit-bearing addresses in the provisioned data, up to 397 units at one address), every unit ties at identical matchScore regardless of which unit — or none — the query specified. Where those units' real coordinates are tightly clustered (within `GCS_AMBIGUITY_TOLERANCE_M`), decision 57's merge machinery fires and returns a confident-looking single response — `confidence` unchanged from an unambiguous match — silently averaged across every unit at up to ~38m from the actual requested unit's position, with no signal to the caller beyond a Circle-shaped geometry a consumer must know to check for. Where units are spatially dispersed beyond the tolerance, the system already fails honestly (468) — that path is not a gap and decision 57's merge machinery is not being extended to cover it; the tight-cluster case is the one this decision closes. The Add_Number gate's exact-identity reasoning (decision 69) transfers directly: two different unit values at one street address are two different answers, not a near-miss of each other. The sparseness carve-out is the point of departure from decision 69 rather than a copy of it — Add_Number is populated on essentially every SSAP record, so decision 69 never needed to consider a record silently lacking one, but 85%+ of records here have no unit at all and are ordinary single-unit addresses; gating those out whenever a query happens to include a unit would wrongly disqualify the common case rather than the ambiguous one decision 61 already governs this distinction for.

### 76 — §6.5 (amends 66)

**Decision:** Two corrections to the Community cascade. First, MSAGComm is dropped as the cascade's fourth tier; the cascade shortens to A3 → A4 → Post_Comm, first populated wins. Second, the discriminative-factor lookup driving the Community term's weight (in both score_ssap and score_rcl) now follows whichever cascade field actually resolved that record's comparison value, rather than a single field hardcoded regardless of which tier produced the value — previously `f("A3")` unconditionally in score_ssap and `f("Post_Comm")` unconditionally in score_rcl.

**Reasoning:** Investigating the persistent wrong_community false-positive signal (unmoved by decisions 73-75 and unresponsive to raising `_BASE_WEIGHTS["Community"]` alone) surfaced that the weight discount itself was structurally mismeasuring a large share of records. On SSAP, 21.8% of records (17,028 of 78,237) resolve their Community value from Post_Comm — because A3 is empty for 22.0% of records and A4 only ever populates in that same empty-A3 population — yet were being discounted against A3's discriminative factor (0.3268) rather than Post_Comm's own (0.3752). RCL is worse in the same way but inverted: roughly 52.8% of records per side resolve from A3, not Post_Comm, yet score_rcl discounted all of them against Post_Comm's factor (0.6115) rather than A3's own (0.4669) — a majority-of-records mismatch, not an edge case. Measuring the correct field's factor per record is a direct application of decision 66's own founding principle (measure the deployment rather than assume it) to a case decision 66 did not anticipate: a cascade means the "the field" being compared is not fixed across records, so the statistic describing its variability cannot be fixed either. Dropping MSAGComm is separately justified on the evidence gathered investigating this: it is reached by exactly 1 SSAP record (of 78,237) and at most 1 RCL record per side (of 19,703), consistent with Post_Comm's near-universal population; removing it costs one record's Community comparison (which falls to unscored, per decision 61's sparseness posture, rather than producing any wrong result) and eliminates reliance on a legacy pre-NG9-1-1 field this GCS does not otherwise use.

### 77 — §6.5 (follows from 76)

**Decision:** Community becomes a qualification gate, in the same shape as decision 71's street-name gate: when both the query and a candidate's decision-76-resolved Community value are populated, the candidate is disqualified (matchScore forced to 0) unless the two names are phonetically equivalent (Soundex) or reach a minimum edit similarity. That threshold is a new, independent constant — `_COMMUNITY_QUALIFY_MIN_EDIT_SIM`, strawman 0.5 — not a reuse of `_STREET_QUALIFY_MIN_EDIT_SIM`. A candidate with no resolvable Community value is not disqualified: sparseness costs score, not candidacy (decision 61), the same carve-out already established for decision 75's Unit gate.

**Reasoning:** Both levers available to a purely weighted treatment of Community were tried in sequence on this deployment's real data and both were measured, not assumed, insufficient: raising `_BASE_WEIGHTS["Community"]` to more than three times its original value left wrong_community at 100% clearing GCS_MIN_MATCH_SCORE (mean only dropped from 92.42 to 79.57, still 19.6 points clear of the 60.0 floor at every value tried); decision 76's discriminative-factor correction — a real, independently-verified fix — also left it at 100% clearing (mean 92.18), because this deployment's A3 and Post_Comm discriminative factors happen to sit close together (0.3268 vs. 0.3752), leaving little for a corrected field-lookup to exploit. This is the identical evidentiary shape decision 71 already resolved for street name: a field every candidate in a local search tends to share (decision 71's own example — every record in a town scores Community/street-type/county at 100 regardless of which street was asked for) cannot be fixed by reweighting alone, because reweighting only ever redistributes emphasis among fields that are, in aggregate, still describing "the same town" for every candidate under consideration. A wrong community is the same kind of identity fact street name already proved to be — a different place, not a lower-confidence version of the right one — and decision 71's own gate mechanism (disqualify below a similarity floor, no reliance on Soundex alone given its known degeneracies, matchScore forced to 0 with the per-field breakdown still reported) transfers without modification. The threshold gets its own constant rather than sharing decision 71's because the two fields have no shared evidentiary basis for a common value: this deployment's community names are a small, repetitive, short-token vocabulary (a few hundred ND town names) with a different real-world confusion pattern — a caller is more likely to state a genuinely different nearby town than to typo the one they meant — than street names draw from, and assuming one threshold suits both would be exactly the unjustified-shared-constant problem §6.5 and §10.5 already argue against elsewhere in this document.

### 78 — §6.5 (diagnosed, deprioritized)

**Decision:** A2 (County) is diagnosed as the same structural shape as decision 77's original Community fix — discriminative factor ~0.32, comparable to A3's pre-correction number, meaning a purely weighted treatment would face the same reweighting-can't-fix-a-shared-value problem. A qualification gate mirroring decision 71's street-name gate is NOT built for A2. A2 remains an ordinary decision-66 weighted-average field: scored whenever the query supplies it, contributing nothing when unsupplied, never excluding a candidate beyond what the weighted average already costs it.

**Reasoning:** Unlike Community, A2 is rarely the caller's primary identifying element — operational experience is that callers lead with a street address, a community name, and sometimes a state, not a county. Decision 66's `populated()` restriction already means A2 only enters scoring when supplied, so the exposure to a mismeasured A2 is small in practice regardless of gate or no gate. Building and maintaining a second gate (its own threshold constant, its own qualification logic, its own test coverage) is not justified against a field with low query-population frequency. If usage patterns are later found to differ from this assumption, this diagnosis is preserved here to resume from rather than re-derive.

### 79 — §6.5 (measured, deprioritized)

**Decision:** St_Type is evaluated for the same weight-increase fix that failed for Community/A2, using a real sweep against the wrong_st_type variant (250 pairs, donor selected to differ from the target in both normalized form and Soundex, same construction as decision 71's street-name gate test). A qualification gate mirroring decisions 71/77 is NOT built for St_Type. St_Type remains an ordinary decision-66 weighted-average field at its current base weight (12.0).

**Reasoning:** The sweep (`_BASE_WEIGHTS["St_Type"]` at 12.0/18.0/24.0/30.0/36.0, all else held constant) found true-match mean flat at 100.0 throughout — reweighting a single field cannot move a score where every other term already matches exactly, since the weighted average of all-1.0 terms is 100.0 regardless of how weight is distributed among them. wrong_st_type mean fell only from 83.52 to 63.36 across the full swept range, and even at 3x the current weight (36.0), 87.2% of wrong-street-type non-matches still cleared GCS_MIN_MATCH_SCORE (60.0) — confirming St_Type has the same reweighting-is-futile shape as Community/A2, not the "ordinary under-weighting" shape session 6 initially diagnosed. Unlike Community, however, a gate is not the right fix here either: a mismatched street type is materially more likely to reflect genuine user uncertainty or cross-source labeling inconsistency ("Elm Ave" typed for "Elm St," same address) than a mismatched community or street name is — a caller is more likely to guess wrong on a suffix type than to misname the street or town entirely. Gating St_Type would reject exactly the caller behavior it needs to tolerate, so St_Type is left weighted, with the acknowledgment that a materially-wrong type will still often clear the admission floor and rank near a true match — an accepted tradeoff given the alternative (a gate) would produce more false rejections than it prevents false admissions.

### 80 — §6.5 (supersedes 77)

**Decision:** Community's hard qualification gate (decision 77) is reverted. Community returns to decision 76's ordinary weighted-average treatment. In its place, a bounded-penalty mechanism is added: when a candidate's Community value fails decision 77's original qualification test (not Soundex-equivalent to the query's resolved Community AND below `_COMMUNITY_QUALIFY_MIN_EDIT_SIM`), the Community term's similarity contribution is clamped to `_COMMUNITY_MISMATCH_SIMILARITY_CAP` — as a ceiling (`min()`), never an assignment, so a non-qualifying pair the blend already scored lower keeps its lower value — overriding whatever the natural Soundex/edit-distance blend computed above that ceiling. A qualifying Community is scored normally and is unaffected by the cap. On RCL, the cap is applied after §7.2 side selection, so side choice runs on the uncapped blend and the cap decision, the reported score, the weight, and the field lookup all stay committed to the same side. `_COMMUNITY_MISMATCH_SIMILARITY_CAP` is set to 0.15 (see Reasoning) — a placed, not chosen, value in the same strawman posture `_COMMUNITY_QUALIFY_MIN_EDIT_SIM` originally held under decision 77.

**Reasoning:** Decision 77 was built on the assumption that a wrong community reliably signals a wrong address, the same assumption that justified decision 71's street-name gate. Reconsidering the caller's actual search behavior surfaces a real case that assumption doesn't cover: a caller confident of the street address but unsure of the administrative community name — for example, a caller who states "Lincoln" for an address actually in Bismarck, not merely a near-miss of an adjacent name — will sometimes name the wrong town without being wrong about the address itself. A hard gate disqualifies that caller's true match entirely; a caller in this position should instead see the correct address returned, ranked appropriately below any candidate whose community also matched, not excluded. This is the same tension identified in decision 79 for St_Type, applied to Community: the field's mismatch is not a reliable proxy for "wrong address," so an identity-style disqualification is the wrong tool.

A dedicated sweep (`tools/community_cap_sweep.py`, 250 wrong_community pairs, cap values 0.0/0.15/0.30/0.50) was run to select the cap value and returned a negative result the decision record should state plainly: **the cap mechanism cannot deliver a materially lower wrong_community score at any value.** Even at cap 0.0 — a wrong-community candidate contributing literally zero on that term — the mean wrong_community score was 91.63, and 100% of the 250 pairs still cleared `GCS_MIN_MATCH_SCORE` (60.0). Moving the cap from 0.0 to 0.50 shifted the mean by only 0.55 points (91.63 → 92.18), because Community is one term of a renormalized seven-term average and the other six terms score 100 in a wrong_community pair by construction — zeroing one term of seven still leaves roughly six-sevenths of the ceiling. The 0.30 and 0.50 sweep rows are arithmetic no-ops rather than informative data points: the uncapped non-qualifying-Community similarity in this sample never exceeds 0.2143, so any cap at or above that value never actually clamps anything. A second finding narrows the mechanism's reach further: 50 of the 250 wrong_community pairs are real different ND towns that nonetheless pass decision 77's own qualification test (Soundex collision or sufficient edit similarity) — no cap value, however aggressive, can affect a pair the qualification test itself does not flag as mismatched.

Given this, the cap is retained rather than removed — it is a genuine, verified improvement in *kind* over decision 77 (a caller who names the wrong adjacent town due to genuine uncertainty is no longer categorically excluded, which was this decision's actual goal), and 0.15 is set as its value because the sweep shows no value in the tested range does meaningfully better or worse within the range that actually clamps anything (0.0 vs 0.15 differ by 0.02 points of mean). What the cap does **not** deliver, and what a future reader should not assume it delivers, is a wrong_community score meaningfully closer to `GCS_MIN_MATCH_SCORE` than a true match — that would require a mechanism operating on the whole matchScore after the weighted average (a multiplicative penalty applied post-average, rather than a per-term clamp folded into it), which this decision does not implement and which remains open — see Appendix C item (d).

### 81 — §6.2, §6.5 (resolves Q30 for A1/Country)

**Decision:** A1 and Country each become a per-field, exact-match, pre-scoring candidate-set gate — the same shape as decision 69's Add_Number gate, extended to apply on both SSAP and RCL rather than SSAP alone. Where the query supplies A1, only candidates whose A1 matches exactly (trim/casefold normalized, no edit distance or Soundex) survive into the candidate set; Country gates independently on the same terms. Either, both, or neither may fire depending on what the query supplies — the two fields are not coupled, and an unsupplied field's gate simply does not activate (decision 61). Both fields are removed from `_BASE_WEIGHTS` and take no further part in the weighted-average matchScore; per decision 69's transparency precedent, a gated-and-passed candidate still reports `A1: 100.0` / `Country: 100.0` in the i3-improved breakdown. A2 (County) is explicitly excluded from this decision and remains under decision 72's Soundex/edit-distance blend, the same treatment as A3/Community — County is hand-typed by a call-taker, not selected from a short constrained list the way A1/Country effectively are, so it does not share the identity-field reasoning below.

**Reasoning:** A1 and Country are controlled-vocabulary codes (ISO 3166-2/USPS state abbreviations; ISO 3166-1 country codes) that a caller does not spell out character-by-character the way a street or community name is spoken and mistyped — decision 72 already recognized this by excluding both from the Soundex half of the free-text blend, but left them scored by edit distance alone, which still credits partial overlap a controlled code shouldn't receive (`A1="SD"` against a record's `A1="ND"` scoring 50% rather than 0%, purely from one shared character). A wrong state or wrong country is not a near-miss of an intended one; it is a different jurisdiction, the same category of error Add_Number's gate (decision 69) and UnitValue's gate (decision 75) already treat as identity-disqualifying rather than similarity-scored. Extending the gate to RCL as well as SSAP (unlike Add_Number, which is SSAP-only) reflects that A1/Country identity is a property of jurisdiction, not of the address-range interpolation mechanics Add_Number's gate is specifically scoped to — a road-interpolated candidate in the wrong state is exactly as disqualifying as an SSAP one.

A2 was considered for the same treatment and declined: unlike A1/Country, County is not drawn from a short list a caller either states correctly or doesn't — it is a hand-typed name a call-taker spells out, subject to the same misspelling and phonetic-confusion patterns as Community or Street Name, and decision 72 already classed it accordingly. Decision 78 separately found a hard gate on A2 not worth building on cost/benefit grounds even before this identity-vs-free-text distinction was drawn; this decision confirms A2's blend classification on a different basis (categorical vs. free-text) that reaches the same conclusion. This resolves Appendix C.4 Q30 for A1 and Country; A2's status under Q30 is now settled as "blend, not exact-match," rather than open.

Direct verification against the currently loaded ND export (decision 68) found A1 uniformly "ND" with no variation at all; Country is presumptively uniform "US" on the same basis, though not separately reverified here. In this deployment, therefore, neither gate is expected to disqualify any candidate in practice — a query-supplied A1/Country will, barring data entry error, always match every record. This decision is groundwork for portability to a multi-state or cross-border deployment rather than a behavior change in the currently loaded data.

### 82 — §6.2, §6.5 (supersedes 81; closes Q30 and the St_Dir question)

**Decision:** Comparison mechanisms are settled as three classes, and every civic element is assigned to exactly one. (1) **Identity gates**, unchanged: Add_Number (decision 69) and UnitValue (decision 75). (2) **Controlled-vocabulary binary terms**: St_Dir, A1, Country — exact match after normalization (the existing `_DIRECTIONAL_EXPANSIONS` table for directionals; trim/casefold for A1/Country) scores 1.0, anything else 0.0; weighted terms, never gates, no edit distance, no Soundex. (3) **Hand-typed name blend**, unchanged: St_Name, St_Type, Community, A2 under decision 72. St_Dir stays a single weighted term spanning both St_PreDir and St_PosDir, compared best-of-both-sides, so a pre/post position swap ("Main Street North" for "North Main Street") scores full credit; a genuinely wrong directional zeroes the term — a bounded ranking penalty (~10 points maximum against a perfect score at current weights), not an exclusion. Decision 81's A1/Country candidate-set gates are reverted before any implementation; both fields return to `_BASE_WEIGHTS` as ordinary weighted terms with the binary comparison.

**Reasoning:** Three findings converged. First, measured against the live similarity code, the Soundex/edit-distance blend is actively wrong on closed vocabularies: "NE" vs. "NW" scores 0.889 — NORTHEAST and NORTHWEST are edit-similar and share Soundex code N632 — giving near-full credit to opposite quadrants, worse than Q30's original "SD" vs. "ND" = 0.50 complaint. A binary comparison scores both at 0, which is the honest answer for values a caller selects from a closed set rather than spells. Second, prior art: the PostGIS TIGER geocoder parses pre- and post-directionals into discrete attributes and rates them categorically with small fixed penalties, reserving soundex/levenshtein for street names and place names — no production geocoder fuzzy-matches direction words or state codes, and none computes compass geometry for them (an approach considered and rejected here as precision that decision 80's dilution analysis shows the seven-term average cannot express anyway). Third, decision 81's gates fail decision 80's own test: a hard A1 gate against a single-state export empties the candidate set entirely for a caller who names the wrong state — a live scenario for this deployment (Fargo across the river from Moorhead MN; Pembina on the Canadian border) and exactly the confidently-wrong-about-administrative-geography caller decision 80 protected at the community level. The gate converts a query the remaining terms would have answered into a 468 hard failure; the binary weighted term prices the mismatch honestly (0, not 50) while keeping the candidate rankable. In the currently loaded export, A1 and Country carry discriminative factor 0.0 (decision 68), so their terms cost nothing today regardless — the correction is to the mechanism, for portability, not to current behavior.

The swap-scores-full-credit choice is deliberate rather than defaulted: the existing best-of-both-sides comparison already handles the common caller error (formal "North Main Street" spoken as "Main Street North"), a graduated swap penalty on a weight-8 term of an ~82-weight denominator would move the final score by well under a point, and splitting St_Dir into two independent terms would double the concept's denominator weight while re-creating the cross-slot mismatch problem the best-of-sides comparison exists to solve. The field stays one term. This decision, together with 69/75 (gates), 71/72/73/74 (name blend), and 80 (Community cap), completes the per-field comparison-mechanism taxonomy — the remaining §6.5 open items are tuning constants only (Appendix C item (d)), not mechanisms.

### 83 — §10.6 (closes the GCS_GEOCODED_PLACEMENT_PENALTY tuning item)

**Decision:** `GCS_GEOCODED_PLACEMENT_PENALTY` is retained at 0.9 and reclassified from an untuned strawman to a settled editorial default, deployment-tunable through its existing environment binding. It is removed from Appendix C item (d)'s open-constants list. No sweep is run, and the reason a sweep is not run is recorded so the item is not re-opened in search of one.

**Reasoning:** The constant cannot change an answer. §10.3's ordering is lexicographic — containment, then tier, then distance — and spatial fit is not among its terms; §10.6 already establishes exactly this separability for extent damping, and the Geocoding penalty is that component's sibling in the same product. The penalty therefore alters one reported number on the enhanced interface, plus confidence as its tier-scaled derivative, and alters nothing about which candidate is returned, in what order, or whether the request succeeds. On the strict i3 interface it is invisible entirely. Every prior tuning sweep in this document — decision 79's St_Type weights, decision 80's Community caps — scored a constant against a labeled outcome it could move: wrong-pair separation, threshold clearance. This constant has no such outcome to be scored against, and no substitute exists: STA-006.3's Placement Method registry records that a position was derived by geocoding, not the magnitude of error in that derivation, which is a property of the SI's own geocoder and reference data rather than of anything the GCS observes. The absence of a sweep here is a structural fact about the constant, not an unfinished task.

0.9 is chosen as an editorial value on the same footing as decision 80's retained 0.15 cap: it makes the round-trip approximation visible in the reported score — an address point positioned by geocoding, then reverse-geocoded back to an address, has passed through two approximations, one of them this service's own forward operation, the circularity §3.3's drafting note flags against the registry — while stopping well short of asserting a known error magnitude. Because the defensible value is a property of the deployment's source data rather than of the algorithm, the environment binding is the answer rather than a better shipped default; `src/runtime_state.py` already binds it and `src/app/lifecycle.py` already closes the reverse scorer over it, so the decision requires no implementation change beyond documentation.

### 84 — §15 (pseudologic written)

**Decision:** §15.1 and §15.2 are written, as annotated pseudocode covering both directions end to end. The section is explicitly declared subordinate: it summarizes decisions made elsewhere, makes none of its own, and where it conflicts with a numbered section the numbered section governs and the conflict is a defect in §15. Every step carries a citation to the section or decision that settles it. §2.4's drafting note about revisiting stage numbering is resolved — the four stages stand unchanged, and §15.1's structure matches the overview table exactly.

**Reasoning:** §15 was deliberately deferred across seven sessions on the grounds that a summary written before its subject matter is settled documents intentions rather than decisions. That condition is now met: decision 82 closed the last open comparison mechanism and decision 83 closed the last open scoring constant that could alter behavior, so §6.5 and §10.6 — the two sections §15 most depends on — are settled in mechanism rather than merely in shape. Writing it earlier would have required revision after each of decisions 69, 71, 72, 73, 74, 75, 76, 80, 82, and 83.

The pseudologic is annotated rather than bare, and the annotations carry the load-bearing negatives — the things an implementer would otherwise get wrong by reasonable inference. Specifically: that no progressive filter exists and every temporally-valid record is scored on every request; that only Add_Number and UnitValue gate candidacy while every other element is a weighted term; that search order is not acceptance order (decision 70's rung comparison); that Parity_L/R never blocks a forward match; that extent damping and the Geocoding placement penalty sit outside §10.3's lexicographic ordering and therefore move reported numbers and no answers; that tier precedence in reverse is scoped to contained candidates only, so a Point input never reaches it; that the reverse RCL inversion must walk the same endpoint-margin-shortened path the forward direction walks or §14.1 breaks by construction; and that an element with no source is omitted rather than emitted empty. Each of these is a case where the obvious implementation is the wrong one, which is precisely what a summary section is for.

### 85 — §7.4, §3.7 (resolves Q22)

**Decision:** A rung-3 STREET_SEGMENT answer is two-dimensional: EPSG:4326, with the RoadCenterLine geometry's per-vertex Z dropped rather than carried. This is the same treatment rung 2 already receives under R1, so there is now one rule for every RCL-derived answer regardless of rung, and no rung-dependent CRS logic. `Candidate.crs` stops returning `None` for a line answer — the deliberate abstention recorded in Q22 ends — and `src/api/wire/gml_xml.py` emits an explicit `srsName` of `urn:ogc:def:crs:EPSG::4326` on the rung-3 `gml:LineString` rather than omitting the attribute.

**Reasoning:** The question was framed as a conflict between R1 (which drops Z at rung 2 because §7.3's perpendicular offset displaces a road-surface Z horizontally onto a parcel, where it is no longer the structure's height) and §7.4's return-the-actual-geometry principle (which would carry the line undisplaced, Z included, and therefore escape R1's specific objection). Both readings are defensible on their own terms, and neither needed to be chosen, because a prior fact settles it: **RoadCenterLine is not a declared 3D-capable feature class**, as §10.5 already states in explaining why the reverse-side vertical band is inert. The provisioned layer's `MultiLineString Z` geometry type is an artifact of the GeoPackage export — a Z-typed layer supplies a Z slot on every vertex whether or not the data model says the slot means anything — not a declaration by STA-006.3 that road-surface elevation is authoritative vertical attribution. A Z the model does not declare is not data the GCS should promote to an answer.

This dissolves both halves of Q22 rather than answering them. The per-vertex-versus-whole-line granularity question does not arise, because no non-zero admission test runs on a value that is never consulted. And R1 is generalized rather than contradicted: R1's conclusion is correct, but its original argument (horizontal displacement) was narrower than its scope needs to be, and Q22 was right to notice that the argument does not transfer to an undisplaced line. The broader reason — the layer's Z is not authoritative at all — covers both rungs, so R1 survives on firmer ground than it was first given.

The alternative, emitting EPSG:4979 with a road-surface elevation profile along the segment, was rejected on what such an answer would mean to a consumer. A rung-3 answer asserts that the address lies somewhere on this segment and declines to say where; attaching a precise vertical profile to a horizontally-indeterminate answer claims knowledge in the axis the data model is silent about while disclaiming it in the axes the model actually covers. Q22's own closing observation — that a consumer requiring a CRS on every geometry would see the gap, and that this was a reason to close the question rather than leave it standing — is honored here by supplying a CRS rather than by continuing to abstain.

### 86 — §6.5 (closes Appendix C item (d)'s whole-score penalty sub-question)

**Decision:** No whole-score post-average multiplicative penalty is built, for Community or for St_Type. The sub-question raised by decision 80's sweep is closed as declined rather than deferred. matchScore remains what §7.4 and the enhanced schema describe — a weighted average of per-field similarity over the elements the query populated — and decision 82's three comparison classes remain exhaustive. No fourth mechanism class is introduced.

**Reasoning:** The proposed penalty is trapped between two walls with no gap between them. Decision 80 established that a caller may be confidently wrong about administrative geography while being right about the address ("Lincoln" for an address in Bismarck), so that caller's true match must still be returned and must still clear `GCS_MIN_MATCH_SCORE`. A multiplier strong enough to move a wrong-community score materially below a true match's is, by the same arithmetic, strong enough to push it under the admission floor — which is decision 77's reverted gate reconstructed with a multiplier in place of a zero. A multiplier weak enough to avoid that reproduces decision 80's own null sweep result. No middle setting exists, and the reason is structural rather than a matter of finding the right constant: **the two populations are identical in the data.** A legitimately-confused caller's true match and a genuine wrong-community false positive have the same field-score shape by construction — same street, same house number, non-matching community — so no scalar computed from those fields can separate them, whether applied per-term or to the whole score.

The information that does separate them is already in use, and it is used by ranking rather than by scoring. Three cases exhaust the space. Where the query names the wrong town and the data holds only the record in the right one, that record is returned at its high score — which is correct, being precisely the caller decision 80 exists to serve. Where the data holds both a right-community and a wrong-community record for the address, the right-community one scores at or near the ceiling, the wrong-community one lower, and default ranking by blended confidence (§7.4) puts the correct answer first; a penalty widens a gap that already decides the outcome. Where the data holds the same address in two wrong communities, both score alike and tie, and — being in different towns — they differ horizontally well beyond `GCS_AMBIGUITY_TOLERANCE_M`, so §6.3 returns 468. That is a better outcome than any penalized score, an honest refusal rather than a confidently-ranked wrong answer. In none of the three does the penalty change what the service returns.

Two further considerations confirm the decline. The honesty concern the penalty was meant to address — a candidate reporting a high matchScore when one of the caller's assertions did not match — is already fully served: the per-field breakdown surfaces Community's depressed score on the enhanced interface, which is the entire reason the HERE `fieldScore` precedent was adopted in Session 3, so a consumer can see which field dragged a candidate down. A post-average multiplier would compress into one number information the interface already carries at full fidelity, and would do so lossily, since a single scaled score cannot say which field caused the scaling. Mechanically, the penalty would also add a fourth comparison-mechanism class two decisions after 82 closed the taxonomy at three, and would break the weighted-average invariant that §7.4, §8.2, and the enhanced-interface schema all state.

St_Type is closed on the same reasoning rather than separately. Decision 79's finding — 87% of wrong_st_type pairs still clearing the threshold at 3x the base weight — has the identical shape, and the identical resolution: a caller who says "Main Avenue" for Main Street is served correctly when no Main Avenue exists, outranked correctly when one does, and refused correctly under §6.3 when the ambiguity is real.

### 87 — §7.2, §11.3 (adopts 67; resolves Q31)

**Decision:** Decision 67's parity-derived side hint is adopted formally into §7.2 and §11.3, as a clarification that the forward direction has exactly ONE side-selection rule rather than as a new rule. Side is resolved from the query's Add_Number parity against the record's Parity_L/Parity_R, and that single rule is consulted at two points: by §6.5's scoring, which needs a side for administrative and postal comparison and necessarily runs before position derivation, and by §7.2/§7.3, which need a side to interpolate along and offset from. The reverse direction resolves side by projecting the origin (§11.2, §11.3), because a reverse request supplies no house number from which parity could be derived. The two ends' fallbacks when parity fails to resolve are left divergent — scoring keeps best-of-both-sides per decision 67, §7.2 lets the asserted range govern — and the divergence is documented rather than reconciled.

**Reasoning:** Q31 was framed as a potential conflict between a parity-derived side hint in scoring and "§7.2's own geometric side selection," to be settled before the two could disagree. Reading §7.2 and §7.3 directly shows the premise is false: §7.3 applies the setback "on the side determined by the matched address parity," and §7.2 states that Parity_L/R governs "which side of the segment a house number belongs to." Forward side selection was already parity-based at both ends, so decision 67 did not introduce a second mechanism running ahead of a geometric one — it independently reached the rule already in force, earlier in the pipeline. Two applications of one rule to one set of inputs cannot disagree, and no cross-check is meaningful. The reverse direction's projection is likewise not a competing policy: with no house number in the request there is no parity to read, so projection is the only mechanism the input supports. Parity re-enters reverse at §11.2, but as the constraint a synthesised number is forced to — derived from the side rather than deriving it. The directions run parity and geometry in opposite order because they are given different things, which is why the asymmetry needed stating rather than fixing.

The fallback divergence is real and is accepted on cost grounds. Where parity does not resolve, scoring compares both sides and keeps the better similarity, never committing to a wrong side because it does not commit at all; §7.2, needing a position rather than a comparison, lets the asserted range govern. These can land on different sides for one record, and decision 80's requirement that scoring commit to a side for reporting makes the consequence visible: the per-field breakdown would describe one side while the position derives from the other. Aligning them would mean importing a range-containment cascade into the scorer that exists solely to serve records whose parity field is null or contradicts its own range — a GIS data-quality defect §7.2 already declines to repair, on the same grounds §11.3 and §11.4 decline to repair sparse attribution. Where the provisioned data is well-formed the two ends agree by construction, so the mechanism would be dead code in every correct case and would add a branch to the scorer to produce a marginally better report on data the SI should fix. The divergence is recorded in §7.2 so a reader encountering it knows it was chosen rather than overlooked.

### 88 — §6.3, 7.4 (resolves Q33)

**Decision:** Confidence does not degrade on merge. The three-field model's confidence dial (decision 31) is deliberately a match-quality measure — matchScore scaled to tier ceiling — and orthogonal to spatial extent by design, the same posture RFC 7459's confidence element already takes in this implementation: `build_confidence` leaves `pdf` at "unknown" specifically because naming one would assert a statistical claim about the shape the number was never built to carry. Folding merge radius into confidence would be exactly that claim. The honesty concern Q33 raised is already served, losslessly and more precisely, by §6.3's Circle geometry — a measured geodesic radius rather than a scalar penalty — which decision 57 already wires end-to-end. The enhanced interface has no version of this gap: decision 27 means it never merges, returning every real candidate individually at its own genuine matchScore.

**Reasoning:** Traced against the implemented code rather than the spec text alone. No part of the mechanism was actually missing — resolve_ambiguity measures the radius, ForwardAnswer carries it, and gml_xml.answer_geometry_element already renders gs:Circle instead of gml:Point whenever the radius is nonzero. What Q33 identified as an incomplete signal is a second, independent, already-complete one; conflating it with confidence would revisit decision 31's core commitment that confidence is "never stored independently" of matchScore and locationType, for a decay function with no principled constant — the same dead end decision 86 already closed for the whole-score penalty.

### 89 — §6.5 (closes Appendix C item (d)'s `_BASE_WEIGHTS`)

**Decision:** `_BASE_WEIGHTS` is closed as VALIDATED against the statewide deployment rather than retuned. No editorial weight changes. This is item (d)'s last open constant set, and it closes on evidence rather than on the reclassify-rather-than-tune reasoning that closed decisions 78, 79, 80 and 86.

**Evidence:** A purpose-built pairwise ranking sweep (`tools/weight_ranking_sweep.py`) against the full statewide export — 431,239 SSAP and 174,540 RCL records, 70.9% of SSAP rows carrying all six in-scope civic fields. For each sampled record the query is an exact copy of the record's own values, and one decoy per field is built by substituting a donor value drawn from elsewhere in the layer, admitted only if it scores at or below 0.15 against the scorer's own comparison for that field. Every empirically testable field pair ranked correctly in 100% of samples, with zero reversals and zero ties, across two independent runs (250 records at seed 42, and 2,000 records at a different seed) agreeing within 0.05 on every mean gap. Community outranks St_Type by a mean 6.87–6.92 points and St_Dir by 9.82–9.85; St_Type outranks St_Dir by 2.93–2.95.

**Why this is a different question from decisions 78/79/80/86:** those tested whether reweighting could push a mismatched candidate's ABSOLUTE score below `GCS_MIN_MATCH_SCORE`, and kept failing because one disagreeing term is diluted inside a seven-term average whose other terms score near 1.0 by construction. This tests RELATIVE ranking between two candidates of the same query, where the query-populated field set — and therefore the weighted-average denominator — is common to both, so the ordering reduces to the sign of the weighted similarity difference and the weight ratios do undiluted work. The earlier null results do not generalize to this question, which is why it was worth measuring rather than assuming settled.

**The six-county artifact, recorded so it is not rediscovered:** an initial run against a six-county extract (78,237 SSAP records) reported Community and St_Type inverted in 250 of 250 samples, and Community against St_Dir at a 43.2% coin flip. Both dissolved on the statewide data. The cause was the discriminative factor, not the editorial weight: A3's factor was 0.327 in an extract where one metro dominated the record count, against 0.754 statewide, so Community's effective weight rose from 4.90 to 11.57 and cleared St_Type's. The finding is a caution about extract representativeness, not about the two-factor design — and the service runs only in the statewide configuration.

**What "validated" does and does not cover:** only 3 of the 21 field pairs are empirically testable, and that is a permanent property of a single-state deployment rather than a sample-size limit. A1 and Country measure a discriminative factor of exactly 0.0000 (100% modal share, "ND" and "US"), so their effective weight is 0.00 and their base weights are inert here — they can only matter in a multi-state export, and tuning them statewide is a no-op. A2 is untestable for the separate reason recorded in decision 91. The remaining pairs rest on the effective-weight table, not on the sweep.

**One hypothesis falsified:** the sweep was run against a stated prediction that street-form fields are address-writing convention and therefore footprint-invariant, while community names are settlement geography and therefore not. That was wrong. `St_PosTyp`'s factor fell 0.111 and `St_PosDir`'s rose 0.136 between the two footprints, with only `St_PreDir` roughly stable. Street-form convention varies across ND settlement patterns about as much as community names do, merely not in a single direction. No geography-versus-convention classification axis is therefore available to build on, and none is added.

---

### 90 — §6.5 (extends 76 to the two-slot terms)

**Decision:** For the two terms that span a pair of record slots — St_Dir (`St_PreDir`/`St_PosDir`) and St_Type (`St_PreTyp`/`St_PosTyp`) — the discriminative factor is read from the slot that actually produced the compared value, rather than from a slot named in source. This is decision 76's per-record cascade lookup, applied to the same structural problem in a different place. When both slots yield equal similarity the factor is taken from the slot with the larger measured population, so the choice is deterministic and the more meaningful measurement wins.

**Evidence:** `score_ssap` weights St_Dir by `f("St_PreDir")` while `_best_of_sides` compares the query against both directional slots. Statewide, `St_PosDir` is populated on 280,882 records against `St_PreDir`'s 29,117 — roughly a tenfold gap — with materially different factors (0.7465 against 0.6246). The term was therefore weighted by the statistics of the slot carrying under a tenth of the data.

**On RCL, slot selection and side selection do not interact.** St_Type and St_Dir are RCL's unsided shared columns — never `_L`/`_R` suffixed — so decision 90's slot lookup is structurally independent of §11.3's side selector rather than merely happening not to collide with it. Implementation confirmed this and pinned it with a test that flips which side Add_Number parity chooses on an otherwise identical record and asserts the St_Dir term scores identically either way. A future reader should not assume the two mechanisms need to be reasoned about together.

**Confirmed against the statewide data on implementation.** For a real record with `St_PosDir` populated and `St_PreDir` empty, the resolved slot is `St_PosDir` and the effective weight moves 4.997 → 5.972, matching this decision's stated estimate to three significant figures. No expected-ordering assertion anywhere in the existing suite changed, which is the predicted signature of a measurement fix rather than an answer fix.

**Two different effective weights are both correct, and a reader will meet both.** 5.972 is the PER-RECORD weight for a record that resolves through `St_PosDir`. `tools/field_factor_diagnostic.py` reports 5.881 for St_Dir, which is the CORPUS-MEAN across the resolution mix — roughly 9.4% of resolved records go through `St_PreDir` at 4.997 and 90.6% through `St_PosDir` at 5.972. Neither number supersedes the other and neither indicates a regression; they answer "what does this record weigh" and "what does the deployment weigh on average" respectively. The same distinction applies to St_Type (per-record 7.111 via `St_PosTyp`, corpus-mean 7.008).

**Resolution split, statewide.** St_Dir resolves 6.7% through `St_PreDir`, 64.8% through `St_PosDir`, and does not resolve at all on 28.4% of records — where the term simply drops from the weighted average, per decision 61's rule that sparseness costs score rather than candidacy. St_Type resolves 94.9% / 4.3% / 0.8%.

**The tie rule is specified but nearly unreachable here.** Zero of 431,239 records populate both directional slots, and ten populate both street-type slots. The equal-similarity tie-break is therefore correct to have specified but is not load-bearing in this deployment, and a future reader should not treat its behavior as exercised by the live data. It exists so the resolution is total rather than conditional on a data property that could change.

**Reasoning:** The correction raises St_Dir's effective weight from 5.00 to approximately 5.97 and reorders nothing at present, so this is not a fix to a wrong answer. It is a fix to a wrong measurement, which is the more durable defect: the current lookup is insensitive to the data it claims to measure, and would stay wrong under any future shift in slot usage. St_Type is corrected by the same mechanism. `St_PosTyp` is the dominant slot at 409,234 against 18,785, so the hardcoded lookup was nearly right — but measurement confirmed it was not exactly right, moving St_Type's corpus-mean effective weight 7.111 → 7.008 because 4.3% of records resolve through `St_PreTyp`, whose factor is 0.3964. "Correct by data accident" was the closer description than "correct"; leaving it would have preserved a second live instance of the defect being fixed, not merely a latent one. The whole point of the measured-factor design is that it reads the deployment rather than trusting an authored assumption; a hardcoded slot name is exactly such an assumption.

---

### 91 — §6.5 (declines A2 shared-suffix normalization)

**Decision:** No shared-suffix stripping is added to `_normalize_token` or to the A2 comparison path. Declined deliberately, and recorded here rather than logged as an open question, so it is not re-raised as unexamined.

**Evidence:** All 52 ND county names carry the literal token "County". Across all 1,326 distinct county pairs, production similarity has a floor of 0.194, a mean of 0.278, and never falls below the 0.15 threshold; stripping the trailing token drops 1,206 of those 1,326 pairs below it. The suffix, not the county name, is holding every pair up. This was confirmed at the mechanism level: expanding from 5 counties to 52 moved the rate not at all, which rules out sample size.

**Reasoning:** The inflation compresses a gap it never inverts. Against the statewide effective weights, A2 contributes 12.4% of matchScore, so a correct county scores 100.00 where a wrong one scores 91.02 at the mean and 89.97 at the worst-case floor — the correct county outranks the wrong county by roughly nine points in every pair measured. Stripping the suffix would widen that to 11.64, adding 2.66 points of separation and changing no ordering. The behavior the deployment actually requires — that a caller who supplies the correct county has candidates in that county ranked above candidates elsewhere, all else equal — is already delivered.

**A coherent asymmetry, noted rather than corrected:** A2's effective mismatch floor (0.194) sits above Community's mismatch cap (`_COMMUNITY_MISMATCH_SIMILARITY_CAP`, 0.15), so a wrong county is priced slightly more leniently than a wrong community. That runs with decision 80's principle rather than against it: a caller confident about the street address may name the wrong administrative unit without being wrong about the address, and the county is the unit they are least likely to have reason to know. The asymmetry is left in place.

### 92 — §3.9.2, §12.2 (closes Appendix C item (c))

**Decision:** `references/i3-geocode-conversion-enhanced.yaml` is reconciled against the implementation and adopted as the NORMATIVE spelling of the enhanced wire format. Where the draft and `src/api/wire/response_json.py` disagreed, each divergence is resolved below rather than left to whichever artifact a reader happens to open first. §3.9.2 is amended: Placement Method is carried on the reverse resource only.

**Why this was reconciliation and not authoring:** the draft was written in Session 5 and the enhanced interface continued to evolve through Session 8, with neither artifact updated against the other. Appendix C item (c) and `response_json.py`'s module docstring both stated no YAML existed; the Session 5 note recording the draft was correct and the two live trackers were stale. Three sessions of carry-forward inherited the wrong version. The drift was substantial enough to be worth recording as a pattern: an artifact described as "not yet written" is not audited, so it drifts silently, and the description outlives the condition it described.

**Naming, resolved toward the implementation in two cases and the draft in one:**

- `pidfLo`, not the draft's `pidfLoGeo`/`pidfLoAddress`. The enhanced candidate carries the full matched record — civic AND geodetic together (§8.2, decision 11) — so a Geo or Address suffix actively misdescribes the field on both resources. The strict wrappers keep their own names, which are the normative YAML's and are accurate there because those bodies really do carry only one.
- `distanceMeters`, not `distanceM`, for internal consistency with `horizontalUncertaintyMeters` and `verticalExtentMeters`.
- `matchScoreBreakdown`, not the implementation's `fieldScores` — the one case resolved toward the draft. On the reverse side the breakdown decomposes §10.6's spatial-fit COMPONENTS, not civic fields, so `fieldScores` is a misnomer there. The rename is cheap (one emission site, two doc comments) and the artifact is pre-deployment, so no consumer is broken.

**`rank` is not carried.** The draft declared it required and 1-based; nothing in the implementation emits it. Resolved by dropping it from the schema rather than adding it to the code: JSON array order is significant, `src/api/enhanced.py` does not re-sort a list after assembling it, and array position therefore already IS the rank. A redundant field would be one more thing that can disagree with itself.

**Six emitted fields the draft omitted are added:** `houseNumberSynthesised`, `horizontalUncertaintyMeters`, `verticalExtentMeters`, `mergedFrom`, `locationCount`, and `droppedElements`. These are not incidental — each exists precisely because the strict interface discards something the engine computed, which is the substance of the §16 rows and the entire argument the NENA-facing diff is making. Omitting them from the proposal artifact would have undercut its own case.

**Conditional absence is documented as meaningful, not as ignorance.** `mergedFrom` absent means exactly one candidate, not an unknown count; `locationCount` absent means exactly one location; `horizontalUncertaintyMeters` absent means §7.4 declined to synthesise an uncertainty around a single matched geometry, because the geometry is itself the uncertainty statement. Each is stated in the field description so a consumer does not have to infer it.

**Confidence bounds diverge from the XML path deliberately.** The draft imported RFC 7459's `minExclusive` 0.0 / `maxExclusive` 100.0 and cited Q5 as unresolved — but the JSON body then violated its own declared schema, since the enhanced path emits a rounded number that can be exactly 0.0 or 100.0 while `build_confidence` emits the token `"unknown"` outside the open interval. Those bounds constrain RFC 7459's XML schema, and this JSON extension is not bound by it. The schema declares inclusive 0–100. Q5 remains live for the strict path and simply does not arise here: the enhanced interface can state a confidence i3's own schema has no way to express, which is the §2.2 contrast working exactly as intended.

**`469` is not declared on either enhanced resource.** The draft carried it on `/GeocodeEnhanced`, inherited from the normative YAML. This service never emits 469 — the condition is undefined for a request carrying no MCS or GCS identity (§2.1) and `src/api/status.py` mints none — and declaring a status the implementation cannot produce misdescribes the interface. `454` IS declared on both, which restores the symmetry the normative YAML breaks by omitting it from `/ReverseGeocode` (§12.3, §16).

**Response content type is `application/json` on the enhanced resources.** The normative YAML declares `application/xml` while typing the body as an object with a string property; those cannot both hold, and the strict resources carry that defect faithfully rather than repairing it (§3.9.1, §1.2.1). These resources are new and under no such obligation. The request body is left byte-identical to the normative declaration, because §3.9.2 specifies the enhanced resources accept the same request as their strict siblings and changing its shape would falsify that.

**Placement Method is reverse-only, and §3.9.2 is amended to say so.** §3.9.2 claimed forward candidates carry Placement Method ID where present; they never have. `ForwardAnswer` carries geometry, quality, position, uncertainty, and merged count, with no path to the matched record's `Placement` at all, so the claim was unimplementable as written rather than merely unimplemented. Resolved by amending the specification rather than building the path: the reverse side has a stated reason to disclose it — it is part of what pays for §10.5's uncorrected centerline bias — and no equivalent argument exists on the forward side, where the matched record travels whole inside `pidfLo` regardless.

### 93 — §3.4 (closes the §3.4 drafting note)

**Decision:** GIS record temporal filtering is evaluated at request time against `runtime_state.now()`, not at GIS load/reload time. Effective is honoured inclusively, Expire exclusively; a record with neither field is always active; an unparseable date is treated as absent rather than as grounds to drop the record. i3 §4.5 defines no client-driven temporal qualifier (no `<asOf>` or revalidateAfter analog) for the GCS to honour, and none is needed — STA-006.3's Effective/Expire pair already lets the service decide a record's status at the instant of the request without one.

**Reasoning:** This was reconciliation, not authoring. `is_active()` (`src/geocode/candidates.py`) already implemented every open question the drafting note posed; the section had simply never been written up against it. Both fields are null throughout the provisioned data, so "records without them treated as always active" describes the deployment's actual condition, not a fallback branch that mostly goes unused.

### 94 — §3.5 (closes the §3.5 drafting note)

**Decision:** Three properties of GIS reload behavior are settled as specification, not left as unstated implementation detail. First, a failed hot-reload leaves the previously-loaded dataset in place rather than clearing it — stale data is preferred to no data — reported via ElementState SERVICE_DISRUPTION while the service keeps converting against the last good load; this is distinct from never having loaded any data at all, which drives both ElementState and ServiceState to their down states because there is nothing to fall back to. Second, a request in flight during a reload always finishes against a consistent snapshot — the live record lists are read by reference and a reload rebinds the reference to a fully-built replacement rather than mutating the lists in place, so no request can observe a half-swapped dataset. Third, readiness and health are reported on separate signals: `/ready` gates traffic specifically on "reload in flight" or "never loaded," a narrower and stricter condition than the broader "operating in a disrupted state" that ElementState/ServiceState may otherwise report while still serving.

**Reasoning:** Also reconciliation rather than authoring — `i3_fe_core.gis.DatasetCache`, `src/gis/provisioning.py`, and `src/app/lifecycle.py`'s reload callbacks already implement all three properties. The value of writing this up is making the "stale over absent" posture an explicit, citable design stance rather than something a reader has to infer from three separate source files.

### 95 — §3.9.1, §A.1 (resolves Q1 and Q14; logs Q2 to §16)

**Decision:** Three wire-interface readings the implementation had adopted provisionally are adopted as specification. First, the `/Versions` entry point lives at `/Gcs/Versions` — one path segment above the `/Gcs/v1` base the two operations sit on — following the normative YAML's own `servers` override literally, and it is *unversioned by design*: a client must be able to reach the version-discovery endpoint before it knows which versions exist, so placing it inside a versioned base would be circular. Second, the request body is accepted in both of the YAML's two readable forms — a JSON string carrying the escaped PIDF-LO, or the raw XML itself — discriminated by the first non-whitespace byte (`"` → JSON string, `<` → raw XML), with Content-Type logged but not enforced. Third, the YAML's `/Versions` 200 body references `i3-common.yaml#/components/schemas/VersionsArray`, and no `i3-common.yaml` exists in the published `NENA911/Geocode-Conversion-Service` repository; the reference is unresolvable from the published artifact, and this is recorded as a §16 row alongside the content-type incoherence already there.

**Reasoning:** All three are reconciliation rather than authoring — the implementation has behaved this way since the plumbing pass, and Q1/Q14 flagged the readings as worth stating rather than inferring. On the body: the YAML declares `application/json` with `schema: {type: string}`, which read strictly means a JSON document that is a string, and read as most senders will implement it means raw XML under a confused Content-Type. Rejecting either form would add a restriction i3 does not impose (decision 2's corollary), and the declaration such a rejection would be strict about is the same one §16 already records as incoherent. On `/Versions`: `i3_fe_core.web_service.versions` supplies the i3 §4.12 body shape, so the unresolvable `$ref` blocks nothing here; it is a defect in the normative definition and belongs in the table where NENA-facing defects live.

### 96 — §10.2 (resolves Q4)

**Decision:** The single search radius's vertical component is accepted as non-binding, and §10.2 states the consequence rather than leaving it as an accident. At any horizontally useful value of `GCS_REVERSE_SEARCH_RADIUS_M` — the proposed 250 m, or even 50 m in a dense urban deployment — the vertical band the same value nominally constrains spans an 80-storey (respectively 16-floor) structure, so the vertical component of the constraint never binds in practice. No separate vertical radius is introduced, and no vertical term is added to the ordering beyond the §10.5 band that already exists.

**Reasoning:** Decision 39 recorded that collapsing to a single pass surrenders exactly one capability: a separate search radius per pass. Q4 is that surrender showing up in practice, and the options were to accept it and state it, or to reintroduce a vertical bound. Reintroducing one fails on the same ground twice established: it needs a vertical tolerance constant, and §10.5 already rejected both the weighted metric's `k` and a widened band for want of a defensible default from data that barely exists (decision 60). The condition is also nearly unreachable — §10.5's band is inert on every provisioned class, and §3.7.2 records that the 2D path is the productive one in most jurisdictions today — so the honest resolution is a stated consequence, revisited if a volumetric feature class ever makes the vertical axis load-bearing.

### 97 — §7.4, §8.3 (resolves Q5)

**Decision:** A confidence value at or beyond either bound of RFC 7459's decimal interval serialises as the token `"unknown"` on the PIDF-LO (XML) path, not as a clamped number. The tier-ceiling table keeping SPACE_3D at 100 is affirmed as correct: 100 is the top of the *internal* confidence scale, and the inexpressibility of exactly 100 is a constraint of RFC 7459's wire schema (`minExclusive="0.0"` / `maxExclusive="100.0"`), not a defect in the scale. The enhanced JSON path is unaffected — decision 92 already declares its bounds inclusive 0–100, since that JSON extension is not bound by RFC 7459's XML schema.

**Reasoning:** The three candidate answers Q5 posed were: emit 99.9, emit `unknown`, or amend the ceiling table. Clamping to 99.9 reports a number the service did not compute — a fabricated tenth-of-a-point of doubt — where `unknown` is a value RFC 7459 defines for precisely the case where the schema cannot carry what the producer knows. Amending the table would let a wire-format limitation reach backward into the semantics of the confidence scale, and would also break the property that ceilings are fixed so two implementations agree on what a value means. The condition is latent — SPACE_3D is unreachable until a volumetric class exists — but §7.5 commits to accommodating 3D spaces without rework, and this is the cheap-now, awkward-later kind of settlement. `build_confidence` in `src/api/wire/gml_xml.py` already implements exactly this; the decision records it as specification rather than implementation accident. The bottom of the scale is moot: `GCS_MIN_MATCH_SCORE` floors admission well above 0.

### 98 — §A.6 (resolves Q6)

**Decision:** The Discrepancy Reporting web service's canonical base is `/dr`, because §4.12's requirement that every web service have a `/Versions` entry point needs a base to hang one off — `/dr/Versions` exists and carries the DR service's version. The root-mounted aliases for `Reports`, `Resolutions`, and `StatusUpdates` are retained deliberately, against the same shared `DiscrepancyReporting` instance: i3 §3.7.1–3.7.3 name the resources with no base path, `i3-fe-core`'s own `create_app()` mounts them at the root, and its conformance suite probes them there. The two-path state is thereby settled as intentional interoperability accommodation rather than an unresolved fork, with `/dr` the path a client should be given and the root aliases withdrawable if a future i3 revision states a base path.

**Reasoning:** The two readings of i3 genuinely collide and neither can be dismissed: reading 1 (no base path) is what the standard's text literally supports and what core's conformance suite enforces; reading 2 (a base, so `/Versions` is satisfiable) is what §4.12's MUST requires structurally. Serving both against one instance costs nothing — state is shared, so a report POSTed to `/Reports` is resolvable at `/dr/Resolutions` — and electing `/dr` as canonical resolves the "not a resting state" objection by making the hierarchy explicit rather than by breaking one of the two readings. Related: §A.6's open note on the extent of the XACML-registry-implied obligation is subsumed by decision 99.

### 99 — §A.6 (resolves Q7)

**Decision:** The GCS files discrepancy reports about **structural provisioning defects only** — conditions under which the GCS cannot perform behaviour this specification requires of it — and never about the content of attribution. The filing triggers are: GIS load or reload failure (the dataset the service is required to convert against cannot be read); a record with a null NGUID (ineligible for §10.4's deterministic tie-break, per R3, which already names the discrepancy path); a multi-part RoadCenterLine segment (no defined traversal order, decision 53); and a record with no usable geometry (cannot be a located match, decision 55). These are exactly the conditions `src/engine/models.py`'s `DataQualityFlag` already records, plus load failure itself — the flag vocabulary *is* the filing vocabulary. `src/discrepancy/` remains a thin module scoped to building `GISDiscrepancyReport`s against the SI for those conditions; the wiring itself stays deferred work, now unblocked.

**Reasoning:** Q7 observed that every place earlier drafts proposed filing — §7.1's Z disagreement (decision 29), §11.3's attribution-versus-polygon disagreement (decision 45), §11.4's sparse records (decision 46) — settled the other way, leaving load failure as the only obvious trigger and asking whether that is the whole obligation. It is not quite, and the line that separates the settled-against cases from the filing cases was already drawn by the code without being stated: decisions 29/45/46 all concern *attribution content*, where the spec's consistent posture is that the GCS reports what the record says and does not second-guess the SI. NGUID_MISSING, MULTIPART_SEGMENT, and NO_GEOMETRY are different in kind — they are not the SI asserting something the GCS doubts, they are records the GCS cannot process as this document specifies (cannot tie-break deterministically, cannot traverse, cannot locate). Reporting those is not second-guessing; it is the feedback loop STA-006.3's provisioning model exists to close. R3 had already committed the NGUID case to the discrepancy path, so this decision generalises a rule one flag already followed rather than inventing one.

### 100 — §3.9.5 (resolves Q9)

**Decision:** The load-shedding response is settled as a *transport-layer* response, emitted before the request is admitted as a GCS operation, and therefore outside i3 §4.5's closed status set — which governs conversion outcomes, not connection admission. The candidate framing Q9 named is adopted explicitly: this is the same move that already lets the service emit 413 (oversized body, rejected by middleware before admission) and lets any HTTP stack emit 405, and the implementation has in fact emitted 413 since the plumbing pass, so the reading was already load-bearing. A shed request receives 429 with a `Retry-After` header and no i3-shaped body; it is never 454 (which tells a shedding client nothing and invites the retry storm shedding exists to prevent) and never 468 (which asserts a search happened). Shedding itself remains unimplemented — this decision removes the blocker, not the deferral — and the previously reserved `GCS_MAX_CONCURRENT_REQUESTS` / `GCS_RATE_LIMIT_*` variables are removed from the canonical variable reference until an implementation reads them, per `.env.example`'s own contract that it lists every variable the service actually reads.

**Reasoning:** Decision 2's closed set exists to stop the GCS minting *conversion* vocabulary i3 has not given it — §1.2.1's rule is about the wire contract of the Geocode and ReverseGeocode operations. A 429 emitted by a connection-admission layer says nothing about a conversion, because no conversion was admitted; reading the closed set to forbid it would also forbid 413 and 405, which no reading of i3 requires and which the normative YAML's own transport (HTTP) makes unavoidable. The line is drawn at admission: once a request is admitted as a GCS operation, only the five §4.5 codes may describe its outcome; before that, HTTP is HTTP. Stating the line explicitly is what Q9 asked for, and it survives contact with the strict-conformance argument precisely because the alternative proves too much.

### 101 — §3.9.4 (resolves Q11; complements 94)

**Decision:** §3.9.4 is written. `/health` is liveness and returns 200 whenever the process is up, carrying `status` / `elementState` / `ntpHealthy` (and the GIS counts) as advisory fields; `/ready` is readiness, returns 503 while a GIS reload is in flight or before any data has loaded, and is the only operational endpoint a load balancer should gate traffic on. This is a recorded, deliberate divergence from `i3-fe-core`'s own `create_app()` convention, whose health route returns 503 when element state is not Normal or NTP is unhealthy: making `/health` 503 as well would collapse the liveness/readiness split this section exists to establish, and killing a worker because its GIS data is stale or its clock has drifted does not make either problem better. Core's conformance suite accepts either status code, so the divergence is interoperable.

**Reasoning:** Reconciliation, not authoring — the implementation and its docstrings have carried this split since the plumbing pass, decision 94 already settled the `/ready` half while writing §3.5, and Q11 asked only that the `/health` half be recorded in §3.9.4 rather than left as a silent local choice. The operational logic: liveness answers "should this process be restarted" and the answer for a worker with stale data or drifted time is no — it is impaired but alive, restart fixes nothing, and the impairment is already externally visible through ElementState/ServiceState and `/ready`. Readiness answers "should traffic be routed here right now," which is the narrower, stricter condition §3.5 describes.

### 102 — §4.2, §4.3 (resolves Q16 and Q17)

**Decision:** Two admission edges are settled. First (Q16), §4.3 "Profile Check" is folded into §4.2: there is no separate profile gate, and the section now points at §4.2, whose election-then-check sequence already answers both cases the drafting note asked about — a document carrying only the wrong profile has its elected location fail the chunk check and returns 468 with no walking of the document for a better-typed location, and a document carrying both profiles selects by namespace within the elected `<location-info>`, never by position (RFC 5491 Rule #7 makes position encode coarseness, not relevance). Second (Q17), a well-formed, schema-valid document carrying **no location whatsoever** — RFC 3863 makes `<tuple>` content optional, so this validates — returns **468**, the same as an elected location lacking the required chunk.

**Reasoning:** Q16 was a staleness repair: decision 50 and §4.2 had already answered §4.3's drafting note, and a section whose note implies a separate gate invites someone to build one — §5's whole argument is that gates i3 does not ask for must not be added. Q17 required an actual choice, and 468 wins over 454 on the shape of the failure: 454 asserts the request was malformed, and this request is not — it is well-formed, schema-valid, and simply carries nothing convertible, the same shape as the elected-location-lacks-chunk case §4.2 already sends to 468. The counter-argument (468 asserts a search was performed, and none was) is acknowledged and outweighed: by that reading the chunk-check 468 already settled in decision 50 would be equally wrong, and no third code exists. Consistency between the two nothing-convertible cases is worth more than either reading of 468's letter, and the closed set offers nothing better.

### 103 — §3.2 (resolves Q19; adopts R4 into §3.2)

**Decision:** Two GIS-ingestion facts are adopted into §3.2 as specification. First (Q19), Placement Method arrives in provisioned data as the registry *token text*, not the integer FK into STA-006.3 Table 15-8 that §3.2's drafting note assumed — no join is performed, the field is typed as text, and code written to expect an integer would fail against this SI. The provisioned spellings do not all match the registry (`Property Access` with a space against the registry's `PropertyAccess`), so every comparison against a registry token is made after trim-and-casefold normalisation — as `src/engine/scoring.py`'s §10.6 Geocoding-damping comparison already does — and the token is passed through to the enhanced interface as the SI spelled it, uncorrected, consistent with the general posture that the GCS reports what the record says. Second (R4), ingestion strips surrounding whitespace from every text value and normalises empty or whitespace-only text to null; interior whitespace is untouched. This is forced by fixed-width export padding — measured against the provisioned data, 32 of 49 sampled SSAP text columns are whitespace-only in over 90% of rows and padding appears on non-blank values — and without it exact comparison and §11.4's omit-rather-than-emit-empty rule are both unimplementable.

**Reasoning:** Both are reconciliation of long-implemented behaviour (`SSAPRecord.Placement` typed `str` since the field was added; `_plain` in `src/gis/records.py` since ingestion was written) into the section that owns GIS data-quality observations. The normalisation rule for Placement matters beyond tidiness: §10.6 damps on the value `Geocoding`, and a comparison without normalisation would silently miss spelling variants, turning a data-entry inconsistency into an unreported scoring difference. Worth noting for §10.5's disclosure argument: the largest single value in the provisioned data is `Parcel` (42% of records) — a parcel centroid rather than a structure point, exactly the placement variance §10.5 argues for surfacing rather than correcting.

### 104 — §A.3 (resolves Q10)

**Decision:** Confirmed by direct read of the full i3 §4.12.3.7 LogEvent type registry (all 44 defined types): **i3 defines no GCS-specific LogEvent type.** The nearest analogues are service-specific pairs — `LostQueryLogEvent`/`LostResponseLogEvent` (scoped by their own definitions to elements querying the ECRF/LVF and to the ECRF/LVF itself) and `LocationQueryLogEvent`/`LocationResponseLogEvent` (scoped to LSRG/LPG ALI traffic) — and neither covers GCS HTTP conversions. The gap is recorded as a §16 row. This document proposes `GcsQueryLogEvent` / `GcsResponseLogEvent` on the `LostQueryLogEvent`/`LostResponseLogEvent` pattern: the entire request PIDF-LO and response object carried in the event, a locally generated globally unique `queryId`/`responseId` pair relating the two, and `direction` incoming/outgoing. `src/logging/` is thereby unblocked — the prologue subclasses implement the proposal, since there is no registered type to extend — though writing them remains deferred work. Second, the privacy posture i3 §4.5's payload-logging MUST implies is stated rather than inherited silently: because the GCS must log "the input and output objects," every logged Geocode request contains a civic address and every logged response a coordinate, so the Logging Service accumulates a complete queryable record of which addresses were asked about. That is presumed intended — it is the same property call-related LogEvents already have — but it is a data-sensitivity fact deployments should weigh when configuring Logging Service access policy (i3's `LogServiceAllowedToRetrieve`), and §A.3 now says so.

**Reasoning:** The blocker on `src/logging/` was purely evidentiary — whether a registered type exists to subclass — and the registry read settles it. Proposing a query/response pair rather than a single conversion event follows the registry's own idiom: every request/response interface i3 logs (LoST, ALI) logs the two halves as separate correlated events, which preserves the malformed-response and no-response cases (`responseStatus` on the response event) that a single combined event cannot represent.

### 105 — §4.1, §4.2 (resolves Q15)

**Decision:** The RFC 4479 presence data model elements (`dm:device`, `dm:person`) remain admitted through RFC 3863's `xs:any namespace="##other" processContents="lax"` without their own schema in `schemas/` — accepted as a documented validation-scope boundary, not closed. The consequence is stated precisely: what goes unvalidated is the RFC 4479 *container structure itself*, not the location content inside it. Because `processContents="lax"` validates any element whose declaration the schema set knows, and the combined `gcs-pidflo.xsd` declares the geopriv, civic, GML, GeoShape, and confidence vocabularies, a `gp:geopriv` inside a malformed `dm:device` is still fully validated wherever it appears; only the `dm:*` wrapper escapes checking, and a malformed wrapper affects only Rule #8's container classification, not the location payload. The closure path is named — add RFC 4479's data-model schema to the `schemas/` wrapper — and deliberately not taken now. The related structural fact Q15 surfaced is adopted into §4.2: RFC 3863's content model (`tuple*`, `note*`, then `xs:any ##other*`) forces a `dm:device` to appear *after* every `<tuple>`, so document order and Rule #8 order point in opposite directions for device-versus-tuple *by construction* — which is precisely why Rule #8 must be a typed precedence rather than "the first one you meet."

**Reasoning:** §4.1's 454-on-schema-invalid obligation is scoped to the PIDF-LO envelope schemas, and RFC 3863 itself — the envelope's own normative schema — is what admits foreign namespaces lax. Enforcing strict validation on `dm:*` would go beyond what the envelope's schema asserts, and the payoff is small because the load-bearing content is already validated by the lax mechanism. The gap is latent and bounded; documenting the boundary honestly beats either silently carrying it or growing the schema set for a wrapper whose malformation cannot corrupt a conversion.

### 106 — Appendix C.2 (closes question 7 and item (b))

**Decision:** Two long-deferred Appendix C.2 items are closed. Question 7 (packaging of the element model): the model stays a plain module in this repository (`src/engine/models.py`), with no extraction to a shared package and no vendored copy elsewhere. The question's own condition — "decide when code exists to observe" — is met, and what the code shows is that the vocabulary is the GCS's own, derived from STA-006.3 and STA-004.2 directly under decision 58's standalone scope; no sibling FE consumes it, so there is nothing to share and an extraction would be speculative packaging for a consumer that does not exist. Reopen only when a second consumer actually appears. Item (b) (tier-ceiling configurability): the ceilings (100/90/80/75/50) remain fixed by this specification and are **not** made configurable, closing the "may warrant a configurability review" deferral as declined. A confidence value's meaning must not vary by deployment — the ceilings exist precisely so two implementations cannot disagree about what a confidence of 75 asserts, and a configurable ceiling would let one deployment's INTERPOLATED_POINT outrank another's ADDRESS_POINT at identical match quality, which is the cross-implementation incoherence §7.4's fixed table was built to prevent.

**Reasoning:** Both closures follow the same YAGNI discipline the register applies elsewhere (decisions 86's declined penalty, 91's declined normalization): a mechanism with no present consumer and no evidence-backed need is not built, and the decline is recorded so it is not re-raised as unexamined.

### 107 — §3.9.3, §A.8, Appendix C.3 (withdraws a false claim; adds a fifth deferred item)

**Decision:** §3.9.3's claim that transport security is discharged through `i3-fe-core security.tls`, and its claim that i3 §5.4 application-layer peer authentication is the compensating control for uvicorn's `CERT_OPTIONAL` mTLS behaviour, are both WITHDRAWN as false. Neither core security module is wired. §3.9.3 is rewritten to state the deployed posture — ad hoc uvicorn TLS with no PFS or version enforcement, `CERT_OPTIONAL` mTLS with no compensating control at any layer, default `httpx` on egress — and to state explicitly that §2.8.1 and §5.4 are currently UNENFORCED rather than partially met. Appendix A.8's citation of `security.tls` / `security.peer_auth` is annotated as naming the modules that should discharge the requirement rather than modules in use. Appendix C.3's deferred-implementation list gains transport security integration as a FIFTH item; the list named four and was undercounting. `GCS_TLS_CLIENT_CERT_FILE` / `GCS_TLS_CLIENT_KEY_FILE` are removed from `.env.example` rather than wired, the GCS having no peer-federation role to consume them.

**How the false claim arose, recorded because the mechanism recurs:** §3.9.3 was written in Session 11 from the launcher's own inline comment, which named `security.peer_auth` as the compensating control. The comment described an intention; the specification restated it as an accomplished fact. This is Appendix C item (c)'s pattern inverted — a stale claim of PRESENCE rather than of absence — and it is the more dangerous direction, because a claimed absence invites an audit while a claimed presence forecloses one. The check that would have caught it is the one the working process already requires: measure the claim against the code before inheriting it. It was not run here because the section's source was a code comment, which resembles measurement and is not.

**The gap is inherited, not introduced — a finding that widens the scope.** A prior-art audit of the two sibling services in the same parent directory (`../mcs-service`, `../lvf-service`) found that NEITHER wires `i3_fe_core.security.tls` or `security.peer_auth` either; grepping both trees for core's security surface returns zero hits. All three services carry near-identical copy-template `main.py` launchers with the same ad hoc uvicorn TLS and the same verbatim `CERT_OPTIONAL` comment. The GCS did not regress from a working sibling pattern; it inherited an absent one three times over. Fixing the GCS alone therefore leaves two services in the same condition, and the remediation is properly a family-level change rather than a GCS-local one.

**Why the naive remediation must not be attempted, on evidence rather than caution.** LVF's git history shows it once enforced `ssl.CERT_REQUIRED` for inbound mTLS — in both `main.py` and a hand-built `SSLContext` for `gunicorn.conf.py` — then discovered that `UvicornWorker` silently downgrades unenforced `cert_reqs` to `CERT_NONE`, and reverted to `CERT_OPTIONAL`. That work and its revert predate LVF's adoption of `i3-fe-core` by roughly two weeks, so LVF's current unwired state is not a considered rejection of core's security layer: core's answer to that precise bug did not yet exist when the question was live, and nobody revisited it once core was adopted for everything else. The failure mode LVF documented is the decisive detail — enforcement that silently degrades to none is indistinguishable from enforcement that works, which is the same shape of defect as the false claim this decision withdraws. Any remediation must therefore use core's `gunicorn_mode` path or its proxy-terminated design and must be VERIFIED against a live handshake with no client certificate presented, rather than accepted on the strength of the configuration reading correctly.

**Three findings belong upstream to `i3-fe-core`, not to this specification, and are recorded here only so they are not lost:** (1) `ADOPTION.md`'s library-pattern guidance lists `SipNotifier`, `DiscrepancyReporting`, the state notifiers and `NtpClient` as the pieces to wire à la carte, and omits `security.tls` / `security.peer_auth` entirely — core demonstrates them only in its `create_app()` framework examples, which none of the three real services use. (2) `assert_core_conformance()` does not probe TLS, mTLS, or peer authentication, so no service running core's own conformance suite would be told about any of this. (3) Between them, these two mean every consumer adopting core via the library pattern will reproduce this gap by default and nothing will catch it — which is a sufficient explanation for why three independent services did.

**Severity is treated as higher than an ordinary documentation defect,** and the amendment ships ahead of the wiring rather than waiting to be superseded by it. A specification asserting a security control that does not exist is worse than one disclosing a gap: a reader performing due diligence on §5.4 enforcement would have come away reassured and wrong, and that misreading persists for as long as the wiring takes.

### 108 — §3.9.3, Appendix C.3 (closes the decision 107 gap; transport security integration is WIRED)

**Decision:** i3 §2.8.1 (cipher/version floor, PFS) and §5.4 (mutual authentication) are enforced on both GCS deployment paths. `i3_fe_core.security.tls` builds the server-side context for plain uvicorn (`gunicorn_mode=False`, genuine `CERT_REQUIRED`, since that process terminates TLS itself) and for gunicorn + `UvicornWorker` via a new `GcsUvicornWorker` subclass that injects the built context directly rather than passing through gunicorn's own certfile/cert_reqs-forwarding chain. Outbound calls to the Logging Service and Discrepancy Reporting use `httpx.AsyncClient(verify=make_client_ssl_context(...))`, following core's own `app/factory.py` wiring rather than LVF's federation-specific helper. A documented, default-off break-glass (`GCS_GUNICORN_CERT_OPTIONAL_FALLBACK`) exists for the gunicorn path, logs loudly at startup when set, and is explicitly not for production. This closes Appendix C.3's fifth deferred item and the KNOWN GAP block decision 107 opened in §3.9.3.

**Verification method, stated because it is the point of this decision:** enforcement is established by observed handshake outcome — actual connection attempts with no certificate, an untrusted certificate, a valid certificate, TLS 1.1, and a non-PFS cipher — not by reading back configuration. 180 attempts (100 sequential, 80 concurrent across 4 workers) against the gunicorn path produced zero acceptances without a valid client certificate; both deployment paths pass all five required cases. The result is backed by a standing regression suite, not a one-time measurement, and is scoped to the pinned toolchain versions recorded in the enforcing module's own docstring.

**A measurement defect very nearly produced the opposite conclusion, and the mechanism is worth recording because it recurs.** The first verification pass appeared to reproduce LVF's silent-downgrade failure — roughly a third of no-certificate connections looked accepted — and that result was written into shipped comments as a confirmed finding before it was caught. The measurement was wrong: TLS 1.3 performs client-certificate authentication post-handshake (RFC 8446 §4.3.2), so a rejected client's own `wrap_socket()` call returns successfully and the connection then receives zero bytes back; the test counted "no exception raised" as "accepted." The defect was caught only because the same fault reproduced deterministically on a second platform for the untrusted-certificate case, which forced isolation with a raw synchronous `ssl`-module diagnostic outside uvicorn entirely — that diagnostic showed the underlying TLS configuration had been correct throughout, and only the test's success criterion was wrong. Once the check was corrected to require an actual non-empty HTTP response rather than the absence of an exception, the enforcement conclusion reversed to the finding recorded above.

**This is the same shape of error as Session 9's six-county extract** (decision 89's near-miss, where an unrepresentative sample nearly produced a confident wrong fix to `_BASE_WEIGHTS`) — a measurement taken as ground truth without first checking whether the measurement apparatus itself could produce the result it appeared to show. It is also a sharper instance of the same pattern than Session 9's: here the verification method shared a structural property with the exact defect it was built to catch — a false-positive "success" signal that looks identical to a true one from the caller's side, which is precisely what makes a silent `CERT_NONE` downgrade dangerous to begin with. The corrective step in both cases was the same: before accepting a surprising empirical result, especially one about to justify shipping a more conservative (here, less-secure) default, isolate and re-verify rather than act on the first measurement.

**Reasoning for the escape-hatch decision:** `.env.example`'s contract, established by decision 100 and restated at §3.8, is that it lists every variable the service actually reads — a contract strong enough that it required removing variables the service does not (decision 107) rather than leaving them undocumented for being unused. An operator flag capable of disabling §5.4 enforcement is the hardest case that contract will face, and hiding it was considered and rejected: the failure mode of an undocumented flag is a service that satisfies §5.4 on paper while a nowhere-recorded switch has turned enforcement off, which is a close relative of the false claim decision 107 withdrew from §3.9.3 itself. Documentation paired with a startup warning was judged the safer control than obscurity — visible in both the static configuration reference and the running service's own logs, rather than relying on nobody finding it.

### 109 — §A.4, §A.5, Appendix C.3 (SIP transport for ElementState/ServiceState notification is WIRED)

**Decision:** i3 §2.4.1/§2.4.2's SIP SUBSCRIBE/NOTIFY transport for emergency-ElementState and emergency-ServiceState is implemented via `src/notify/sip_notifier.py`, a `SipWireAdapter` ported from lvf-service's maintained implementation (not mcs-service's untested copy of the same code) — real SIP message parsing via the `sipmessage` library, real UDP+TCP sockets bound in `start()`, wired as `i3_fe_core.notify.SipNotifier`'s `send_notify` and `authorize_subscriber` injection points. `authorize_subscriber` reads `GCS_SIP_ALLOWED_SUBSCRIBERS` (unset = accept all, matching both references). Startup is gated on `GCS_ENABLE_SIP`, a non-zero `GCS_SIP_PORT`, and leadership via the same `WorkerContext`/`is_leader()` GCS already uses for gunicorn multi-worker deployment — reusing LVF's gating pattern rather than MCS's ungated-await, since MCS's is scoped to its single-process-only posture and GCS's is not. Called from `server.py`'s composing layer after `lifespan_startup()` returns, not nested inside it, so the early-return path for missing GIS data never suppresses SIP. 18 tests ported from lvf-service's suite, adapted to GCS's identity fixtures; full suite green. Closes the SIP adapter item from Appendix C.3's deferred-work list.

**Left deliberately unwired, at parity with both references:** `validate_target_uri` (core's Contact-URI allowlist hook, preventing NOTIFY redirection/amplification) and `logging_client` (no `SubscribeLogEvent`s emitted for SIP traffic, despite GCS's `LoggingClient` being wired elsewhere). Neither LVF nor MCS sets these either. Recorded as an open follow-up, not an oversight: GCS wires `logging_client` into every other core component it constructs, so its absence here is a divergence from GCS's own pattern, not from the reference implementations.

### 110 — §A.3, Appendix C.3 (GCS log-event emit helpers are WIRED)

**Decision:** i3 §4.5's payload-logging MUST is discharged via `src/logging/log_events.py` and `src/logging/logger.py`, implementing decision 104's proposed `GcsQueryLogEvent`/`GcsResponseLogEvent` types (both subclassing `i3_fe_core.logging.logevent.LogEventPrologue`) and wiring `emit_log_event()` at every return path of both `/Geocode` and `/ReverseGeocode` — success, no-result, error, and admission failure alike, not success-only. Two deliberate divergences from decision 104's exact shape and from lvf-service's precedent: `GcsQueryLogEvent` carries the raw request body in a single payload field regardless of whether it later validates, rather than lvf-service's well-formed/malformed field split, since decision 104 asked for "whole payload," not a split; and `GcsResponseLogEvent.response_status` is mandatory and always populated with the actual HTTP status, not conditional. The query event fires unconditionally, before Stage 0 admission runs — a malformed or attack-shaped request is exactly the forensic record an ESInet operator most needs, and §4.5's obligation is not conditioned on validity; this follows lvf-service's own precedent of logging malformed LoST queries too, not a departure from it. Mechanism follows mcs-service's direct `emit_nowait()` rather than lvf-service's background-loop shim, since that shim exists only to bridge synchronous call sites lvf-service has and GCS does not — both `/Geocode` and `/ReverseGeocode` are `async def` throughout. `query_id`/`response_id` correlate as one UUID generated once per request and shared between its query and response events; no existing i3-fe-core correlation-id convention was found to reuse. 7 tests added; full suite green. Closes the log-event-helpers item from Appendix C.3's deferred-work list.

**Left deliberately unwired, at parity with both references:** `logging_client` is still not passed into `SipNotifier` construction — the same open item decision 109 records, since no reference implementation wires it either.

### 111 — §A.6, Appendix C.3 (GIS discrepancy report filing is WIRED)

**Decision:** i3 §3.7's SHOULD-level filing obligation, scoped by decision 99 to structural provisioning defects only, is implemented via `src/discrepancy/discrepancy_report.py`, ported from lvf-service's `discrepancy_report.py` with its LoST-report half dropped (GCS has no LoST role — only the GIS half of that module's shape applies). `GISProblem` is a deliberate three-token subset of i3 §3.7.11's full registry — `GeneralProvisioning`, `OmittedField`, `BadGeometry` — matched to what GCS's own detection paths can actually produce: GIS load/reload failure (`GeneralProvisioning`, filed directly from `lifecycle.py`'s existing `_on_gpkg_reload_failure`), `DataQualityFlag.NGUID_MISSING`/R3 (`OmittedField`), and `DataQualityFlag.NO_GEOMETRY`/decision 55 and `DataQualityFlag.MULTIPART_SEGMENT`/decision 53 (both `BadGeometry`). Two entry points: `file_gis_dr()` (async, called from lifecycle's already-async failure callback) and `fire_gis_dr()` (a sync fire-and-forget wrapper for the two synchronous request-path detection sites, `src/geocode/candidates.py` and `src/reverse/search.py`) — the wrapper reuses the same loop-capture-at-startup guard `_on_gpkg_reload_failure` already established for its own caller (a background thread), rather than inventing a second convention, and drops the report silently rather than raising when no loop is available, so a filing side-effect can never perturb the scoring computation the caller is actually there to produce. `_submit()` always logs locally and only POSTs when `GCS_DR_ENDPOINT` is set (mirroring lvf-service's never-raises guarantee exactly); `DiscrepancyReporting`'s existing similarity-key rate limiter is relied on to absorb repeat filings against a hot GIS dataset carrying many flagged records, the same mechanism lvf-service leans on for its own repeated-failure call sites. Closes the discrepancy-filing item from Appendix C.3's deferred-work list.

### 112 — §3.9.5, Appendix C.3 (load shedding declined as an implementation priority)

**Decision:** Load shedding is removed from Appendix C.3's active deferred-work list. §3.9.5 continues to state the correct status-code shape decision 100 already settled (429 with `Retry-After`, no i3-shaped body, never 454/468), should shedding ever be built — that determination is unaffected and not reopened. What changes here is priority, not design: no operational evidence currently held against this deployment shows sustained load reaching a level admission-layer shedding would need to answer, and no configuration variables are reserved for it (decision 100's `.env.example` contract already declines to speculate on variables the service does not yet read). This is a declined-for-now closure in the same register as decision 106's tier-ceiling decline, not a claim that shedding is unneeded in principle — revisit if operational experience shows sustained load the existing transport-layer protections (gunicorn worker limits, any fronting reverse-proxy rate limiting) do not adequately bound.

### 113 — §A.4, §A.5 (SipNotifier's `logging_client` hook is WIRED; `validate_target_uri` remains deliberately unimplemented)

**Decision:** `i3_fe_core.notify.SipNotifier`'s optional `logging_client` parameter is now wired in `SipWireAdapter.__init__` (`src/notify/sip_notifier.py`) and passed through from `runtime_state.logging_client` at construction (`src/app/lifecycle.py::maybe_start_sip`), matching how every other GCS core component already receives it. A `SubscribeLogEvent` (§4.12.3) is now emitted for every processed SUBSCRIBE, accepted or rejected. This closes half of the open item decisions 109/110 flagged.

**`validate_target_uri` is left unwired, and this is now a considered decision rather than an inherited gap.** Unlike `logging_client` — a mechanical pass-through of an already-built component, identical to GCS's existing pattern — `validate_target_uri` has no reference implementation anywhere in the family: LVF and MCS both leave it `None`, confirmed directly against their source. Building it for GCS alone would mean GCS originating and shipping a novel security-adjacent design (a Contact-URI/NOTIFY-target safety check) with no sibling implementation to validate against or diff from, ahead of every other FE that shares this library. GCS's standing practice throughout this arc of work — SIP, logging, discrepancy filing — has been to port working, tested reference behavior, not to originate ahead of it. `validate_target_uri` stays parked on that basis, in the same register as decision 112's load-shedding deferral: a known, named, unimplemented hook, not a silently-dropped one. Revisit if a reference implementation appears in LVF or MCS, or if operational/security review independently calls for it.

### 114 — §6.4, §8.4, §12.3 (468 gains a fixed, non-distinguishing body reason)

**Decision:** `no_result_response()` (`src/api/status.py`) now returns a body on every 468 — `{"reason": "No result was derivable for the query."}` — identical on every call regardless of which §6.4 path (or, on the admission side, which `AdmissionError`) produced it. Previously 468 carried no body at all, citing §1.2.1 ("the format permits it is not the standard asks for it"). The caller-supplied `reason` argument each call site already computes is still passed in and is still logged server-side (`log.info("468 No Address Found: %s", reason)`); only the wire body is now fixed rather than absent.

**Reasoning:** Raised by the user reviewing the regression suite: 454 has carried a `reason` body since decision 36, and 468 carrying none reads as an unexplained inconsistency rather than a deliberate choice — worth resolving one way or the other and recording, rather than leaving as a standing §16-adjacent asymmetry. Two ways to resolve it were weighed:

  1. Put the existing `reason` argument on the wire verbatim, matching 454 exactly.
  2. Put a fixed, invariant string on the wire, carrying no more information than the status code already does.

(1) was rejected. At least one call site's `reason` is not generic: the §6.3 `AmbiguousResult` path (`src/api/geocode.py`) passes candidate count and span in metres (`"4 candidates span 52693.0 m, beyond the configured GCS_AMBIGUITY_TOLERANCE_M of 150.0 m"`), and the `AdmissionError`-routed paths (`failure_response`, `src/api/status.py`) pass admission-specific text (e.g. "The elected location carries no civic location information."). Exposing either would silently reopen §6.4's own stated invariant — "no coverage test distinguishes them" — under cover of a consistency fix, which is a materially bigger and unreviewed change wearing a small one's justification. (2) does not have that problem: it closes the shape gap with 454 (every non-2xx response now carries a `reason` field, so a client need not special-case 468 as bodyless) while conveying nothing beyond what the status code alone already asserts. §6.4 is amended in this session to state this explicitly rather than leave the "no field to carry the difference" phrasing technically false once a field exists.

**Verification:** `tests/conformance/test_admission_http.py::test_geocode_with_only_a_geodetic_location_is_468` and `tests/conformance/test_log_events.py::test_no_result_response_carries_468_and_a_fixed_generic_reason` assert the fixed string, not the admission-specific text that triggered the particular 468 under test. `tests/regression/harness.py::parse_outcome()` extracts and compares the 468 `reason` the same way it already did for 454, so a regression that silently reintroduces a distinguishing 468 reason — or drops the body again — surfaces as a diff in `tests/regression/`, not a silent pass.

### 115 — §8.1, §8.3, §12.1 (response bodies are indented; a `usage-rules`-triggered pretty-print bug is fixed)

**Decision:** Every wire response now indents both layers it's built from: the embedded PIDF-LO XML (`src/api/wire/pidf_xml.py::to_string()`, 2-space, one element per line) and the JSON wrapper around it (`src/api/status.py`, via a new `_PrettyJSONResponse(JSONResponse)` used by `success_response()`, `error_response()`, and `no_result_response()` in place of Starlette's bare `JSONResponse`). Applies on all four resources, on every status code that carries a body (200, 454, and 468 as of decision 114).

**Reasoning:** Raised by the user, reviewing a regression-suite dump of every fixture's request/response — the JSON was one line and the embedded XML string was unreadable escaped `\n` noise. Neither i3 nor the underlying RFCs (3863, 4119, 5491) have any opinion on incidental serialization whitespace — §1.2.1's "wire vocabulary" concern is about fields and status codes existing or not, not about how many spaces separate them — so indenting is not a departure from anything normative: a JSON parser and an XML parser see byte-for-byte the same document either way, only a human reading raw output sees a difference. Weighed and declined: reformatting only in developer-facing tooling (the regression runner, a standalone review script) rather than in the live service. Declined because the user's actual request was for the live server's real responses to be readable, not for a better developer tool standing in front of them — and because, having found the bug below, the honest fix was in the one place that's true for every consumer, not just this project's own test tooling.

A genuine formatting bug surfaced during verification, not something introduced to justify this decision: `build_presence()` (`src/api/wire/pidf_xml.py`) appends `usage_rules` via `copy.deepcopy()` of an element parsed out of the CALLER's incoming request. That copy still carries the whitespace `.tail` from its position in the caller's own document — meaningless once relocated into the GCS's response, but enough that `pretty_print=True` (which only fills in indentation where `.tail`/`.text` is still `None`, never touching anything already set) silently gave up reformatting the entire `<gp:geopriv>` subtree around it. Every response carrying a `usage-rules` element from the input — which is every response, since `build_presence()` always emits one (empty or copied) — was affected, invisibly, before this session: `<gp:geopriv>` through `<gp:usage-rules/>` serialised as one flat run while everything above and below it looked properly indented, which is exactly the kind of defect that a human never manually re-formatting responses would never have noticed. `to_string()` now calls `etree.indent(presence, space="  ")` before `etree.tostring(..., pretty_print=True, ...)` — `etree.indent()` recomputes every structural whitespace node unconditionally, so it holds regardless of which payload elements were freshly built (`.tail`/`.text` already `None`) and which were copied in from elsewhere (already set to something stale).

**Verification:** Full `pytest` suite (521 passed, 5 skipped) is unaffected — schema validation against the master XSD and every content assertion are insensitive to insignificant whitespace, as expected. The `tests/regression/` suite (38/38) required no golden reseed: `parse_outcome()` compares semantically-reduced fields extracted via `lxml.etree.fromstring()`/`json.loads()`, both whitespace-insensitive, so a pure formatting change is invisible to it by construction — itself a small confirmation that storing raw responses and reducing at compare time (decision 114's discussion of the golden-file format) was the right call.

### 116 — §3.9.1, §8.1, §12.1, §16 (strict interface's 200 response corrected to real XML, superseding Session 3)

**Decision:** The strict interface's 200 response — `/Geocode` and `/ReverseGeocode` only, not the enhanced pair — is now real `application/xml`, not `application/json`. `src/api/wire/strict_xml.py` builds `<GeodeticData><pidfLoGeo><![CDATA[...]]></pidfLoGeo></GeodeticData>` and `<CivicAddress><pidfLoAddress><![CDATA[...]]></pidfLoAddress></CivicAddress>`; `src/api/status.py::success_xml_response()` serves it. This **supersedes** the Session 3 finding (§3.9.1) that the YAML's declared `application/xml` content type and its `{pidfLoGeo: string}` schema were irreconcilable, which is why this implementation had emitted `application/json` instead since Session 3. §3.9.1 and the §16 "Normative YAML content types are incoherent" row both carry correction notes pointing here rather than being silently rewritten, per this register's own no-silent-deletion rule.

**Reasoning:** Raised by the user, following on from decision 115's readability fix — decision 115 made the embedded XML properly indented, but a JSON string still cannot contain a literal newline (RFC 8259); any multi-line content embedded as a JSON string value necessarily serialises with escaped `\n` sequences, on the wire, with no server-side fix available while the 200 body stays JSON. Before treating that as a hard limit, two things were checked directly rather than assumed:

  1. **`i3-fe-core`'s own precedent.** lvf-service's LoST responses are real `application/xml` with no JSON wrapper at all (`Response(..., media_type="application/xml")`, `src/lost/find_service.py`) — but LoST (RFC 5222) was never redefined as a JSON/REST interface, so it never had this specific tension to resolve. The shared `i3_fe_core` components both services already depend on (Discrepancy Reporting, Versions) emit plain JSON with genuinely JSON-shaped payloads, not XML-in-JSON. Nothing in the family currently does what GCS's strict interface had been doing; informative, but not a direct precedent either way.
  2. **The OpenAPI 3.0 specification itself**, fetched and read directly rather than assumed from memory (see chat log for the exact exchange) — the XML Object section and Swagger's own reference documentation are explicit that, absent an `xml:` annotation, an object schema's properties become child elements named after the property, nested under a root element named after the schema. `GeodeticData { pidfLoGeo: string }` under `application/xml`, with no `xml:` annotation anywhere in the YAML, therefore has a real, standard default reading: `<GeodeticData><pidfLoGeo>...</pidfLoGeo></GeodeticData>`. The Session 3 "irreconcilable" claim did not consider this — it is not that OpenAPI is silent and this implementation invented a convention; OpenAPI has a stated default the YAML never overrode.

  How the string-typed property's own text (which is itself XML markup) gets represented inside that child element is not an OpenAPI question — OpenAPI's XML object doesn't address it, and doesn't need to, because it's a base-XML question with a standard answer: a CDATA section carries text verbatim, which is exactly what a JSON string value would have carried, just without JSON's control-character escaping requirement. This closes decision 115's readability gap for real: the embedded PIDF-LO now reaches the wire with genuine newlines and indentation, readable directly from `curl` with no post-processing, because CDATA content is not JSON-string-escaped.

  The i3 standard PDF itself was also checked for anything arguing against this (not merely for something arguing for it) — searched for `CDATA`, `content-type`, and `media type` directly; none appear in connection with the GCS or MCS sections. §4.4 (MSAG Conversion Service) uses the identical "returns ... as a string" phrasing i3 §4.5 uses for GCS ("A successful query returns an AQS MSAG address as an XML object in a string"), confirming that phrasing is i3's deliberate, repeated style for these conversion FEs rather than a one-off drafting artifact in the GCS section specifically — but the phrasing describes the value's nature (textual), not the envelope encoding, and is satisfied equally by a JSON string or an XML CDATA section. Nothing found argues for a third reading or against this one.

**Scope — strict interface's 200 response only:**
  - The **enhanced interface** (`/GeocodeEnhanced`, `/ReverseGeocodeEnhanced`) is untouched. `candidates[]` is GCS's own additive, non-normative schema (§2.2) — never bound to the YAML's declared content type — and stays JSON.
  - **454 and 468** on the strict interface stay JSON (`{"reason": ...}`, decisions 36 and 114). The YAML declares no schema or content type for either — no `content` block at all, only a bare `description` — so there is nothing for either to be reconciled against; decision 114's reasoning for keeping 468's body fixed and JSON-shaped is unaffected by this decision.
  - The **request body** (JSON string or raw XML, both accepted per decision 95) is unaffected — this decision is about the 200 response only.

**Verification:** Full `pytest` suite (521 passed, 5 skipped) after updating `tests/conformance/test_conversion_http.py`'s `_pidf()` helper and every test asserting the strict interface's body shape (`test_the_response_body_is_real_xml_carrying_the_pidf_lo_as_cdata`, formerly asserting the JSON reading, now asserts `application/xml`, a `<GeodeticData>`/`<CivicAddress>` root, and a literal `<![CDATA[` in the raw response bytes). `tests/regression/harness.py::parse_outcome()` branches on the response's actual `content-type` header to choose XML or JSON parsing for a 200 body; the 14 strict-200 golden fixtures were reseeded (`ADM-MULTI-LOC-STRICT-001`, `ADM-JSON-BODY-001`, `FWD-SSAP-EXACT-001`, `FWD-RCL-INTERP-001`, `FWD-STREET-ONLY-001`, `FWD-GAP-HNO-001`, `FWD-DROPPED-HNO-STRICT-001`, `REV-POINT-SSAP-001`, `REV-RCL-SYNTH-HNO-001`, `REV-POLYGON-001`, `REV-ELLIPSE-001`, `REV-SPHERE-VALID-001`, `REV-CROSSCOUNTY-001`, `REV-DUPLICATE-TIEBREAK-001`) — the other 24 (enhanced, 454, 468, malformed-request) needed no change, confirming the scope above held in practice, not just on paper. The `]]>` edge case (reachable via the input's echoed `entity`, decision 12) was checked directly: `lxml`/`libxml2`'s `etree.CDATA()` splits an embedded `]]>` into adjacent CDATA sections automatically and round-trips correctly through `etree.fromstring()`, so no additional escaping code was needed for it.

### 117 — §3.9.2, §12.2 (enhanced-interface YAML brought current with decision 116; its 454/468 gain the body schema they always emitted but never declared)

**Decision:** Two corrections to `references/i3-geocode-conversion-enhanced.yaml`, discovered by a documentation-alignment pass rather than by new implementation work. First, its header comment argued the `application/json` choice on the strict resources' YAML content-type/schema pair being "irreconcilable" — the exact Session 3 reading decision 116 superseded. The comment is rewritten: the enhanced interface's `application/json` choice stands on its own (GCS's own additive schema, never bound to the normative YAML's content type either way, and a natural fit for a candidate-list shape) rather than resting on a defect the strict interface turned out not to have. Second, the `'454'` and `'468'` response objects on both `/GeocodeEnhanced` and `/ReverseGeocodeEnhanced` gain a `content` block — a new shared `ErrorReason` schema (`{reason: string}`) — matching what `src/api/status.py` has emitted on every non-200 response since decisions 36 and 114 respectively. Previously both codes declared only a bare `description`, as if they carried no body; decision 92 reconciled the 200 shape field-for-field but did not audit the error shapes, and nothing since has either.

**Reasoning:** `enhanced.py`'s own docstring states the normative relationship plainly — "The YAML is the normative spelling; the code is expected to match it rather than the reverse" — which makes an undeclared body on 454/468 a genuine schema gap against code that has carried one since before this file was last touched, not a stylistic nit. The stale content-type reasoning is a smaller defect in the same register as the one decision 116 already fixed at §2.1 and §3.9.1: a superseded claim left standing in a file the register's own no-silent-deletion rule does not automatically reach, because this file is a YAML artifact rather than prose in this document. Both are corrected here together since both surfaced in the same pass and both are small, mechanical alignments rather than new design.

**Verification:** `python -c "import yaml; yaml.safe_load(open('references/i3-geocode-conversion-enhanced.yaml'))"` parses cleanly; the new `ErrorReason` `$ref` resolves under both resources' `454` and `468`. No code change — `src/api/status.py`'s `error_response()` and `no_result_response()` already emit exactly the `{reason: string}` shape now declared. Full `pytest` suite and `tests/regression/` suite unaffected (schema-only YAML edit, no route or serialisation change).

# Appendix C — Open Tasks and Questions

Working state carried between sessions. Emptied as items are resolved.

## C.1 Source Documents Not Yet Read

| **Source**                                                                              | **Why it matters**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
|------------------------------------|------------------------------------|
| NENA GitHub OpenAPI YAML for the GCS interface                                          | READ (Session 3) — NENA911/Geocode-Conversion-Service, i3-geocode-conversion.yaml v1.0. Findings adopted in §2.1, §3.6.2, §3.9.1, §8.1, A.1; defects logged in §16. Removed from the unread list.                                                                                                                                                                                                                                                                                                                                                               |
| i3 §10.31 Match Type registry — full token list                                         | READ (Session 4) — seven tokens: Address, RoadCenterline, PoliticalBoundary, MsagCommunity, CoverageRegion, Hybrid, Other. Mapping adopted in §12.2; the registry’s coarseness relative to locationType is logged in §16. Removed from the unread list.                                                                                                                                                                                                                                                                                                         |
| STA-006.3 §6.1 Site/Structure Address Point Placement Method registry — full token list | READ (Session 4) — Structure, Site, Parcel, Geocoding, ExteriorAccess, InteriorAccess, InteriorCentroid, PropertyAccess, Unknown. Consequences adopted in §10.5 (sharpens the distance bias; surfaced per candidate rather than adjusting the rule), §10.6 (Geocoding damps the spatial-fit score as a double approximation), and §7.4 (InteriorCentroid is this document’s §7.5 convention, already registered). §6.2’s Address Polygon Extent Method registry was read at the same time and corrects §7.4’s reachability claim. Removed from the unread list. |
| RFC 5491 §5 (shapes) and §7 (confidence)                                                | Resolved (Session 2): confidence is not RFC 5491 §7 as originally assumed — RFC 5491 offers only a one-line 95%+ recommendation. The actual confidence element/schema is RFC 7459 (added to §1.1). RFC 5491 §5 shapes confirmed via direct read. Resolved (Session 4): accepted input shapes for ReverseGeocode are all eight §5 GeoShape forms (§9). Resolved (Session 11): the gs: prefix and URI in §1.4 are confirmed against the OGC GML-pidf-lo-shape schema itself (`schemas/gml-geoshape/GML-pidf-lo-shape.xsd`). Nothing remains on this row.                                                                                                                                                        |
| NENA-REQ-003                                                                            | Cited as the basis for 3D support and HAE; not yet read directly.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

## C.2 Open Questions

| **\#** | **Question**                                                                                                                                                                                                                                                                                                             | **§** |
|------------------------|------------------------|------------------------|
| 1      | RESOLVED (Session 2) — Reframed rather than answered as posed: the merge case is a legitimate multi-candidate answer (generic query, distinct structures on one parcel), not a tolerance-tuning problem. i3-improved returns ranked/scored candidates; i3 interface averages with uncertainty sized to extent. See §6.3. | 6.3   |
| 2      | RESOLVED (Session 2) — Chain: geometry Z → Altitude → Elevation. No discrepancy report on mismatch. See §7.1.                                                                                                                                                                                                            | 7.1   |
| 3      | RESOLVED (Session 3) — Echo the input entity where present; HELD-style unlinked pseudonym where absent (RFC 5985/6753). retransmission-allowed passes through. See §8.3.                                                                                                                                                 | 8.3   |
| 4      | RESOLVED (Session 2) — One scoring function, not a two-stage exact-then-fuzzy pipeline, following prior art (PostGIS Tiger, Nominatim). Exact match sits at the top of the same per-field similarity scale. See §6.5.                                                                                                    | 6.5   |
| 5      | RESOLVED (Session 2) — Single flat configurable offset (GCS_RCL_OFFSET_M), perpendicular, side-dependent, never on the line itself. See §7.3.                                                                                                                                                                            | 7.3   |
| 6      | RESOLVED (Session 3) — One web service, per the normative YAML: one server base, one /Versions covering both operations. See A.1.                                                                                                                                                                                        | A.1   |
| 7      | RESOLVED (Session 11, decision 106) — the element model stays a plain module in this repository (`src/engine/models.py`). The deciding condition ("decide when code exists to observe") is met: the vocabulary is the GCS's own under decision 58's standalone scope, no sibling FE consumes it, and extraction for a consumer that does not exist would be speculative packaging. Reopen only when a second consumer actually appears.                                                                              | 6.5, 11.1   |
| 8      | RESOLVED (Session 3) — 454 on both operations with a body reason; the poor fit and YAML asymmetry are §16 rows. See §4.1, §8.4.                                                                                                                                                                                          | 4.1   |

**Open items after Session 5:** The four pre-implementation edge cases flagged at the close of Session 4 — zero-length ranges, single-address ranges, parity mismatches, and §4.2’s multiple-location rule — are resolved (§7.2, §4.2). Remaining: (a) RESOLVED (implementation) — GCS_RCL_ENDPOINT_MARGIN_M, GCS_RCL_OFFSET_M, GCS_MIN_MATCH_SCORE, and GCS_REVERSE_SEARCH_RADIUS_M now carry defaults in `.env.example` (15.0, 10.0, 60.0, 250.0 respectively), each flagged there as a `[PROPOSAL]` value not yet tuned against real data; (b) RESOLVED (Session 11, decision 106) — the tier-ceiling weights (100/90/80/75/50) stay fixed by the specification, configurability declined: a confidence value's meaning must not vary by deployment; (c) RESOLVED — the enhanced-interface candidate schema `references/i3-geocode-conversion-enhanced.yaml` is reconciled and normative, decision 92; (d) RESOLVED — the §10.6 spatial-fit components are now written as formula in §10.6 itself: distance normalised against GCS_REVERSE_SEARCH_RADIUS_M with containment at the top of the scale, extent damping `radius_m / (radius_m + extent_m)` (decision 66), and the Geocoding placement penalty settled by decision 83; (e) RESOLVED (implementation) — the §10.4 tie-breaking identifier is the feature’s NGUID, carried on the engine record model as `nguid` with an explicit `is_tie_breakable` predicate; a null NGUID makes a record ineligible for deterministic ordering and is reported through the discrepancy path (`NGUID_MISSING`) rather than replaced with a local surrogate (filing scope settled by decision 99).

## C.3 Sections Not Yet Drafted

§9, §10, §11, §12, and §14.1 are now settled, which closes the ReverseGeocode side. The former entries on this list are all now WRITTEN: the §6.5 similarity mechanisms (decisions 66–82, closed by 89) and the §10.6 spatial-fit components (decisions 66, 83); the enhanced-interface YAML for §3.9.2 and §12.2 (decision 92); §15 pseudologic (decision 84, both directions); §3.4, §3.5, §3.8 (decisions 93, 94, and §3.8's reconciliation, Session 10); and §3.9.4, §3.9.5, §4.3 (decisions 100–102, Session 11). Nothing remains undrafted. Both algorithm chapters are substantively complete: §7.1–§7.5 forward, §9–§12 reverse. What remains open across the document is only the §16 gap register's NENA-facing rows and the deferred implementation work — none of it now blocked on an unsettled specification question. Transport security integration, added as a fifth deferred item by decision 107, is WIRED and verified (decision 108). The SIP adapter (§A.4/§A.5, decision 109), log-event emit helpers (§A.3, decision 110), and GIS discrepancy filing (§A.6, decision 111) are each now WIRED as well, ported from lvf-service's maintained reference implementation and verified against GCS's own test suite. Load shedding (§3.9.5) is the one remaining item, and it is no longer carried here as active deferred work: decision 112 deprioritizes building it rather than scheduling it, with the status-shape question decision 100 already settled left standing unaffected should it ever be picked back up.

## C.4 Implementation-Discovered Questions

Questions surfaced while building the service against real provisioned data
(`data/data.gpkg`). This subsection replaces the former standalone
`docs/spec-questions.md`; the specification is now the single record. Its
Q-numbering is independent of C.2 above — code and tests cite these numbers, so
they are retained even once an item is resolved. Resolved items are kept as
one-line pointers to the decision or section that carries the answer; only
genuinely open items are stated in full.

### Resolved (carried by the specification)

| # | Resolution |
|---|---|
| R1 | An interpolated rung-2 result carries no Z and is 2D (EPSG:4326): the only available Z is road-surface, and §7.3's perpendicular offset moves it horizontally onto a parcel where it is no longer that structure's height. See §7.3. Generalized by decision 85 to EVERY RCL-derived answer including rung 3, on the broader ground that RoadCenterLine is not a declared 3D-capable class (§10.5) — so the layer's Z is not authoritative at any rung, displaced or not. |
| R2 | §7.2's validation columns are `Valid_L` / `Valid_R`, not `Validation_L/R`. Confirmed against provisioned schema; implemented in `src/gis/records.py`. |
| R3 | `NGUID` is the §10.4 deterministic tie-break identifier. A null NGUID makes a record ineligible for deterministic ordering and is reported via the discrepancy path, never replaced with a local surrogate (the GeoPackage FID is not stable across reloads). Closes Appendix C item (e). |
| R4 | Ingestion strips surrounding whitespace and normalises empty/whitespace-only text to null (`src/gis/records.py::_plain`); interior whitespace untouched. Forced by fixed-width export padding. Now written into §3.2 (decision 103). |
| Q3 | `GCS_AMBIGUITY_TOLERANCE_M` — required, no specification default; set per deployment in `.env`. See decision 54. |
| Q12 | RCL `MultiLineString` — single-part is normal; multi-part is a flagged data-quality condition, not silently traversed. See decision 53. |
| Q13 | Horizontal position — geometry is authoritative; the `Longitude`/`Latitude` columns are not position inputs. See decision 52, subsequently superseded by decision 55. |
| Q18 | Uniformly-placeholder geometry Z (every SSAP Z is 0) — the non-zero admission test treats a 0 Z as absent. See decision 51, subsequently superseded by decision 55. |
| Q20 | Geometry-only position on every axis (X/Y and Z from the shape geometry; attribute columns not consulted; no-geometry record yields no located match). See decision 55. |

### Formerly open — all resolved as of Session 11, retained under stable numbering

#### Q1 — RESOLVED, see spec decision 95.

`GET /Gcs/Versions`, one segment above the versioned base per the YAML's own
`servers` override, and unversioned by design: a client must reach version
discovery before it knows which versions exist. Stated in §3.9.1 and §A.1.

---

#### Q2 — RESOLVED, see spec decision 95.

The unresolvable `i3-common.yaml` `$ref` is recorded as a §16 row, alongside
the content-type incoherence. Not blocking; `i3_fe_core.web_service.versions`
supplies the i3 §4.12 body shape.

---

#### Q4 — RESOLVED, see spec decision 96.

Accepted and stated in §10.2 rather than repaired: at any horizontally useful
radius the vertical component never binds — decision 39's recorded surrender
showing up in practice. No separate vertical bound is introduced, for the same
no-defensible-constant reason §10.5 gives (decision 60). Revisit if a
volumetric feature class makes the vertical axis load-bearing.

---

#### Q5 — RESOLVED, see spec decision 97.

A confidence at or beyond RFC 7459's exclusive bounds serialises as the token
`"unknown"` on the PIDF-LO path — never clamped to a number the service did
not compute. The tier ceiling table ending at 100 is correct: 100 is the top
of the internal scale, and the inexpressibility is a wire-schema constraint.
The enhanced JSON path declares inclusive bounds (decision 92) and is
unaffected. `build_confidence` implements this.

---

#### Q6 — RESOLVED, see spec decision 98.

`/dr` is the canonical base, giving §4.12's required Versions entry point a
home at `/dr/Versions`; the root aliases are retained deliberately for i3's
no-base-path reading and i3-fe-core's conformance suite, withdrawable if a
future i3 revision states a base path. The XACML-obligation note is subsumed
by decision 99.

---

#### Q7 — RESOLVED, see spec decision 99.

The GCS files about structural provisioning defects only — GIS load/reload
failure, null NGUID (R3), multi-part segment (decision 53), no usable geometry
(decision 55) — and never about attribution content (decisions 29, 45, 46).
The engine's data-quality flag vocabulary is the filing vocabulary.
`src/discrepancy/` remains thin and unwired, now unblocked.

---

#### Q8 — RESOLVED, see spec decision 94.

§3.5 now states this directly: stale data is preferred over no data. A failed
hot-reload leaves the previously-loaded dataset in place and reports
`ElementState = SERVICE_DISRUPTION`, while the service keeps converting
against the last-good load underneath that signal — available and reported as
degraded, not stopped. This is distinct from never having loaded any data at
all, where both ElementState and ServiceState report their down states
because there is nothing to fall back to. `/ready` reporting 503 while
`is_reloading()` is true (§3.9.4) is unchanged and is the narrower,
traffic-gating signal layered on top of the broader health picture above.

---

#### Q9 — RESOLVED, see spec decision 100.

The candidate framing is adopted: shedding is a transport-layer response
emitted before admission, outside §1.2.1's closed set — the same reading that
already permits the 413 the middleware emits. A shed request receives 429 with
`Retry-After`; never 454, never 468. Shedding itself remains unimplemented,
and no configuration variables are reserved for it until an implementation
reads them.

---

#### Q10 — RESOLVED, see spec decision 104.

Confirmed by direct read of the full i3 §4.12.3.7 registry (44 types): no GCS
LogEvent type exists, and the LoST/ALI query-response pairs are scoped by
their own definitions to other services. §16 row; `GcsQueryLogEvent` /
`GcsResponseLogEvent` proposed on the LostQuery/LostResponse pattern. The
privacy posture of §4.5's payload-logging MUST is now stated in §A.3.
`src/logging/` is unblocked (the prologue subclasses implement the proposal),
though writing them remains deferred work.

---

#### Q11 — RESOLVED, see spec decision 101.

§3.9.4 is written: `/health` is liveness and always returns 200 while the
process is up; `/ready` carries the 503 and is the only traffic-gating
endpoint. The divergence from i3-fe-core's own health-route convention is
recorded as deliberate; core's conformance suite accepts either code.

---

#### Q14 — RESOLVED, see spec decision 95.

Both body forms — JSON string and raw XML — are accepted, discriminated by the
first non-whitespace byte, with Content-Type logged rather than enforced. Now
stated in §3.9.1 so a sender can tell from the spec that either form works.

---

#### Q15 — RESOLVED, see spec decision 105.

Accepted as a documented validation-scope boundary rather than closed: only
the `dm:*` container structure escapes validation — lax processing still fully
validates the geopriv/civic/GML content inside it, so a malformed wrapper can
affect only Rule #8's container classification. The closure path (adding RFC
4479's data-model schema to the wrapper) is named and deliberately not taken.
The document-order-versus-Rule-#8 structural fact is adopted into §4.2.

---

#### Q16 — RESOLVED, see spec decision 102.

§4.3 is rewritten to point at §4.2, which already answers both cases the
drafting note posed: wrong-profile-only elects and fails the chunk check
(468, no walking the document); both-profiles selects by namespace within the
elected `<location-info>`, never by position (Rule #7). No standalone profile
gate exists or may be built.

---

#### Q17 — RESOLVED, see spec decision 102.

A well-formed, schema-valid document carrying no location at all returns 468,
stated in §4.2: the same nothing-convertible shape as the chunk-check case,
in a request that is not malformed. The 468-asserts-a-search counter-argument
is acknowledged and outweighed by consistency with decision 50's settled case.

---

#### Q19 — RESOLVED, see spec decision 103.

§3.2 now states it: Placement Method arrives as registry token text (no join;
the field is typed `str`), provisioned spellings vary from the registry
(`Property Access` vs `PropertyAccess`), and every registry-token comparison —
§10.6's Geocoding damping in particular — runs after trim-and-casefold
normalisation. The token passes through to the enhanced interface as the SI
spelled it. The Parcel-at-42% disclosure point is recorded with §10.5's
argument.

---

#### Q21 — The element model's field vocabulary is not written down

**Resolved, see spec decisions 62 and 63.** The `ca:` ↔ STA-006.3 mapping is transcribed into §3.10 from STA-004.2, which supplies it element by element and governs on disagreement. `Add_Number` is correctly an integer (STA-004.2 narrows RFC 5139's string typing); `701B` and `194-03½` decompose per STA-004.2's own rules into prefix/integer/suffix with the original preserved in `AddNum_Cmp`. An address number that cannot reduce to a non-negative integer is dropped and the request proceeds without it, reported on the enhanced interface. Appendix C.2 question 7 (where the element model is packaged) remains open.

---

#### Q22 — A rung-3 line answer carries per-vertex Z; decision 55 speaks to points

**Resolved, see spec decision 85.** Dissolved rather than answered on its own terms: RoadCenterLine is not a declared 3D-capable feature class (§10.5), so the `MultiLineString Z` geometry type is an export-format artifact rather than an assertion that the Z means anything. The layer's Z is never consulted, at any rung. A rung-3 STREET_SEGMENT answer is therefore 2D, EPSG:4326 — the same as rung 2 — which generalizes R1 to every RCL-derived answer rather than conflicting with it. The per-vertex-versus-whole-line admission question does not arise, since no admission test runs on a Z that is never read. `Candidate.crs` no longer abstains for a line answer, and the rung-3 `gml:LineString` carries an explicit `srsName` of EPSG:4326 instead of omitting the attribute.
---

#### Q23 — Endpoint margin on a segment shorter than twice the margin

**Resolved, see spec decision 56.** A segment whose usable length would go zero or negative after the margin is trimmed returns the segment midpoint at INTERPOLATED_POINT, on decision 48's worst-case-error rationale; the margin does not participate and no new constant is introduced.

---

#### Q24 — Where does §6.2's filter end and §6.5's scoring begin?

**Resolved, see spec decision 61.** Dissolved rather than answered: there is no filter, so there is no boundary. Every temporally-valid record is scored on every request. §3.4's temporal exclusion (a correctness test) and `GCS_MIN_MATCH_SCORE` (applied after scoring) are unaffected.

---

#### Q25 — RFC 5491 shape for §6.3's merged extent

**Resolved, see spec decision 57.** §7.4's anti-synthesis rule is scoped to single matches; the merged case returns a Circle (centroid + radius to the farthest merged candidate). The geocode core emits centre and radius-in-metres; the wire layer renders the GeoShape.

---

#### Q26 — §10.5's vertical band on provisioned feature classes

**Resolved, see spec decision 60.** The band is scoped to classes carrying a vertical extent, and §10.5 now states that no provisioned class has one — a point Z is a slot, not a range. The band is inert today and retained as forward-looking structure; no vertical tolerance is admitted. Interacts with Q4, which remains open.

---

#### Q27 — Centerline tier at ordering time versus reported tier

**Resolved, see spec decision 59.** RCL candidates tier uniformly as INTERPOLATED_POINT for §10.3 ordering; the tier reported on the answer is §11.2's and may be lower. §10.3 now states the consequence explicitly rather than resolving side and ranges during the search, which would contradict §10.1's single pass.

---

#### Q28 — STA-004.2's zero rule for an address number with no integer portion

**Resolved, see spec decision 64 (amending 63).** §3.3.3.8's "enter 0" instruction governs authoring a GIS record, where a value must be stored, not interpreting a query, which may carry no address number at all. The drop stands; no zero is substituted. Reported to NENA as a rule stated where a reader looking for query behaviour would find it.

---

#### Q29 — Does RFC 7459 confidence travel on the strict interfaces?

**Resolved, see spec decision 65.** It does, on all four resources. §8.1's and §12.1's "and nothing else" claims are narrowed to the `GeodeticData` and `CivicAddress` response objects, which gain no property; confidence rides inside the PIDF-LO payload as IETF vocabulary, minting nothing of i3's. §8.1's indistinguishability consequence now states what survives: a coarse confidence, and nothing about why. §16 records that i3 leaves population of the element unstated.

---

#### Q30 — Categorical vs. free-text similarity

**Resolved, see spec decision 82 (which supersedes 81's brief gate design before implementation).** A1, Country, and St_Dir are compared as binary exact-match after normalization — weighted terms scoring 1.0 or 0.0, no edit distance, no Soundex, no gate. A2 stays under decision 72's hand-typed blend: County is spelled out by a call-taker, not drawn from a short fixed list. Fully closed; no further code change contemplated.

---

#### Q31 — RCL side hint precedes §7.2's own side selection

**Resolved, see spec decision 87.** Dissolved on its premise: §7.2/§7.3 do not select side geometrically in the forward direction — they select it from Add_Number parity, the same rule decision 67 arrived at independently for scoring. There is one forward side-selection rule consulted at two points in the pipeline, so the geometry-versus-parity disagreement this question anticipated cannot arise. The reverse direction projects because a reverse request carries no house number to derive parity from — a difference in available input, not in policy. The two ends' *fallbacks* when parity fails to resolve do diverge (scoring keeps best-of-both-sides; §7.2 lets the asserted range govern), and decision 87 accepts that divergence explicitly rather than aligning it: it requires a record whose parity field is null or contradicts its own range, a data-quality defect §7.2 already declines to repair.
---

#### Q32 — Soundex digit blindness on numbered/ordinal street names

**Raised:** tools/sample_pairs.py tuning-sample investigation (pair 1078). **Resolved, see spec decision 73**, same session.

Soundex encodes letters only; a digit-leading street name's identity-bearing content (the digit run) is invisible to it, so "2nd" and "22nd" — different streets — code identically. Two leak patterns followed: a low-but-non-zero, non-gating score for differing-digit pairs via the edit-similarity key, and, more severely, full phonetic credit for differing-digit pairs that happen to share a letter suffix via the Soundex-match key. Decision 73 splits digit-leading tokens into an exact-match digit gate plus a fuzzy-tolerant letter suffix, closing both patterns while preserving typo tolerance for the suffix ("1st" mistyped as "1ts" still qualifies). Recorded in full despite same-session resolution because the two failure patterns and the sample-blind-spot mechanism (`_pick_far_street_donor`'s different-Soundex requirement structurally excludes the Soundex-match-branch leak) are worth carrying forward rather than compressing to a one-line pointer.

---

#### Q33 — §6.3/decision 57's merge confidence does not degrade

**Resolved, see spec decision 88.** Dissolved on inspection rather than fixed: confidence was always meant as a match-quality dial (decision 31), deliberately orthogonal to spatial extent, and the code already reflects that — RFC 7459's `pdf` is left "unknown" for the same reason. The Circle's measured radius already carries the honesty signal Q33 was looking for, more precisely than a scalar penalty could. The enhanced interface never had this gap: decision 27 means it never merges. No code change.

---

#### Formerly "still open because they block code" — all now closed, retained as pointers

- **(c) The enhanced candidate schema — CLOSED, see decision 92.**
  `references/i3-geocode-conversion-enhanced.yaml` is the additive diff, now
  reconciled field-for-field against `src/api/wire/response_json.py` and
  verified to match it exactly in both directions and on the envelope. The
  YAML is the normative spelling; the code is expected to match it rather than
  the reverse. Note for anyone reading an older copy of this document: item (c)
  described the YAML as unwritten for three sessions after a draft of it
  already existed, and `response_json.py`'s module docstring repeated that
  claim. Both were stale, not the Session 5 note that recorded the draft.
- **(d) `§6.5` similarity measures and `§10.6` spatial-fit components —
  MECHANISM settled (decisions 66, 69, 70, 71, 72), CONSTANTS still open.** The
  weighting mechanism (query-populated renormalization, deployment-measured
  discriminative factors, the community cascade), the Soundex/edit-distance
  similarity blend, and the street-name qualification gate are implemented in
  `src/engine/scoring.py` and `src/gis/field_stats.py`. Address Number is no
  longer part of this list — decision 69 made it a hard candidate-set gate
  on SSAP rather than a weighted field, so there is no `_BASE_WEIGHTS` entry
  for it to tune. What remains a guess: the base editorial weights in
  `_BASE_WEIGHTS` (Street Name confirmed as the intended top weight per
  decision 79's reasoning; St_Type and A2 evaluated and left at their
  current values — see decisions 78-79, both diagnosed as not fixable by
  reweighting alone but not gated either, for different reasons); the
  street-name
  qualification threshold `_STREET_QUALIFY_MIN_EDIT_SIM` (0.5, decision 71);
  the Community qualification threshold `_COMMUNITY_QUALIFY_MIN_EDIT_SIM`
  (0.5, decision 77) — repurposed by decision 80 as the trigger for a
  bounded penalty rather than a gate, still needing its own value
  justification — and `_COMMUNITY_MISMATCH_SIMILARITY_CAP` (0.15, decision
  80, settled by sweep — see decision 80's reasoning for why the sweep
  found no cap value materially changes the wrong_community score, and why
  0.15 was kept as the mechanism's value regardless). Whether a whole-score
  post-average penalty for a disqualifying Community (rather than a
  per-term clamp folded into the weighted average) is worth building is a
  question raised by decision 80's own sweep and CLOSED as declined by
  decision 86: no whole-score penalty is built, for Community or St_Type.
  A multiplier strong enough to separate the populations reconstructs
  decision 77's reverted gate; one weak enough to be safe reproduces
  decision 80's null result; and no middle setting exists, because a
  legitimately-confused caller's true match and a genuine false positive
  are identical in the fields. Ranking, §6.3's ambiguity refusal, and the
  per-field breakdown already handle every case a penalty would touch. Comparison MECHANISMS
  are now fully settled by decision 82's three-class taxonomy (gates /
  binary controlled-vocabulary terms / hand-typed blend) — A1, Country, and
  St_Dir compare binary exact-match and stay in `_BASE_WEIGHTS` as weighted
  terms; A2 stays in the blend; decision 81's briefly-specified A1/Country
  gates were reverted before implementation. What remains open here is
  nothing: decision 89 closes the base editorial weights as VALIDATED
  against the statewide deployment rather than retuned, on a pairwise
  ranking sweep in which every empirically testable field pair ordered
  correctly in 100% of samples across two independent runs. Item (d) is
  therefore CLOSED for `§6.5`. Three qualifications are recorded with it and
  should be read as part of the closure, not around it: only 3 of 21 field
  pairs are empirically testable, which is a permanent property of a
  single-state deployment rather than a sample-size limit; A1 and Country
  carry an effective weight of exactly 0.00 here, so their base weights are
  inert and tuning them statewide is a no-op; and A2 is untestable for the
  shared-suffix reason decision 91 declines to normalize away. Decision 90
  additionally corrects the discriminative-factor lookup for the two
  slot-spanning terms so the factor follows the value compared rather than
  a slot named in source. See Appendix C.4 Q30 (closed). `GCS_GEOCODED_PLACEMENT_PENALTY` is likewise no longer an
  open constant: decision 83 settles it at 0.9 as an editorial default and
  records why it is not sweepable at all — it sits outside §10.3's
  lexicographic ordering, so it moves a reported number and no answer, and
  STA-006.3 supplies no error magnitude to sweep against. The injection seam remains
  `src/engine/scoring_registry.py`; with
  nothing registered the four resources still return 454 rather than
  converting against an invented formula, though `src/app/lifecycle.py` now
  registers `scoring.score` and `scoring.make_reverse_scorer(...)` at
  startup.
- **(e) The stable identifier for §10.4's deterministic tie-break** — **ANSWERED,
  see R3 above.** `NGUID`, with null NGUID making a record ineligible for
  deterministic ordering and reported via the discrepancy path rather than
  substituted.
- **(7, Appendix C.2) Packaging of the shared element model.** i3-fe-core is
  the wrong home (its charter is cross-cutting i3 conformance, not "what some
  FEs share"), so a separate package or a vendored copy. The spec says decide
  when code exists to observe — `src/engine/models.py` is where that code will
  be.


# Appendix D — Document Change Log

### Version 9 — August 2026

**Change:** Added Appendix B decision 117 (§3.9.2, §12.2). Two corrections to `references/i3-geocode-conversion-enhanced.yaml`: its header comment's "irreconcilable content type" reasoning, written against the Session 3 reading decision 116 later superseded, is rewritten to stand on its own instead of a defect the strict interface turned out not to have; and `'454'`/`'468'` on both enhanced resources gain the `content` block (a new `ErrorReason` schema) they had never declared despite `src/api/status.py` emitting a `{reason: string}` body on both since decisions 36 and 114. §2.1's Session 3 settled-callout — the document's other standing instance of the same superseded "cannot be implemented as written" claim, missed when decision 116 corrected §3.9.1's copy of it — gains the matching correction note.

**Rationale:** Session 15, a documentation-alignment pass following on from decisions 114–116: those decisions changed the wire format but this repository's non-prose artifact (the enhanced YAML, decision 92's own normative spelling) and one further prose location were not swept for the same correction at the time. Neither finding required new implementation — `src/api/status.py` already emitted the now-declared error shape, and no behavior changed — which is why this lands as a documentation decision rather than a numbered code change of its own weight.

### Version 8z — August 2026

**Change:** Added Appendix B decisions 114–116 to the changelog retroactively; each decision's own Appendix B entry, §16 rows, and settled callouts were written in Session 14 alongside the code, but no changelog entry was recorded for the batch at the time — the same gap Version 8x's retroactive Session 10 entry already named as a recurring failure mode. 114 (§6.4, §8.4, §12.3) gives 468 a fixed, non-distinguishing body reason, closing the shape gap against 454. 115 (§8.1, §8.3, §12.1) indents both response layers and fixes a `usage-rules`-triggered pretty-print bug that had been silently flattening part of every response carrying one. 116 (§3.9.1, §8.1, §12.1, §16) corrects the strict interface's 200 response to real `application/xml`, superseding the Session 3 reading that had emitted `application/json` instead since the document's earliest sessions — the largest single wire-format correction since Session 3 itself. §16's "Normative YAML content types are incoherent" row is marked resolved by 116.

**Rationale:** Housekeeping, in the same register as Version 8x's own entry: the register carries the decisions and the sections carry the callouts; only this log was missed, this time for three decisions across one session rather than two decisions across one.

### Version 8y — August 2026

**Change:** Added Appendix B decision 113 (§A.4, §A.5). Wires `SipNotifier`'s `logging_client` hook (mechanical pass-through, matching every other GCS core component; `SubscribeLogEvent` now emitted for every SUBSCRIBE). Leaves `validate_target_uri` deliberately unimplemented — no reference implementation exists in LVF or MCS to port, and GCS's practice through this arc of work has been to port working reference behavior rather than originate ahead of it; recorded as parked, in the same register as decision 112's load-shedding deferral, not silently dropped. §A.4/§A.5's WIRED callout updated accordingly.

**Change:** Sessions 14 (with retroactive Session 12–13 entries for decisions 107–108 folded in above). Added Appendix B decisions 109–112. 109 and 110 wire the SIP transport (§A.4/§A.5) and the GCS log-event emit helpers (§A.3) respectively, both ported from lvf-service's maintained reference implementations rather than mcs-service's untested copies, with deliberate shape adaptations recorded in each decision's text (GCS-specific event fields, async-native emit mechanism, unconditional pre-admission query logging). 111 wires GIS discrepancy report filing (§A.6) against the trigger vocabulary decision 99 already settled. 112 declines load shedding (§3.9.5) as an active implementation priority without reopening decision 100's status-shape settlement. Appendix C.3 updated: of the five items decision 107 counted, four are now WIRED (transport security by 108, SIP/logging/discrepancy by 109–111) and the fifth (load shedding) is deprioritized rather than scheduled by 112 — nothing remains on C.3's active list. §A.3, §A.4, §A.5, and §A.6 each gain a WIRED callout pointing at the implementing decision.

**Change:** Session 11 — a clearing pass over Appendix C's open questions. Added Appendix B decisions 95–106, resolving every remaining C.4 open question (Q1, Q2, Q4, Q5, Q6, Q7, Q9, Q10, Q11, Q14, Q15, Q16, Q17, Q19) plus C.2 question 7 and item (b), and §1.4's gs:-confirmation drafting note. §3.9.4 and §3.9.5 are written (decisions 101, 100); §4.3 is rewritten as a pointer into §4.2 (decision 102); §3.2 gains the Placement-token and whitespace-normalisation settlements (decision 103, adopting R4); §3.9.1 gains the Versions-path and dual-body-form settlements (decision 95); §10.2 gains the vertical-component consequence (decision 96); §7.4 gains the RFC 7459 out-of-interval serialisation rule (decision 97); §A.1, §A.3, and §A.6 are updated (decisions 95, 104, 98, 99). §16 gains two rows: the unresolvable `/Versions` `$ref`, and the absence of a GCS LogEvent type — the latter confirmed by direct read of the full i3 §4.12.3.7 registry (44 types, none GCS). C.3 records that nothing remains undrafted. Every remaining drafting note is discharged — §3.1, §3.3, §3.6.1, §3.9.3, §4.1, §6.1, §6.4, §7.1, §7.2, and §7.5 are converted to settled or plain prose, each note's content having been resolved by earlier decisions (R2, 55, 70, 85, 105) or by the §16 rows that already carry it — so by §1.3's own definition ("zero drafting notes is the definition of a complete draft") the document is now a complete draft. Editorial repairs: §4.2's RFC 5491 Rule #8 sentence had lost its three element names to a rendering defect, leaving text that misstated the precedence as "tuples last" — restored to device → tuple → person, matching RFC 5491 and the implementation; the same class of defect is repaired in §3.6.1 and two §16 rows (`<presence>`/`<usage-rules>`, `<method>`).

**Rationale:** Session 11 was a simplification-and-reconciliation pass over the whole repository. Most resolutions are reconciliation rather than authoring — the implementation had already behaved as decided (Q1, Q5, Q11, Q14, Q17, R4, the Placement normalisation), and the spec had simply not been written up against it. The genuinely new settlements are Q7's filing scope (the data-quality flag vocabulary is the filing vocabulary; attribution is never second-guessed), Q9's transport-layer framing (the same reading that already licenses 413), Q10's registry read (evidence, not assumption), and the three declines recorded so they are not re-raised (Q15's schema growth, C.2 item (b)'s configurability, question 7's extraction).

### Version 8x — August 2026

**Change:** Retroactive entry for Session 10, which added Appendix B decisions 93 and 94 and wrote §3.4 (temporal filtering: request-time evaluation, inclusive Effective / exclusive Expire, absent-means-active, unparseable-means-absent), §3.5 (reload: stale data preferred over no data, consistent snapshots by reference rebinding, readiness distinct from health), and §3.8's reconciliation (`.env.example` as the canonical variable reference, prefix-level orientation only in the spec) — but recorded no changelog entry at the time.

**Rationale:** Housekeeping. The register carries the decisions and the sections carry the callouts; only this log was missed.

### Version 8w — August 2026

**Change:** Added Appendix B decision 92 (§3.9.2, §12.2), closing Appendix C item (c). `references/i3-geocode-conversion-enhanced.yaml` is reconciled field-for-field against `src/api/wire/response_json.py` and adopted as the normative spelling of the enhanced wire format: `pidfLo` and `distanceMeters` resolved toward the implementation, `matchScoreBreakdown` toward the draft, `rank` dropped, six emitted-but-undocumented fields added, conditional absence documented as meaningful, confidence bounds declared inclusive, `469` dropped and `454` declared on both resources, response content type `application/json`. §3.9.2 amended: Placement Method is carried on the reverse resource only. Item (c) marked closed with a note that it and `response_json.py`'s docstring were stale for three sessions.

**Rationale:** Session 9. The draft YAML existed from Session 5 but had drifted from an implementation that kept evolving; because both live trackers described it as unwritten, nothing audited it. Reconciliation was verified mechanically — the schema's field set now matches the emitter exactly in both directions and on the envelope.

### Version 8v — August 2026

**Change:** Added Appendix B decisions 89, 90, and 91 (all §6.5). 89 closes Appendix C item (d)'s `_BASE_WEIGHTS` as validated statewide rather than retuned, recording the six-county extract artifact, the 3-of-21 testability limit, and the falsified geography-versus-convention hypothesis. 90 extends decision 76's per-record factor lookup to the two slot-spanning terms (St_Dir, St_Type), so the discriminative factor is read from the slot that produced the compared value. 91 declines shared-suffix normalization for A2. §6.5 gains a settled callout; its stale "still a guess" characterisation of the base weights is corrected; Appendix C item (d) is marked closed for §6.5.

**Rationale:** Session 9. The base weights were the last untuned constants in item (d); a purpose-built pairwise ranking sweep against the full statewide export settled them on evidence, and surfaced both the factor-lookup defect fixed by 90 and the A2 suffix behavior declined by 91. Decision 90 was implemented in the same session and its record amended with two implementation findings: that St_Type and St_Dir are RCL's unsided shared columns, making slot selection structurally independent of side selection, and that the effective-weight movement confirmed against statewide data (4.997 → 5.972) matches the estimate. Suite 454 → 466 passing with no expected-ordering assertion changed. Decision 90's record further amended after `tools/field_factor_diagnostic.py` was corrected to resolve the factor per record: the corpus-mean effective weights (St_Dir 5.881, St_Type 7.008) are distinguished from the per-record values (5.972, 7.111), St_Type is recorded as having moved rather than being unaffected, and the tie rule is noted as near-unreachable statewide.

### Version 8u — August 2026

**Change:** Added Appendix B decision 88 (§6.3, §7.4; resolves Q33): confidence intentionally does not degrade on merge. §6.3 gains a settled callout. Q33 struck to a resolved pointer in Appendix C.4.

**Rationale:** Session 9 open item, dissolved on inspection — the mechanism was already correct; the concern was answered by decision 31's confidence design and decision 57's Circle, not by new code.

### Version 8t — August 2026

**Change:** Added Appendix B decision 87 (§7.2, §11.3; adopts 67, resolves Q31). §7.2 gains two settled callouts — one stating that the forward direction has exactly one parity-based side-selection rule consulted at both scoring and position derivation, one recording the deliberate divergence between the two ends' fallbacks when parity fails to resolve. §11.3 gains a callout explaining why the reverse direction projects rather than reading parity. Q31 rewritten as a resolved pointer.

**Rationale:** Q31 anticipated a conflict between scoring's parity-derived side hint and "§7.2's own geometric side selection." No such conflict exists: §7.2 and §7.3 already select side from Add_Number parity, so decision 67 independently reached the rule already in force rather than introducing a rival to it. The reverse direction projects because a reverse request carries no house number to derive parity from — a difference in available input, not policy. The fallbacks do diverge, and are left so deliberately: aligning them would add a range-containment branch to the scorer serving only records whose parity is null or self-contradictory, a data-quality defect §7.2 already declines to repair, and dead in every well-formed case.

### Version 8s — August 2026

**Change:** Added Appendix B decision 86 (§6.5), closing Appendix C item (d)'s whole-score post-average multiplicative penalty sub-question as declined for both Community and St_Type. matchScore remains a weighted average of per-field similarity; decision 82's three comparison classes remain exhaustive and no fourth mechanism class is added. Item (d) updated accordingly.

**Rationale:** The penalty has no viable setting. Strong enough to separate wrong-community scores from true matches is strong enough to push them under `GCS_MIN_MATCH_SCORE`, reconstructing decision 77's reverted gate; weak enough to avoid that reproduces decision 80's null sweep. The gap does not exist because the two populations are identical in the fields — a caller confidently wrong about the town and a genuine false positive produce the same field-score shape by construction, so no scalar computed from those fields separates them at any point of application. What does separate them is already used: ranking puts a right-community competitor first where one exists, §6.3 returns 468 where the same address appears in two wrong communities beyond the ambiguity tolerance, and the record is correctly returned where it is the only one. The reported-honesty concern is already served losslessly by the per-field breakdown on the enhanced interface. St_Type closes on identical reasoning, retiring decision 79's residue.

### Version 8r — August 2026

**Change:** Editorial correction to §6.5's decision-74 callout. It enumerated three sites where the transposition-aware edit-distance primitive applies, the third being "the pure-edit-distance categorical fields (Country, A1)". Decision 82 removed those fields from edit distance entirely, and the neighbouring decision-72 callout was updated accordingly, but 74's was not — leaving a present-tense normative statement describing behavior the implementation does not have. The third site is now marked as removed by decision 82, with the decision's live scope restated as the blend and the digit-leading suffix. No decision changes; the primitive itself is untouched.

**Rationale:** Surfaced by a Claude Code pass verifying that no code comment still enumerated the obsolete third site — the code was already correct, and the check found the spec was not. Recorded as a changelog entry rather than a new decision number because nothing was decided: decision 82 already made this change and 74's callout simply failed to follow it.

### Version 8q — August 2026

**Change:** Added Appendix B decision 85 (§7.4, §3.7; resolves Q22): a rung-3 STREET_SEGMENT answer is 2D at EPSG:4326, with the RoadCenterLine geometry's per-vertex Z dropped. `Candidate.crs`'s abstention for line answers ends, and the rung-3 `gml:LineString` carries an explicit `srsName` rather than omitting it. Q22 is rewritten as a resolved pointer.

**Rationale:** The question was posed as R1 (drop Z at rung 2, because the perpendicular offset displaces road-surface Z onto a parcel) versus §7.4's return-the-actual-geometry principle (carry the line undisplaced, escaping R1's specific objection). Neither had to be chosen: §10.5 already establishes that RoadCenterLine is not a declared 3D-capable feature class, so the layer's `MultiLineString Z` type is an export-format artifact rather than an assertion that road-surface elevation is authoritative attribution. A Z the data model does not declare is not promoted to an answer. This generalizes R1 to all RCL-derived answers on firmer ground than its original displacement argument, and dissolves the per-vertex-versus-whole-line admission question entirely, since no test runs on a value never consulted.

### Version 8p — August 2026

**Change:** §15 Complete Algorithm Pseudologic is written — §15.1 Geocode (including a SCORE_RECORD sub-listing for §6.5) and §15.2 ReverseGeocode, both as annotated pseudocode with per-step citations. Added Appendix B decision 84 recording the section as subordinate to the numbered sections. §2.4's drafting note on revisiting stage numbering is resolved and removed; Appendix C.3 no longer lists §15 as undrafted.

**Rationale:** §15 was deferred across seven sessions because a summary of unsettled decisions documents intentions rather than decisions — it would have needed revision after each of decisions 69, 71-76, 80, 82, and 83. Decisions 82 and 83 closed the last open comparison mechanism and the last behavior-affecting scoring constant respectively, so §6.5 and §10.6 are now settled in mechanism and the section is finally writable. The listings are annotated rather than bare, carrying the load-bearing negatives an implementer would otherwise get wrong by reasonable inference: no progressive filter; only two fields gate candidacy; search order is not acceptance order; parity never blocks a forward match; extent damping and the placement penalty sit outside the lexicographic ordering; reverse tier precedence applies only to contained candidates; the reverse inversion must walk the forward direction's margin-shortened path; empty elements are omitted, not emitted.

### Version 8o — August 2026

**Change:** Added Appendix B decision 83 (§10.6): `GCS_GEOCODED_PLACEMENT_PENALTY` is retained at 0.9 and reclassified from untuned strawman to settled editorial default, removed from Appendix C item (d)'s open-constants list. §10.6 gains a settled callout stating what 0.9 means and why no sweep is possible; decision 66's callout is amended to point at it.

**Rationale:** The constant sits outside §10.3's lexicographic ordering (containment, tier, distance), so it moves the reported spatial-fit number and confidence and nothing else — never the candidate order, never admission, never a 200-versus-468. It is therefore not sweepable in the way decisions 79 and 80 swept their constants: those scored a value against a labeled outcome it could move, and this one has no such outcome. STA-006.3's registry records that a placement was derived by geocoding, never the error magnitude of that derivation, which belongs to the SI's geocoder rather than to anything the GCS observes. 0.9 is kept as an editorial value that makes the round-trip approximation visible without asserting a magnitude, with the environment binding — already implemented — as the mechanism for deployments that know their own data better.

### Version 8n — August 2026

**Change:** Added Appendix B decision 82 (§6.2, §6.5; supersedes 81, closes Q30 and the St_Dir open item): comparison mechanisms settled as a three-class taxonomy — identity gates (Add_Number, UnitValue, unchanged), controlled-vocabulary binary terms (St_Dir, A1, Country: exact match after normalization = 1.0, else 0.0, weighted not gated), and the hand-typed name blend (St_Name, St_Type, Community, A2, unchanged). Decision 81's A1/Country candidate-set gates are reverted before implementation; both fields return to `_BASE_WEIGHTS`. St_Dir stays one weighted term spanning both directional slots with the existing best-of-both-sides comparison (position swap = full credit; genuine mismatch = 0 on the term). §6.2's and §6.5's decision-81 callouts are replaced; Q30 and Appendix C item (d) updated.

**Rationale:** Measured against the live similarity code, the Soundex/edit-distance blend gives "NE" vs. "NW" a 0.889 similarity (NORTHEAST/NORTHWEST are edit-similar and Soundex-identical) — near-full credit for opposite quadrants — and "SD" vs. "ND" 0.50, the inflation Q30 originally flagged. Binary exact-match after normalization scores both at 0, matching PostGIS TIGER geocoder practice (parsed directionals rated as discrete categorical attributes; fuzzy matching reserved for names). Decision 81's gates failed decision 80's own test: against a single-state export, a hard A1 gate empties the candidate set for a border-area caller who names the wrong state (Fargo/Moorhead; Pembina on the Canadian line) — converting a recoverable query into a 468 — where a binary weighted term prices the mismatch honestly while keeping the true match rankable. A compass-distance similarity for directionals was considered and rejected: no production geocoder does it, and decision 80's dilution analysis shows a weight-8 term of an ~82-weight average cannot express that precision anyway. With this, every §6.5 comparison mechanism is settled; only tuning constants remain open.

### Version 8m — August 2026

**Change:** Added Appendix B decision 81 (§6.2, §6.5; resolves Q30 for A1/Country): A1 and Country each become independent, per-field, exact-match, pre-scoring candidate-set gates — the Add_Number-shape gate (decision 69), extended to apply on RCL as well as SSAP. Both fields are removed from `_BASE_WEIGHTS` and the weighted-average matchScore, with a gated-and-passed candidate still reporting `100.0` in the i3-improved breakdown per decision 69's transparency precedent. §6.2 and §6.5 each gain a settled callout. Q30 (Appendix C.4) is marked resolved for A1/Country; Appendix C item (d)'s constant list is updated to drop A1/Country and confirm A2's classification.

**Rationale:** A1 and Country are controlled-vocabulary codes (state/country abbreviations) a caller doesn't spell out the way a street or community name is typed and misspelled — decision 72 already excluded them from the Soundex half of the free-text blend, but edit distance alone still credits partial character overlap between codes that should be treated as simply right or wrong (`A1="SD"` vs. `A1="ND"` scoring 50% on shared characters despite naming different states). A wrong state or country is an identity mismatch, not a near-miss, the same category of error Add_Number (decision 69) and UnitValue (decision 75) already gate on. A2 (County) is explicitly excluded from this gate and confirmed under decision 72's hand-typed blend instead — County is spelled out by a call-taker, not selected from a short fixed list, so the identity-field reasoning does not apply to it. In the currently loaded ND export, A1 is uniform "ND" (decision 68) and Country is presumptively uniform "US," so neither gate is expected to disqualify any candidate in the deployment as provisioned today — this decision is groundwork for portability to a multi-state or cross-border deployment.

### Version 8l — August 2026

**Change:** Added Appendix B decision 80 (§6.5, supersedes 77): Community's hard qualification gate is reverted; Community returns to decision 76's weighted-average treatment, with a new `_COMMUNITY_MISMATCH_SIMILARITY_CAP` (0.15) clamping — not zeroing — a non-qualifying Community's contribution. §6.5 gains a settled callout replacing decision 77's. Appendix C item (d)'s constant list is updated: `_COMMUNITY_QUALIFY_MIN_EDIT_SIM` is repurposed as the cap's trigger rather than a gate threshold, and a new open sub-question (whole-score post-average multiplicative penalty) is logged.

**Rationale:** Jason's own example — "Lincoln" typed for an address actually in Bismarck — established that a wrong community does not reliably signal a wrong address, the assumption decision 77 was built on. A dedicated sweep (`tools/community_cap_sweep.py`, 250 pairs, caps 0.0–0.5) found the cap cannot meaningfully move the wrong_community score at any value tested (mean 91.63–92.18, 100% still clearing `GCS_MIN_MATCH_SCORE` throughout) — Community is one of seven averaged terms, diluted by the other six regardless of its own value. The cap is kept anyway as a genuine improvement in kind (the caller is no longer categorically excluded), even though it does not improve the score in degree. The mechanism that would actually separate these cases — a whole-score post-average multiplicative penalty — is logged as open, not built.

### Version 8k — August 2026

**Change:** Added Appendix B decision 79 (§6.5, measured, deprioritized): St_Type is left as an ordinary weighted field at its current base weight, no qualification gate built.

**Rationale:** Session 6 diagnosed St_Type as ordinary under-weighting with real headroom to fix by reweighting. A real sweep (250 wrong_st_type pairs, weights 12.0→36.0) disproved that — the mean score only fell 83.5→63.4, with 87% of pairs still clearing the admission threshold even at 3x the base weight, the same reweighting-is-futile shape later confirmed for Community (decision 80) and A2 (decision 78). Unlike Community, a gate is also the wrong tool here: callers are judged more likely to mistype the street type than the street name itself, so gating would disqualify legitimate near-misses rather than catch genuine wrong-address candidates.

### Version 8j — August 2026

**Change:** Added Appendix B decision 78 (§6.5, diagnosed, deprioritized): A2 (County) is not built as a qualification gate.

**Rationale:** A2 was found to share Community's pre-80 structural shape — a measured discriminative factor around 0.32, the sort of number a gate would meaningfully act on — but two things make the gate not worth building: A2 is rarely a caller's primary identifying element for an address, and decision 66 already limits its exposure to queries that supply it at all (`populated()` renormalization excludes it entirely otherwise). No sweep-justified benefit was found to outweigh the added code path.

### Version 8i — August 2026

**Change:** Added Appendix B decision 77 (follows from 76): Community becomes a qualification gate mirroring decision 71's street-name gate, with its own independent constant `_COMMUNITY_QUALIFY_MIN_EDIT_SIM` (strawman 0.5, deliberately not shared with `_STREET_QUALIFY_MIN_EDIT_SIM`). §6.5 gains a settled callout; Appendix C item (d)'s constant list gains the new threshold.

**Rationale:** Both weight-based levers (raising `_BASE_WEIGHTS["Community"]` up to 3.3x, and decision 76's discriminative-factor field-lookup correction) were tried in sequence against the real 1,250-pair sample and both measured insufficient — wrong_community held at 100% clearing GCS_MIN_MATCH_SCORE either way. Same evidentiary shape that already justified decision 71's street-name gate over further reweighting.

### Version 8h — August 2026

**Change:** Added Appendix B decision 76 (amends 66): MSAGComm dropped from the Community cascade (now A3 → A4 → Post_Comm); Community's discriminative-factor weight now follows whichever cascade field actually resolved each record's comparison value, rather than a single field hardcoded regardless of which tier produced it (previously `f("A3")` fixed in score_ssap, `f("Post_Comm")` fixed in score_rcl). §6.5 gains a settled callout and the cascade description is updated.

**Rationale:** Investigating the wrong_community false-positive signal — unmoved by decisions 73-75 and unresponsive to raising `_BASE_WEIGHTS["Community"]` alone up to 3.3x its current value — found the discriminative-factor discount itself was mismeasuring a large share of records: 21.8% of SSAP records and roughly 52.8% of RCL records per side resolve their Community value from a cascade tier other than the one whose statistics were being used to discount the weight. MSAGComm's removal is separately evidenced: reached by exactly 1 SSAP record and at most 1 RCL record per side out of the full provisioned dataset.

### Version 8g — August 2026

**Change:** Added Appendix B decision 75 (§6, §6.5): UnitValue becomes a conditional identity gate on SSAP candidates, mirroring decision 69's Add_Number gate but exempting candidates with no unit at all (decision 61's sparseness posture) — resolves the discovery that Unit was never read anywhere in scoring despite §3.10 stating it "remains available to §6.5 scoring." §6.5 gains a settled callout. Appendix C.4 gains Q33: whether decision 57's merge `confidence` should degrade to signal an averaged multi-candidate response, surfaced while tracing decision 75 but not resolved by it — left open.

**Rationale:** Targeted probing after decisions 71-74 found UnitValue/UnitPreTyp round-trip through the model, GIS loader, and wire but are never read by score_ssap/score_rcl — a real spec/code disagreement. Tracing the actual response-path consequence (rather than assuming severity) found it bimodal: spatially dispersed multi-unit buildings already fail honestly (468, beyond `GCS_AMBIGUITY_TOLERANCE_M`), but tightly-clustered buildings produce a confident merged response indistinguishable in `confidence` from a clean single match, silently averaged across every unit regardless of which one was requested. The gate closes the dangerous case without touching decision 57's merge machinery, which is functioning as designed for genuine spatial ambiguity.

### Version 8f — August 2026

**Change:** Added Appendix B decision 74 (amends 72, 73): the edit-distance primitive underlying `_normalized_similarity` and decision 73's digit-leading suffix comparison is now transposition-aware (adjacent-swap Damerau-Levenshtein / "optimal string alignment"), applied everywhere edit distance is used rather than only the path that surfaced it. §6.5 gains a settled callout.

**Rationale:** Implementing and testing decision 73 found its own motivating case — "1st" mistyped as "1ts" — still disqualified under plain Levenshtein, which charges an adjacent transposition as two edits rather than one. The same primitive underlies every edit-distance comparison in the file, so the fix is scoped to the primitive, not the one field that exposed it.

### Version 8e — August 2026

**Change:** Added Appendix B decision 73 (resolves Q32, amends 71 and 72): street-name comparison splits a digit-leading token into an exact-match digit gate and a Soundex-free, edit-distance-only letter suffix, closing a Soundex digit-blindness gap that let differing-digit street names ("2nd" vs. "22nd") qualify as candidates — in the worst case with full phonetic credit. §6.5 gains a settled callout; Appendix C.4 gains Q32, resolved same session.

**Rationale:** Surfaced investigating an outlier in the weight-tuning sample set (tools/sample_pairs.py, pair 1078): Soundex's letters-only encoding is a property of the algorithm itself, not this implementation, so no reimplementation or library swap would have closed the gap — only a decomposition of the token could. Blocks the §6.5/§10.6 weight-tuning pass (Appendix C item (d)), which was paused pending this fix.

### Version 8d — August 2026

**Change:** Resolved the two questions raised during the `src/api/wire/` build. Decision 64 (resolves Q28, amends 63): STA-004.2 §3.3.3.8's "enter 0" rule governs record authoring rather than query interpretation, so an address number with no integer portion is dropped and no zero is substituted; the carve-out is now written into decision 63 rather than inferred. Decision 65 (resolves Q29): RFC 7459 confidence is emitted on all four resources; §8.1 and §12.1's "and nothing else" claims are narrowed to the response objects rather than the PIDF-LO payload, §8.1's indistinguishability consequence amended to state that a coarse confidence survives, and §16 gains a row recording that i3 never says whether a GCS should populate the element.

**Rationale:** Both were implemented on a stated reading during the wire build and both readings held. Q28's is a genuine reading conflict inside STA-004.2 itself, reconciled by observing that a record author must store a value where a query need not carry one — substituting zero would turn an unusable number into a specific wrong building. Q29's conflict was between §7.4's commitment and prose written before it; prose yielded, and the narrowing is recorded honestly because it slightly weakens §2.2's controlled comparison rather than leaving a claim the implementation contradicts.

### Version 8c — August 2026

**Change:** New §3.10 (Civic Element Model and PIDF-LO Mapping) carrying the full `ca:` ↔ STA-006.3 column mapping, transcribed from NENA-STA-004.2-2024 with that standard named as controlling. Decision 62 settles the element model's vocabulary and confines wire translation to the wire layer in both directions. Decision 63 settles address number typing and decomposition: `Add_Number` is a non-negative integer per STA-004.2 (narrowing RFC 5139), complete numbers decompose into prefix/integer/suffix with the original preserved in `AddNum_Cmp`, and a number that cannot reduce to an integer is dropped rather than rejected, reported on the enhanced interface. Q21 collapsed to a resolved pointer; Appendix C.2 question 7 narrowed to packaging alone.

**Rationale:** Q21 held that the mapping was written nowhere, which was true of this document but not of the standards set — STA-004.2 supplies it, and §1.1 already pointed there. Transcribing it resolves the question without authoring a competing definition. The address number rule follows the same source: decomposition and the integer typing are STA-004.2's, and the only genuinely local choice is what happens when decomposition fails, which follows decision 61's posture that an unusable element should cost precision rather than candidacy.

### Version 8b — August 2026

**Change:** Decision 61 removes §6.2's progressive filter. Every temporally-valid record in the searched layer is now scored on every request; no civic element excludes a record from scoring. §6.2 retitled Candidate Set and rewritten as settled, the term "progressive filter" retired. §3.4's temporal exclusion and `GCS_MIN_MATCH_SCORE` explicitly retained — the first is a correctness test, the second applies after scoring. Q24 collapsed to a resolved pointer in Appendix C.4, dissolved rather than answered.

**Rationale:** The filter traded accuracy for throughput, and the service's priority is accuracy. Every filtered element was one where a caller typo or a record data defect produced a 468 instead of a low score, with no second pass to recover it. Each candidate element list failed on that point, and the fuzzy place-name tier proposed to soften it needed a similarity constant no available data justifies — the same objection §10.5 raised against `k`. Scoring the full layer removes the failure mode rather than managing it. This also retires the last of §6.2's dependency on a document outside this specification, which decision 58 had already made untenable.

### Version 8a — August 2026

**Change:** Resolved the two questions raised during the src/reverse/ build. Decision 59 (resolves Q27): RoadCenterLine candidates tier uniformly as INTERPOLATED_POINT for §10.3 ordering purposes, with the tier reported on the answer determined by §11.2 and permitted to differ; §10.3 gains a paragraph stating the consequence. Decision 60 (resolves Q26): §10.5's vertical band is scoped to classes carrying a vertical extent, and §10.5 now states that none is currently provisioned, so the band is inert and retained as forward-looking structure; no vertical tolerance admitted. Q26 and Q27 collapsed to resolved pointers in Appendix C.4.

**Rationale:** Both surfaced while implementing §9–§12 and both were the specification's calls rather than the implementation's. Q27 is a real if narrow ordering defect arising from a circular dependency between §10.3's tier term and §11.2's tier determination; resolving it by ordering uniformly preserves §10.1's single pass and states the cost plainly instead of concealing it behind a second stage. Q26 is a documentation defect rather than a behavioural one — the rule reads as though it does work it cannot do on any provisioned class — and is fixed by saying so.

### Version 8 — August 2026

**Change:** Standalone-service restructure (decision 58, superseding 3 and 25). All references to the LVF Algorithm Specification / LVF v79 / LVF codebase pruned from the living document: §1.5 removed; §3.4, §3.5, §3.8, §3.9.4, §3.9.5, §4.1, §6.2, and §15 drafting notes rewritten to state their requirements directly; §3.2, §6.5, §8.2, §11.1, and §13 prose rewritten standalone (§13 generalised to LoST-based elements); §14 retitled Cross-Element and Round-Trip Consistency; Appendix C.1's LVF unread-source row removed; C.2 question 7 and C.3 rephrased; C.4's Q6/Q7/Q9 codebase-precedent mentions rephrased; Q21 and Q24 reframed from blocked-on-reading-LVF to questions this specification answers on its own terms — Q24 in particular is now decidable rather than blocked. References to the LVF as an i3 functional element retained where the standards-landscape arguments require them (§16, §11.2, §11.4, §14, §A.3). Table of Contents generated. Decision register and change log history retained intact per the register's own supersession discipline.

**Rationale:** The GCS is a standalone service; the only relationship to the LVF is repository structure and the shared i3-fe-core library, which the repository expresses and the specification need not. Deferring parts of this specification to a sibling document made it incomplete on its own terms and manufactured false dependencies. Top-level section numbering is deliberately preserved: it is load-bearing across the codebase, tests, and all 57 prior register entries, and the existing lifecycle ordering already is the logical flow — the restructure removes the foreign scaffolding from that flow rather than renumbering it.

### Version 7c — August 2026

**Change:** Resolved two of the three questions raised during the src/geocode/ build. Decision 56 (resolves Q23): a centerline segment too short to carry the endpoint margin returns the segment midpoint, extending decision 48's rationale rather than introducing a new rule or constant. Decision 57 (resolves Q25): §7.4's prohibition on synthesised uncertainty shapes is scoped to single matches; the §6.3 merged case returns a Circle (centroid + radius to the farthest merged candidate), with the geocode core emitting centre and radius-in-metres and the wire layer rendering the GeoShape. Q23 and Q25 collapsed to resolved pointers in Appendix C.4. Q24 (the §6.2/§6.5 filter boundary) remains open — it is blocked on reading LVF v79 §6.2, which Appendix C.1 still lists unread.

**Rationale:** Both were flagged as implemented-on-a-reading during the geocode build and needed either promotion to a decision or correction. Both readings held up; Q23 needed no code change and Q25's radius was already carried, so these are spec-side confirmations that put the reasoning on record. Q24 is left open deliberately, since it depends on a document not yet in the repository rather than on a judgement that can be made now.

### Version 7b — July 2026

**Change:** Merged the former standalone `docs/spec-questions.md` into Appendix C as a new subsection C.4 (Implementation-Discovered Questions). Resolved and struck items (R1–R4, and struck Q3/Q12/Q13/Q18/Q20) are carried as one-line pointers to the decision or section that holds the answer; genuinely open items (Q1–Q21 minus the struck ones, plus the code-blocking carry-overs) are carried in full. C.4's Q-numbering is noted as independent of C.2's. The specification is now the single tracked record; `docs/spec-questions.md` is retired.

**Rationale:** Two overlapping trackers with colliding numbering (C.2's "Q2" and the implementation file's "Q2" were different questions) was avoidable friction. Folding the implementation-side questions into the spec's existing open-tasks appendix keeps one source of truth without losing the code citations that reference the Q-numbers.

### Version 7a — July 2026

**Change:** Added Appendix B decision 55, superseding 51 and 52. Position on every axis is now sourced solely from the matched feature's shape geometry — X/Y from the geometry rather than the Longitude/Latitude columns, Z from the geometry's own ordinate where non-zero and nowhere else. The Altitude and Elevation attribute columns are no longer treated as position inputs (may be revisited later). A record with absent or unusable geometry yields no located match and is flagged as a data-quality defect. Decision 51's fall-through chain and 8.5%-Elevation reasoning, and decision 52's geometry-over-columns framing and Null Island concern, are consequently retired. Closes docs/spec-questions.md Q20.

**Rationale:** Surfaced against real records while resolving Q20: the geometry, not the attribute columns, is the standard's own primary position source (STA-006.3 §4.2.1), which both simplifies the rule and removes the axis asymmetry decisions 51 and 52 had left between vertical and horizontal handling.

### Version 7 — July 2026

**Change:** Pre-implementation session (implementation repo). Added Appendix B decisions 51–54: Z-precedence chain (§7.1) admits a source only if non-null and non-zero, so a uniformly-placeholder geometry Z falls through to Altitude then Elevation rather than reporting every address at 0 m HAE; horizontal precedence (geometry over attribute Longitude/Latitude columns); RCL MultiLineString handled as single-part-normal, multi-part flagged via discrepancy reporting rather than guessed at; GCS_AMBIGUITY_TOLERANCE_M confirmed as required-with-no-default, value set per deployment in .env. All four resolved against real provisioned data during src/engine/ implementation planning, not from the text alone.

**Rationale:** Implementation session — src/engine/, src/geocode/, src/reverse/ are plumbing-complete stubs per the docstring plans in src/engine/__init__.py etc.; these four decisions were blocking issues discovered loading real GIS data (data/data.gpkg) that had to be settled before models.py could be written correctly.

### Version 6 — July 2026

**Change:** Session 5 — pre-implementation edge-case closure. Settled §7.2’s three open mechanics (zero-length ranges return the segment midpoint on the matched side at INTERPOLATED_POINT; single-address ranges collapse into that rule; parity governs side selection and reverse synthesis but never blocks a forward match within the asserted range) and §4.2’s multiple-location rule (i3’s first-location MUST followed literally, with RFC 5491 Rule #8 supplying the precedence i3 omits, 468 where the elected location lacks the required chunk, and the discard reported on the enhanced interface only). Decision Register entries 48–50; three §16 rows added. Both algorithm chapters are now free of unresolved mechanics; remaining drafting notes are implementation ports and formula tuning.

**Rationale:** Session 5 close — implementation-ready.

### Version 5 — July 2026

**Change:** Session 4 close — the ReverseGeocode side. Settled §9 (all eight RFC 5491 shapes accepted; single centroid-derived search origin), §10.1 (one search pass, revising decision 18), §10.2 (GCS_REVERSE_SEARCH_RADIUS_M in metres, with the reasoning against decimal degrees), §10.3 (lexicographic ordering: containment → tier → distance, tier precedence scoped to contained candidates), §10.4 (deterministic tie-breaking on stable identifier), §10.5 (geodesic distance to geometry as-is with the centerline bias documented; lexicographic vertical band), new §10.6 (spatial-fit scoring; extent damps score not containment), §11.1 (completeLocation reuse), §11.2 (synthesised HNO with clamping, parity, and path symmetry), new §11.3 (administrative elements from record fields; side-specific RCL attribution), §11.4 (sparse records returned, empty elements omitted), §12.1–§12.3, and §14.1. Read the i3 §10.31 Match Type and STA-006.3 §6.1 Placement Method registries: match type mapping adopted in §12.2, Placement Method consequences in §10.5 and §10.6, and §7.4’s “unreachable ceiling” claim corrected — FOOTPRINT_2D is reachable where an SI provisions the Recommended address polygon class. Scoped §7.4’s input-uncertainty rule to Geocode. Added GCS_REVERSE_SEARCH_RADIUS_M. Decision Register entries 37–47; six §16 rows added; two registries removed from C.1.

**Rationale:** Session 4 close.

### Version 4 — July 2026

**Change:** Session 3 close. Resolved §7.4 confidence as the three-field quality model (matchScore / locationType / confidence with tier ceilings 100/90/80/75/50), grounded in industry research (Esri, Google, HERE, Pelias vs. PostGIS Tiger). Resolved §7.5 centroid (footprint X/Y, vertical midpoint Z). Resolved §8.3 PIDF envelope (entity echo / RFC 5985 unlinked pseudonym; retransmission-allowed pass-through). Read the normative OpenAPI YAML: GeodeticData naming corrected, one-web-service resolved (A.1), referral carriage moved to 307 Location header (§3.6.2), §3.9.1 settled; three YAML defects logged in §16. Defined the enhanced interface as /GeocodeEnhanced and /ReverseGeocodeEnhanced discovered via Versions vendor parameter (§3.9.2). Resolved §4.1/§8.4 (454 on both operations). Added GCS_MIN_MATCH_SCORE. Decision Register entries 31–36; C.2 questions 3, 6, 8 resolved; five §16 rows added; YAML removed from C.1.

**Rationale:** Session 3 close.

### Version 3 — July 2026

**Change:** Reframed purpose/audience (§1, §1.2, §1.2.1): internal working algorithm + NENA-facing gap register/extensions, not an industry reference. Trimmed §1.1 (removed LVF Algorithm Specification, added RFC 7459, cut S/AL clause from STA-010.3f-2021 role) and §1.5 (LVF as source-code/reuse reference only, gate-by-gate table removed). Toned down §2.2 “working demonstration” framing. Softened §3.4/3.5/3.8/3.9.5 LVF-port language to case-by-case review. Resolved §6.3 (multi-candidate reframing), §6.5 (one scoring function, informed by PostGIS/Nominatim research), §7.1 (Z precedence chain), §7.2 (interpolation + endpoint margin variable), §7.3 (configurable offset), §7.4 (geometry-as-answer + confidence on both interfaces, sizing still open). Added Decision Register entries 24-30; resolved four Appendix C.2 open questions; added new open items.

**Rationale:** Session 2 close.

### Version 2 — July 2026

**Change:** Session 1 working decisions incorporated — see Appendix B, entries 1–23. Added §1.2.1 (strict reading), §2.2 (two interfaces), §2.3 (one engine), §3.7 (CRS and 3D), rewrote §1.5, §3.1, §3.3, §3.6, §5, §13, §14. Gap register expanded from 12 to 20 rows. Added Appendix B (Decision Register) and Appendix C (Open Tasks and Questions).

**Rationale:** Session 1 close.

### Version 1 — July 2026

**Change:** Initial template. Structure, governing standards, i3 §4.5 normative baseline, seed gap register. No algorithm content.

**Rationale:** Session 1 start.

