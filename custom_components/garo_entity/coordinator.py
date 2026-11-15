"""Data coordinator for GARO Entity."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GaroEntityAPI, GaroEntityAuthError, GaroEntityError
from .const import (
    CONF_SCHEDULE_ENABLED,
    CONNECTOR_ID,
    DOMAIN,
    OWNER_MAX_CURRENT_KEY,
)
from .local_api import GaroEntityLocalAPI, GaroEntityLocalError
from .parsers import station_identifier
from .schedule import scheduled_limit

_LOGGER = logging.getLogger(__name__)

METER_INTERVAL = 300
CONFIG_INTERVAL = 900
DISCOVERY_INTERVAL = 3600
LOCAL_DATA_KEY = "_local"


class GaroEntityCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinate cloud and optional LAN reads for all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        driver_api: GaroEntityAPI,
        owner_api: GaroEntityAPI | None,
        local_api: GaroEntityLocalAPI | None,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.entry = entry
        self.driver_api = driver_api
        self.owner_api = owner_api
        self.local_api = local_api
        self.stations: list[dict[str, Any]] = []
        self._last_discovery = 0.0
        self._last_meter = 0.0
        self._last_configuration = 0.0

    @property
    def local_data(self) -> dict[str, Any]:
        """Return the latest local controller data."""
        return (self.data or {}).get(LOCAL_DATA_KEY, {})

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        local_data = await self._async_update_local() if self.local_api else None
        now = time.monotonic()
        try:
            if not self.stations or now - self._last_discovery >= DISCOVERY_INTERVAL:
                self.stations = await self._async_discover_stations()
                self._last_discovery = now
            if not self.stations:
                raise UpdateFailed("No GARO Entity charging stations were found")

            include_meter = not self.data or now - self._last_meter >= METER_INTERVAL
            include_configuration = (
                not self.data or now - self._last_configuration >= CONFIG_INTERVAL
            )
            results = await asyncio.gather(
                *(
                    self._async_update_station(
                        station, include_meter, include_configuration
                    )
                    for station in self.stations
                )
            )
            if include_meter:
                self._last_meter = now
            if include_configuration:
                self._last_configuration = now

            data = {
                station_id: station_data
                for station_id, station_data in results
                if station_id
            }
            if local_data is not None:
                data[LOCAL_DATA_KEY] = local_data
            return data
        except GaroEntityAuthError as err:
            raise ConfigEntryAuthFailed from err
        except UpdateFailed:
            raise
        except GaroEntityError as err:
            raise UpdateFailed(f"Error communicating with GARO: {err}") from err

    async def _async_discover_stations(self) -> list[dict[str, Any]]:
        """Merge EVDriver and Owner views of the same physical stations."""
        driver_stations = await self.driver_api.async_get_charging_stations(
            ("EVDriver",)
        )
        owner_stations: list[dict[str, Any]] = []
        if self.owner_api:
            try:
                owner_stations = await self.owner_api.async_get_charging_stations(
                    ("Owner",)
                )
            except GaroEntityError as err:
                _LOGGER.warning(
                    "GARO Owner discovery failed; EVDriver remains active: %s", err
                )
                owner_stations = [
                    dict(station)
                    for station in self.stations
                    if station.get("_garo_owner_access") is True
                ]

        merged: dict[str, dict[str, Any]] = {}
        for source, has_driver, has_owner in (
            (driver_stations, True, False),
            (owner_stations, False, True),
        ):
            for raw in source:
                identifier = station_identifier(raw)
                if not identifier:
                    continue
                station = merged.setdefault(identifier, {})
                station.update(raw)
                station["_garo_driver_access"] = bool(
                    station.get("_garo_driver_access") or has_driver
                )
                station["_garo_owner_access"] = bool(
                    station.get("_garo_owner_access") or has_owner
                )
                contexts = set(station.get("_garo_contexts", []))
                if has_driver:
                    contexts.add("EVDriver")
                if has_owner:
                    contexts.add("Owner")
                station["_garo_contexts"] = sorted(contexts)
                station["_garo_context"] = (
                    "Owner" if "Owner" in contexts else "EVDriver"
                )
        return list(merged.values())

    async def _async_update_station(
        self,
        station: dict[str, Any],
        include_meter: bool,
        include_configuration: bool,
    ) -> tuple[str, dict[str, Any]]:
        station_id = station_identifier(station) or ""
        old = dict((self.data or {}).get(station_id, {}))
        data: dict[str, Any] = {**old, "station": station}
        has_driver = bool(station.get("_garo_driver_access"))
        has_owner = bool(station.get("_garo_owner_access")) and bool(self.owner_api)
        status_api = self.driver_api if has_driver else self.owner_api
        transaction_api = self.driver_api if has_driver else self.owner_api
        context = "EVDriver" if has_driver else "Owner"

        if status_api is None or transaction_api is None:
            return station_id, data

        calls: dict[str, Any] = {
            "connector": status_api.async_get_connector_status(station_id),
            "transactions": transaction_api.async_get_transactions(
                station_id, context, CONNECTOR_ID
            ),
        }
        if include_meter:
            meter_api = self.owner_api if has_owner else self.driver_api
            meter_context = "Owner" if has_owner else "EVDriver"
            calls["meter_values"] = meter_api.async_get_latest_meter_values(
                station_id, meter_context, CONNECTOR_ID
            )
        if include_configuration and has_owner and self.owner_api:
            calls["configuration"] = self.owner_api.async_get_configuration(
                station_id, [OWNER_MAX_CURRENT_KEY]
            )

        keys = list(calls)
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        connector_updated = False
        for key, result in zip(keys, results, strict=True):
            if isinstance(result, GaroEntityAuthError):
                raise result
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "GARO %s update failed for %s: %s", key, station_id, result
                )
                continue
            data[key] = result
            if key == "connector":
                connector_updated = True
        data["available"] = connector_updated or bool(old.get("available"))
        return station_id, data

    async def _async_update_local(self) -> dict[str, Any]:
        """Read LAN values and enforce the optional peak-period schedule."""
        assert self.local_api is not None
        old = dict((self.data or {}).get(LOCAL_DATA_KEY, {}))
        limit_result, meter_result = await asyncio.gather(
            self.local_api.async_get_limit(),
            self.local_api.async_get_energy_status(),
            return_exceptions=True,
        )
        if isinstance(limit_result, Exception) and isinstance(
            meter_result, Exception
        ):
            _LOGGER.warning("GARO local update failed: %s", limit_result)
            return {**old, "available": False}

        data = {**old, "available": True}
        if not isinstance(meter_result, Exception):
            data.update(meter_result)
        else:
            _LOGGER.warning("GARO local meter update failed: %s", meter_result)

        target, active = scheduled_limit(self.entry.options, dt_util.now())
        data["schedule_enabled"] = bool(
            self.entry.options.get(CONF_SCHEDULE_ENABLED, False)
        )
        data["schedule_active"] = active
        data["schedule_target_a"] = target if data["schedule_enabled"] else None

        if isinstance(limit_result, Exception):
            _LOGGER.warning("GARO local current-limit update failed: %s", limit_result)
            return data

        current_limit = float(limit_result)
        if data["schedule_enabled"] and round(current_limit) != target:
            try:
                await self.local_api.async_set_limit(target)
            except GaroEntityLocalError as err:
                _LOGGER.warning("GARO local schedule command failed: %s", err)
            else:
                current_limit = float(target)
                data["last_schedule_change"] = dt_util.utcnow().isoformat()
        data["current_limit_a"] = current_limit
        return data

    async def async_refresh_after_command(self, delay: float = 2.0) -> None:
        """Refresh shortly after a cloud or local command was sent."""
        await asyncio.sleep(delay)
        await self.async_request_refresh()
