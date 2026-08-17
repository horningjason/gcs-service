"""The one engine (spec §2.3, decision 8).

This package holds what BOTH directions share; the direction-specific chapters
live in src/geocode/ and src/reverse/. Together these three occupy the slot
lvf-service keeps in src/validation/ — the same place in the directory layout,
holding a different shape of work: two substantial algorithms over a shared
candidate and quality model rather than one linear pipeline.

Contents:

    models.py     CivicAddress, GisRecord (SsapGisRecord / RclGisRecord),
                  Candidate, and the §7.4 quality fields (MatchQuality, the
                  LocationType tiers with their spec-fixed ceilings). The
                  element model is the GCS's own, derived from STA-006.3 and
                  STA-004.2 directly — decision 58 specifies this service
                  standalone, so there is no shared package to extract it to
                  (Appendix C.2 question 7, closed by decision 106). Carries
                  the resolutions that happen the moment a GIS row becomes a
                  candidate: decision 55's geometry-only position on every
                  axis under the non-zero Z admission test, and decision 53's
                  multi-part centerline detection. Also the precision-ladder
                  tiering (§3.3 rungs mapped onto §7.4 locationType), keyed to
                  matched geometry class rather than rung number so future
                  tiers insert without renumbering.

    scoring.py    §6.5 forward per-field similarity and §10.6 reverse spatial
                  fit — the formulas Appendix C item (d) originally withheld,
                  since written and closed out (decisions 66-91; base weights
                  validated statewide by decision 89). ONE scoring function
                  per direction, not an exact-then-fuzzy pipeline: an exact
                  match occupies the top of the same continuous scale a fuzzy
                  match scores lower in (decision 28).

    scoring_registry.py
                  The injection seam. Route handlers read the scorer from
                  here; src/app/lifecycle.py registers scoring.py's functions
                  at startup, and tests inject trivial ones. With nothing
                  registered, conversion returns 454 rather than running an
                  invented formula — see that module's docstring. The
                  GCS_MIN_MATCH_SCORE admission gate is applied in
                  src/geocode/candidates.py, upstream of both response
                  assemblies, so rank 1 is identical across the two
                  interfaces (decision 9 governs disclosure, not admission).

    geometry.py   True geodesic distance on the WGS84 spheroid in metres —
                  never decimal degrees (§10.2, decision 40). Interpolation
                  walked along actual vertex geometry, endpoint margin,
                  perpendicular offset, projection onto a path, and the §7.5
                  centroid convention. Dimensionality follows the data: one
                  interpolation carrying whatever dimensions the vertices
                  have, degenerating to 2D when they carry none (§3.7.1,
                  decision 17).
"""
