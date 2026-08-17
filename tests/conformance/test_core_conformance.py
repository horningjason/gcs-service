"""i3-fe-core conformance for the GCS.

A green run means the cross-cutting NENA-STA-010.3f-2021 requirements
i3-fe-core enforces are correctly wired into this FE's own FastAPI app:
ElementState/ServiceState endpoints and body structure, the §10.12/§10.13/
§10.18 IANA registries, the §3.7 Discrepancy Reporting web service, the
liveness probe, and NTP.

This covers what CORE owns. GCS-specific conformance — the i3 §4.5 contract,
the closed status-code set, PIDF-LO construction — belongs in separate modules
as the engine is built, per i3-fe-core ADOPTION.md's closing note.
"""

from __future__ import annotations

import os

import pytest

# Config that has no safe default must be present before src.server imports,
# because src/runtime_state.py reads the environment at import time and
# src/app/lifecycle.py::validate_config() raises on a missing value.
# See spec Appendix C.4 — the value here is a test fixture, not a
# recommendation.
os.environ.setdefault("GCS_AMBIGUITY_TOLERANCE_M", "150.0")


class _FakeNtpClient:
    """Stand-in so the suite never touches the network. §2.2 only requires the
    client be present and expose is_healthy."""

    is_healthy = True
    offset = 0.0

    async def start(self) -> None:  # pragma: no cover - trivial
        return None

    async def stop(self) -> None:  # pragma: no cover - trivial
        return None


@pytest.fixture()
def gcs_app(monkeypatch):
    """The real src.server:app, with NTP stubbed out.

    NtpClient is patched at the name src.server imported it under, so the
    lifespan builds the fake instead of reaching for pool.ntp.org.
    """
    from src import server

    monkeypatch.setattr(server, "NtpClient", lambda **kwargs: _FakeNtpClient())
    # Hermetic: core conformance covers ElementState/ServiceState/DR/health,
    # none of which need GIS data. Skip the ~37 s cold load whatever the
    # developer's .env says.
    monkeypatch.setenv("GCS_GPKG_PATH", "")
    return server.app


def test_core_conformance(gcs_app):
    from i3_fe_core.conformance.checks import assert_core_conformance

    assert_core_conformance(gcs_app, gcs_app.state.core.identity)


def test_identity_is_gcs(gcs_app):
    """§10.11 serviceNames registry — the token for this FE is "GCS"."""
    identity = gcs_app.state.core.identity
    assert identity.service_name == "GCS"
    assert identity.element_id


def test_service_state_reports_no_security_posture(gcs_app):
    """§2.4.2: securityPosture MUST be absent (not null) for a service that
    does not maintain one. The GCS handles no calls and holds no credentials
    beyond its own TLS material, so it maintains none — same position LVF
    takes."""
    from starlette.testclient import TestClient

    with TestClient(gcs_app) as client:
        body = client.get("/ServiceState").json()
    assert "securityPosture" not in body
