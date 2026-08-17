"""HTTP protocol adapter for the GCS web service.

This package is the GCS analogue of lvf-service/src/lost/: request admission,
the per-resource handlers, and (under wire/) the PIDF-LO serialisation. It is
named api/ rather than lost/ because the GCS is not a LoST server (spec §2.2)
and because it carries the i3-improved resources alongside the strict i3 ones.

Resources (spec §3.9.1, §3.9.2 — confirmed against
references/i3-geocode-conversion.yaml):

    POST /Geocode                  strict i3  -> GeodeticData { pidfLoGeo }
    POST /ReverseGeocode           strict i3  -> CivicAddress { pidfLoAddress }
    POST /GeocodeEnhanced          i3-improved -> ranked candidate list
    POST /ReverseGeocodeEnhanced   i3-improved -> ranked candidate list

The strict paths are byte-for-byte conformant to the normative YAML and are
mounted unconditionally. The enhanced pair is mounted only when
GCS_ENABLE_ENHANCED is true, and is advertised through the /Versions vendor
parameter — i3's own sanctioned hook for a service declaring vendor-specific
capability (decision 35).
"""

from __future__ import annotations

from fastapi import APIRouter

# The i3 §4.5 status set is CLOSED to five codes (spec §1.2.1, §2.1, decision 2):
# 200, 307, 454, 468, 469. This service mints none of its own, and there is no
# longer any build-state placeholder here: the 501 this module used to hand out
# while the engine was unwritten is gone along with the condition it described.
# A 501 in a deployed GCS is a defect rather than a documented departure, so the
# helper that could emit one has been removed rather than left unused.
#
# src/api/status.py is now the single place a response is constructed, and
# tests/conformance/test_conversion_http.py asserts the four resources never
# emit anything outside STATUS_SET.


def build_router(enable_enhanced: bool) -> APIRouter:
    """Assemble the GCS web service router.

    One router, because the normative YAML defines ONE web service with one
    server base (/Gcs/v1) covering both operations (spec §3.9.1, decision 34,
    Appendix C.2 question 6).
    """
    from src.api import enhanced, geocode, reverse_geocode

    router = APIRouter()
    router.include_router(geocode.router)
    router.include_router(reverse_geocode.router)
    if enable_enhanced:
        router.include_router(enhanced.router)
    return router
