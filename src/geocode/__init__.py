"""Forward conversion — civic address to geodetic position (spec §4-§8).

Contents:

    candidates.py         §6 — layer search order (SSAP then RCL, per §4.5's
                          own ordering "site/structure address points or road
                          centerlines"), the candidate set, and §6.3
                          ambiguity handling. There is no filter: every
                          temporally-valid record is scored on every request
                          and no civic element excludes one from scoring
                          (decision 61), because what a filter excludes it
                          excludes permanently and this service prioritises
                          accuracy over throughput. Vertical agreement merges
                          unconditionally and the uncertainty spans the extent;
                          horizontal disagreement beyond
                          GCS_AMBIGUITY_TOLERANCE_M returns 468 (decision 54 —
                          the variable is required and carries no
                          specification-level default, so the value comes from
                          .env). The multi-candidate case that merge logic
                          exists for is a generic query resolving to distinct
                          structures on one parcel — the enhanced interface
                          returns both ranked, the strict interface averages
                          with extent-sized uncertainty (decision 27).

    position.py           §7 — SSAP position from the matched feature's shape
                          geometry alone: X and Y from the geometry, Z from the
                          geometry where it survives the non-zero test and from
                          nowhere else, 2D at EPSG:4326 otherwise (decision 55,
                          which supersedes the geometry/Altitude/Elevation
                          chain decisions 29 and 51 described; the Altitude and
                          Elevation columns are not read for position at all).
                          RCL interpolation proportional along actual vertex
                          geometry with GCS_RCL_ENDPOINT_MARGIN_M trimmed off
                          each end (decision 30); the zero-length-range case
                          returning the segment midpoint at INTERPOLATED_POINT
                          ceiling 75 with the margin NOT participating
                          (decision 48); parity governing side selection but
                          never blocking a forward match within the asserted
                          range (decision 49); and the GCS_RCL_OFFSET_M
                          perpendicular setback, which may never place the
                          position on the centerline itself.

    response_assembly.py  §8 — geometry-as-answer: rung 1 and rung 2 return a
                          Point, rung 3 returns the segment's actual LINE
                          geometry, because there is no basis to collapse a
                          street-level match to one position and the line is
                          itself the honest uncertainty signal (decision 30).
                          No synthesised Circle or Ellipse.

The geodesic primitives all of §7 rests on — true distance in metres on the
WGS84 spheroid, interpolation walked along real vertex geometry, perpendicular
offset — live in src/engine/geometry.py, their planned home, because §10.2 and
§10.5 read the same functions from the reverse direction.

There is no gate1.py. Spec §5 / decision 14: i3 §4.5 imposes no structural
precondition on Geocode, and requiring one would add a restriction the standard
does not have. A street-level query with no HNO is accepted and answered at
rung 3; the honesty burden moves to uncertainty, where RFC 5491 already
supplies the vocabulary.
"""
