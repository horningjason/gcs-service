"""
Shared, cross-cutting runtime singletons and config.

No business logic belongs here — only state and the minimal setup needed to
initialize it. Deep call sites in src/api/, src/geocode/ and src/reverse/ read
the notifiers and the logging client from here rather than threading
app.state.core through every call.

Mirrors lvf-service/src/runtime_state.py. What is deliberately absent is the
whole federation block LVF carries here (_parent_uri, _sync_children,
_root_ams, _forest_guide_*, _default_mapping_source_id): the GCS has no
coverage region, no recursion and no redirection on its own initiative
(spec §3.1, §3.6, decision 4).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_log_level_name = os.environ.get("GCS_LOG_LEVEL", "INFO").upper()
_log_level = getattr(logging, _log_level_name, None)
if not isinstance(_log_level, int):
    logging.warning("GCS_LOG_LEVEL=%r is not a valid level — defaulting to INFO", _log_level_name)
    _log_level = logging.INFO
_src_logger = logging.getLogger("src")
_src_logger.setLevel(_log_level)
if not _src_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    _h.setLevel(_log_level)
    _src_logger.addHandler(_h)
    # uvicorn's handler lives on "uvicorn", not root — prevent double-logging
    _src_logger.propagate = False

from i3_fe_core.time.ntp import NtpClient

log = logging.getLogger(__name__)

# --- Identity ---------------------------------------------------------------

_server_uri: str = os.environ.get("GCS_SERVER_URI", "gcs.example.com")

# --- Referral (spec §3.6.2, decision 5) -------------------------------------
# Statically provisioned. Empty is a deliberate, documented state: conversion
# failure then returns 468 with no referral, a knowing departure from i3
# §4.5's MUST recorded as a §16 gap row. When set, the URI travels in the
# Location header of a 307 (decision 34, confirmed against the normative YAML —
# GeodeticData has no gcsReferralUri property at all).
_referral_uri: str = os.environ.get("GCS_REFERRAL_URI", "").strip()

if not _referral_uri:
    log.info(
        "GCS_REFERRAL_URI is not configured — conversion failures will return 468 "
        "without a referral (documented departure from i3 §4.5, spec §16)"
    )

# --- Conversion tuning ------------------------------------------------------
# Distances are metres, true geodesic on the WGS84 spheroid (spec §10.2,
# decision 40). The four values below carry implementation-chosen defaults
# that Appendix C item (a) explicitly defers; GCS_AMBIGUITY_TOLERANCE_M
# deliberately has none. See _require_float() below and .env.example.


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("%s=%r is not a number — using default %s", name, raw, default)
        return default


def _require_float(name: str) -> Optional[float]:
    """Read a variable that has no safe default.

    Returns None when unset. src/app/lifecycle.py raises on None at startup
    rather than this module doing it at import time, so that test collection
    and `--help`-style invocations do not explode on an unconfigured checkout.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        log.error("%s=%r is not a number", name, raw)
        return None


_rcl_offset_m: float = _env_float("GCS_RCL_OFFSET_M", 10.0)
_rcl_endpoint_margin_m: float = _env_float("GCS_RCL_ENDPOINT_MARGIN_M", 15.0)
_min_match_score: float = _env_float("GCS_MIN_MATCH_SCORE", 60.0)
_reverse_search_radius_m: float = _env_float("GCS_REVERSE_SEARCH_RADIUS_M", 250.0)
# Not one of the four deferred defaults above: 0.9 is settled by decision 83 as
# a deliberate editorial value (§10.6). It is unsweepable — STA-006.3 records
# that a placement was geocoded, never how far off that derivation was — and it
# moves only the reported spatial-fit number and confidence, never candidate
# order, admission, or a 200-vs-468. This binding IS the tuning mechanism: a
# deployment that knows its own geocoded placements adjusts the variable.
_geocoded_placement_penalty: float = _env_float("GCS_GEOCODED_PLACEMENT_PENALTY", 0.9)
_ambiguity_tolerance_m: Optional[float] = _require_float("GCS_AMBIGUITY_TOLERANCE_M")

# --- Interface toggles ------------------------------------------------------
# The i3-improved resources (spec §3.9.2, decision 35). The strict i3 paths are
# byte-for-byte conformant either way.
_enable_enhanced: bool = os.environ.get("GCS_ENABLE_ENHANCED", "true").strip().lower() == "true"

# --- Process-wide handles ---------------------------------------------------

_SERVER_START_TIME: str = datetime.datetime.now(datetime.timezone.utc).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)

_event_loop: Optional[asyncio.AbstractEventLoop] = None
_ntp_client: Optional[NtpClient] = None

# Mirrored from app.state.core in server.py at import time.
state_store = None
element_notifier = None
service_notifier = None
discrepancy = None
logging_client = None


def now() -> datetime.datetime:
    """Current UTC time, corrected by the NTP client's measured offset
    (NENA-STA-010.3f-2021 §2.2). Falls back to the host clock when no NTP
    sample is available yet or NTP is unconfigured."""
    base = datetime.datetime.now(datetime.timezone.utc)
    if _ntp_client is not None and _ntp_client.offset is not None:
        base += datetime.timedelta(seconds=_ntp_client.offset)
    return base
