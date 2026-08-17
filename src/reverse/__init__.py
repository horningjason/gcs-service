"""Inverse conversion — geodetic position to civic address (spec §9-§12).

The whole of §10 is a recommended best practice with no standards guidance
behind it: i3 §4.5 refers to "the 'nearest' point algorithm employed" as though
it were a defined thing, and it is not defined in i3, in STA-006.3, or in any
referenced RFC.

Contents:

    origin.py             §9 — the eight RFC 5491 §5 GeoShape forms accepted on
                          input, reduced to ONE search origin by the §7.5
                          centroid convention (footprint centroid for X/Y,
                          vertical midpoint for Z) so that nothing downstream
                          has a shape-specific code path. The input's extent is
                          not discarded with the shape: it is the §10.3
                          containment test and the §10.6 damping term, so a
                          query expressing two kilometres of uncertainty does
                          not score as though it expressed two metres. This is
                          where §7.4's ignore-the-input's-uncertainty rule stops
                          applying — on this side the input geometry is the
                          query itself, not metadata about it.

    search.py             §10 — ONE proximity pass from the §9 origin out to
                          GCS_REVERSE_SEARCH_RADIUS_M. No separate containment
                          pass and no separate 3D pass; both are terms in the
                          ordering rather than gates in front of it, because a
                          two-pass structure lets the second pass re-admit what
                          the first rejected (decision 39, revising decision 18).
                          Ordering is LEXICOGRAPHIC, not arithmetic:
                          containment, then precision tier, then distance —
                          nothing blended into a single number, so distance is
                          a tiebreaker within a tier and never a competitor to
                          it (decision 41). Tier precedence applies only among
                          contained candidates; a Point input has no area and
                          contains nothing, so the commonest input in the
                          system orders by pure proximity. Distance is measured
                          to geometry as it exists, with the known centerline
                          bias documented rather than corrected (decision 42).
                          Ties resolve on the matched feature's stable
                          identifier, ascending — arbitrary, and deliberately
                          so, because an arbitrary rule applied identically by
                          every implementation is what makes two GCS instances
                          provisioned from the same SI agree (decision 41).
                          That identifier is NGUID (Appendix C.4 R3): present on
                          both layers, globally unique per STA-006.3, and stable
                          across replication from the master SI. A record whose
                          NGUID is null is ineligible for deterministic ordering
                          and the condition is reported via the discrepancy
                          path — never replaced with a local surrogate, the
                          GeoPackage FID least of all, since it is not stable
                          across reloads and substituting it would silently
                          defeat the cross-implementation guarantee §10.4 exists
                          to provide.

    civic_derivation.py   §11 — SSAP civic read directly off the matched
                          record's fields. No derivation, inference, or
                          synthesis at that rung: the record already holds a
                          civic address and the GCS reports it. RCL civic
                          synthesises the house number by inverting §7.2's
                          interpolation along the SAME margin-shortened path —
                          if the two directions traversed different paths,
                          §14.1's round-trip diagnostic would fail by
                          construction rather than by data quality. The result
                          is clamped to the segment's asserted range and forced
                          to the parity of the side the origin fell on
                          (decision 44). Administrative elements come from the
                          matched record's own fields, NOT point-in-polygon
                          against boundary layers, because reversing against a
                          different source than the forward match used would
                          break the round trip on every record whose attribution
                          disagrees with its containing polygon (decision 45).
                          Sparse records are returned rather than skipped, and
                          an element with no source is omitted rather than
                          emitted empty (decision 46).

    response_assembly.py  §12 — one civic address on the strict interface, the
                          ordered candidate list on the enhanced one.
"""
