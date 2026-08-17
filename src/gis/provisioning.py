"""GIS data loading and hot-reload for the two layers STA-006.3 Table 4-1
marks Required for the GCS: SiteStructureAddressPoint and RoadCenterLine.

Backed by i3_fe_core.gis.DatasetCache — GcsDatasetSpec below is the seam that
plugs the GCS GeoPackage into that shared cache/reload engine, exactly as
LVF's LvfDatasetSpec does.

SCOPE OF THIS MODULE

This module owns loading, caching and reload state. It owns no knowledge of
what the columns mean: src/gis/records.py holds the column selection and the
row -> record conversion, and this module calls into it.

Reload success/failure NOTIFICATION is the caller's job via the on_success /
on_failure callbacks passed to watch(), not this module's — same split LVF
uses. This module has no dependency on state notifiers or metrics.

Unlike LVF there is no boundary layer and no coverage derivation: the GCS is
not provisioned with service boundary layers, has no coverage region, and
derives none (spec §3.3, §3.6, decision 4).

It also triggers src/gis/field_stats.py's recompute after every (re)load —
the §6.5/§10.6 deployment-discriminative-weight measurement described
there — so a hot GIS reload picks up new field distributions without a
restart.

CACHE SIZE

The first implementation held every source column of every row as a plain
dict, which produced a 128 MB JSON cache against a 45 MB GeoPackage. Two
changes in records.py fixed that at source — explicit column selection and
null omission on serialise. See that module's docstring for the measurements.
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Callable, Optional

from i3_fe_core.gis import DatasetCache

from src.gis import field_stats as gis_field_stats
from src.gis import records as gis_records
from src.gis.records import RCLRecord, SSAPRecord

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GIS data store (populated at startup)
# ---------------------------------------------------------------------------

_ssap: list[SSAPRecord] = []
_rcl: list[RCLRecord] = []

_gis_last_loaded: Optional[datetime.datetime] = None
_cache: Optional[DatasetCache] = None


def _read_layer(gpkg_path: str, layer_name: str, converter) -> list[Any]:
    """Read one GeoPackage layer into records via `converter`."""
    import geopandas as gpd

    gdf = gpd.read_file(gpkg_path, layer=layer_name, engine="pyogrio")
    geom_col = gdf.geometry.name
    return [converter(row, fid, geom_col) for fid, row in gdf.iterrows()]


class GcsDatasetSpec:
    """DatasetSpec adapter: plugs the GCS GeoPackage layers into
    i3_fe_core.gis.DatasetCache."""

    def __init__(self, gpkg_path: str) -> None:
        self._gpkg_path = gpkg_path

    @property
    def source_path(self) -> str:
        return self._gpkg_path

    @property
    def cache_key(self) -> str:
        return "gcs"

    def populate_from_source(self, now: datetime.datetime) -> None:
        global _ssap, _rcl, _gis_last_loaded

        ssap_layer = os.environ.get("GCS_SSAP_LAYER", "SiteStructureAddressPoint")
        rcl_layer = os.environ.get("GCS_RCL_LAYER", "RoadCenterLine")

        for layer_name, store_name, converter in (
            (ssap_layer, "SSAP", gis_records.row_to_ssap),
            (rcl_layer, "RCL", gis_records.row_to_rcl),
        ):
            try:
                rows = _read_layer(self._gpkg_path, layer_name, converter)
            except Exception as exc:
                # Both layers are Required for the GCS (STA-006.3 Table 4-1),
                # but a missing one is reported rather than fatal: the ladder
                # degrades (no SSAP means no rung 1; no RCL means no rungs 2/3)
                # and /ready gates on the combined count.
                log.warning("Could not load %s layer %r: %s", store_name, layer_name, exc)
                continue
            if store_name == "SSAP":
                _ssap = rows
            else:
                _rcl = rows
            log.info("Loaded %d %s records from %r", len(rows), store_name, layer_name)

        gis_field_stats.recompute(_ssap, _rcl)
        _gis_last_loaded = now

    def populate_from_cache(self, payload: dict, now: datetime.datetime) -> None:
        global _ssap, _rcl, _gis_last_loaded
        _ssap = [gis_records.dict_to_ssap(d) for d in payload["ssap"]]
        _rcl = [gis_records.dict_to_rcl(d) for d in payload["rcl"]]
        gis_field_stats.recompute(_ssap, _rcl)
        _gis_last_loaded = now
        log.info("Loaded from cache: %d SSAP, %d RCL", len(_ssap), len(_rcl))

    def serialize(self) -> dict:
        return {
            "ssap": [gis_records.ssap_to_dict(r) for r in _ssap],
            "rcl": [gis_records.rcl_to_dict(r) for r in _rcl],
        }


def load(gpkg_path: str, now: datetime.datetime) -> None:
    """Load GIS data — from the JSON cache when the GeoPackage mtime is
    unchanged, otherwise from the GeoPackage itself."""
    global _cache
    _cache = DatasetCache(
        GcsDatasetSpec(gpkg_path),
        poll_interval_seconds=int(os.environ.get("GCS_GPKG_POLL_INTERVAL_SECONDS", "60")),
    )
    _cache.load(now)


def watch(
    get_now: Callable[[], datetime.datetime],
    on_success: Callable[[], None],
    on_failure: Callable[[Exception], None],
) -> None:
    """Blocking loop (run in a daemon thread): poll the GeoPackage mtime and
    hot-reload on change. No-op if load() has not been called."""
    if _cache is not None:
        _cache.watch(get_now, on_success, on_failure)


def is_reloading() -> bool:
    """True while a hot-reload is in flight. /ready reports 503 on this so the
    load balancer holds traffic off a worker that cannot convert yet
    (spec §3.9.4)."""
    return _cache.is_reloading if _cache is not None else False


def is_loaded() -> bool:
    return bool(_ssap or _rcl)


def ssap_count() -> int:
    return len(_ssap)


def rcl_count() -> int:
    return len(_rcl)


def ssap_records() -> list[SSAPRecord]:
    """The loaded address points. The request path reads the live list.

    Returned by reference rather than copied: a hot reload rebinds the module
    global to a new list, so a request already holding the old one finishes
    against a consistent snapshot instead of seeing a half-swapped dataset.
    """
    return _ssap


def rcl_records() -> list[RCLRecord]:
    """The loaded centerlines. See ssap_records()."""
    return _rcl


def last_loaded() -> Optional[datetime.datetime]:
    return _gis_last_loaded
