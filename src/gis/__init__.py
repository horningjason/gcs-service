"""GIS provisioning for the GCS.

provisioning.py loads and hot-reloads the two STA-006.3 layers Table 4-1 marks
Required for the GCS.

    records.py        WRITTEN. STA-006.3 row -> record model, and the cache
                      (de)serialisation for it: which columns exist, what they
                      are called, and which of them the algorithm reads. The
                      query-side types it feeds live in src/engine/models.py.
                      §7.2's drafting note asked for the RCL field names to be
                      confirmed against the provisioned schema; they are, and
                      Validation_L/R turned out not to exist (the columns are
                      Valid_L / Valid_R — spec Appendix C.4 R2).

    field_stats.py    WRITTEN. Deployment-measured discriminative weight per
                      civic element: how much a field can possibly tell us,
                      measured from the provisioned data alone rather than
                      tuned against match/non-match pairs. src/engine/
                      scoring.py multiplies its base weights by these factors,
                      so a field that is constant across the whole export
                      stops carrying weight it cannot earn. _MIN_POPULATION is
                      a first-principles sample-size floor (decision 68), not
                      a tuned value. tools/field_stats_report.py prints the
                      same measurement standalone.

    spatial_index.py  NOT YET WRITTEN. Degree-space bounding-box pre-filter
                      ahead of exact geodesic distance computation. Spec §10.2
                      sanctions this explicitly as an implementation
                      optimisation — data stays in EPSG:4326 and coordinates
                      serialise as degrees, but a configured radius is never a
                      degree value.

Where the specification turns out to be silent or self-contradictory on
something this layer needs, the question goes into the spec's own Appendix C.4
(Implementation-Discovered Questions), Open subsection — not into a separate
tracker, and not resolved silently in code.
"""
