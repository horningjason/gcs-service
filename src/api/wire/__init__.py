"""PIDF-LO wire serialisation for the GCS.

This is the ONLY layer that speaks PIDF-LO element names. The engine carries
STA-006.3 column names throughout (§3.10, decision 62), so translation happens
exactly once, here, in both directions — which is what keeps §11.1's reverse
derivation a field-for-field copy rather than a second mapping table, and keeps
§6.5 comparing like-named fields.

    xml_ns.py         namespace constants (§1.4) and the hardened lxml parser
                      config: resolve_entities=False, load_dtd=False,
                      no_network=True. This service parses attacker-supplied
                      XML on an emergency services network, so the parser
                      configuration is a security control rather than a detail.

    civic_xml.py      ca: / cae: / cdx1: / cdx2: <-> CivicAddress, both
                      directions, implementing §3.10's mapping table.
                      NENA-STA-004.2-2024 states that mapping element by
                      element and governs on any disagreement with the table.
                      Address numbers decompose into AddNum_Pre /
                      Add_Number / AddNum_Suf per STA-004.2 §3.3.2-§3.3.4 with
                      the caller's original form preserved in AddNum_Cmp; a
                      number that cannot reduce to a non-negative integer is
                      dropped rather than rejected (decision 63).

    pidf_xml.py       the RFC 3863 / RFC 4119 envelope: the input entity echoed
                      where present, a HELD-style unlinked pseudonym generated
                      where absent, usage-rules passed through unchanged, and
                      <method> deliberately never emitted (§8.3, decisions 12
                      and 33).

    gml_xml.py        RFC 5491 §4's GML subset and §5's GeoShape. All eight
                      shapes parse on the READ side, feeding §9's one search
                      origin. The WRITE side emits a Point at rungs 1 and 2,
                      the segment's own LineString at rung 3 (§8, decision 30),
                      and a Circle for §6.3's merged case (decision 57 — the
                      core supplies centre and radius in metres, this layer
                      renders the shape). Coordinate order is lat lon. Carries
                      the RFC 7459 confidence element.

    response_json.py  GeodeticData / CivicAddress wrappers and the enhanced
                      candidate schema.

Note that the wrapper objects are JSON while their payload is an XML document
carried as a string value — the only implementable reading of the normative
YAML's declared schemas (§3.9.1, §16).

This package occupies the slot lvf-service/src/lost/wire/ does in that
repository's layout. That is where the resemblance ends: decision 58 specifies
the GCS standalone, so nothing here is a port of anything, and the element
model these modules translate to is the GCS's own, derived from STA-006.3 and
STA-004.2 directly.
"""
