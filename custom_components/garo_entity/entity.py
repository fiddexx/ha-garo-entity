"""Shared GARO Entity entity base."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GaroEntityCoordinator
from .local_coordinator import GaroLocalCoordinator
from .parsers import station_name


class GaroEntityBase(CoordinatorEntity[GaroEntityCoordinator]):
    """Base class linked to one GARO charging station."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GaroEntityCoordinator,
        entry: ConfigEntry,
        station_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self.station_id = station_id

    @property
    def station_data(self) -> dict[str, Any]:
        """Return cached coordinator data for this station."""
        return (self.coordinator.data or {}).get(self.station_id, {})

    @property
    def station(self) -> dict[str, Any]:
        return self.station_data.get("station", {})

    @property
    def available(self) -> bool:
        data = self.station_data
        return super().available and bool(data) and bool(data.get("available", False))

    @property
    def device_info(self) -> DeviceInfo:
        unit = self.station.get("charging_unit") or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.station_id)},
            name=station_name(self.station),
            manufacturer="GARO",
            model=unit.get("model") or "Entity",
            sw_version=unit.get("firmware_version"),
            serial_number=unit.get("serial_number") or self.station.get("uid"),
            configuration_url="https://www.garoconnect.com/",
        )


class GaroLocalEntity(CoordinatorEntity[GaroLocalCoordinator]):
    """Base class for values exposed by the local GARO controller."""

    _attr_has_entity_name = True
    _availability_key = "meter_available"

    def __init__(
        self, coordinator: GaroLocalCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def local_data(self) -> dict[str, Any]:
        return self.coordinator.local_data

    @property
    def available(self) -> bool:
        return (super().available and bool(self.local_data.get("available"))
                and bool(self.local_data.get(self._availability_key, False)))

    @property
    def device_info(self) -> DeviceInfo:
        local_api = self.coordinator.local_api
        host = local_api.base_url if local_api else "local"
        return DeviceInfo(
            identifiers={(DOMAIN, f"charger_local_{host}" if self.coordinator.role == "charger" else f"local_{host}")},
            name="GARO Entity Charger (local)" if self.coordinator.role == "charger" else "GARO Entity Balance (local)",
            manufacturer="GARO",
            model="Entity Charger" if self.coordinator.role == "charger" else "Entity Balance",
            configuration_url=host if local_api else None,
        )
