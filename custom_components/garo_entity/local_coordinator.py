"""Independent polling for each local endpoint; only the balancer may write."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import CONF_LOCAL_IS_BALANCER, CONF_SCHEDULE_ENABLED, DOMAIN
from .local_api import GaroEntityLocalError
from .schedule import scheduled_limit

_LOGGER = logging.getLogger(__name__)


class GaroLocalCoordinator(DataUpdateCoordinator):
    """Poll one local device independently from cloud and other local devices."""

    def __init__(self, hass, entry, api, role, scan_interval):
        if role not in {"charger", "balancer"}:
            raise ValueError("Unknown local endpoint role")
        super().__init__(
            hass, _LOGGER, config_entry=entry,
            name=f"{DOMAIN}_{role}",
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.entry = entry
        self.local_api = api
        self.role = role

    @property
    def local_data(self):
        return self.data or {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Read LAN values and enforce the optional peak-period schedule."""
        if self.role == "charger":
            try:
                meter = await self.local_api.async_get_energy_status()
            except GaroEntityLocalError:
                return {"available": False, "meter_available": False}
            return {**meter, "available": True, "meter_available": True}
        old = dict(self.data or {})
        limit_result, meter_result = await asyncio.gather(
            self.local_api.async_get_limit(),
            self.local_api.async_get_energy_status(),
            return_exceptions=True,
        )
        if isinstance(limit_result, Exception) and isinstance(
            meter_result, Exception
        ):
            _LOGGER.warning("GARO local update failed: %s", limit_result)
            return {"available": False, "meter_available": False, "limit_available": False}

        data = {"available": True, "meter_available": not isinstance(meter_result, Exception),
                "limit_available": not isinstance(limit_result, Exception),
                "last_schedule_change": old.get("last_schedule_change")}
        if not isinstance(meter_result, Exception):
            data.update(meter_result)
        else:
            _LOGGER.warning("GARO local meter update failed: %s", meter_result)

        target, active = scheduled_limit(self.entry.options, dt_util.now())
        data["schedule_enabled"] = bool(
            self.entry.options.get(CONF_SCHEDULE_ENABLED, False)
            and self.entry.options.get(CONF_LOCAL_IS_BALANCER, False)
        )
        data["schedule_active"] = active
        data["schedule_target_a"] = target if data["schedule_enabled"] else None

        if isinstance(limit_result, Exception):
            _LOGGER.warning("GARO local current-limit update failed: %s", limit_result)
            return data

        current_limit = float(limit_result)
        if data["schedule_enabled"] and current_limit != target:
            try:
                await self.local_api.async_set_limit(target)
            except GaroEntityLocalError as err:
                _LOGGER.warning("GARO local schedule command failed: %s", err)
            else:
                try:
                    current_limit = float(await self.local_api.async_get_limit())
                except GaroEntityLocalError:
                    data["limit_available"] = False
                else:
                    if current_limit == target:
                        data["last_schedule_change"] = dt_util.utcnow().isoformat()
        data["current_limit_a"] = current_limit
        return data

