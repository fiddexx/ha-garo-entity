"""Number entities for GARO Entity."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GaroEntityAPI, GaroEntityError
from .const import (
    DATA_COORDINATOR,
    DATA_OWNER_API,
    DOMAIN,
    OWNER_MAX_CURRENT_KEY,
)
from .coordinator import GaroEntityCoordinator
from .entity import GaroEntityBase
from .parsers import configuration_items, configuration_value, station_identifier


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: GaroEntityCoordinator = runtime[DATA_COORDINATOR]
    owner_api: GaroEntityAPI | None = runtime[DATA_OWNER_API]
    entities: list[NumberEntity] = []
    for station in coordinator.stations:
        station_id = station_identifier(station)
        if station_id is None:
            continue
        if owner_api is not None and station.get("_garo_owner_access") is True:
            entities.append(
                GaroOwnerMaxCurrent(coordinator, owner_api, entry, station_id)
            )
    async_add_entities(entities)


class GaroOwnerMaxCurrent(GaroEntityBase, NumberEntity):
    """Owner-configurable per-station charging current limit."""

    _attr_translation_key = "owner_max_current"
    _attr_icon = "mdi:current-ac"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = 6
    _attr_native_max_value = 32
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: GaroEntityCoordinator,
        api: GaroEntityAPI,
        entry: ConfigEntry,
        station_id: str,
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self.api = api
        self._attr_unique_id = (
            f"{entry.entry_id}_{station_id}_number_{OWNER_MAX_CURRENT_KEY.lower()}"
        )

    @property
    def native_value(self) -> float | None:
        value = configuration_value(
            self.station_data.get("configuration"), OWNER_MAX_CURRENT_KEY
        )
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        current = int(value)
        try:
            await self.api.async_set_configuration(
                self.station_id, OWNER_MAX_CURRENT_KEY, current
            )
        except GaroEntityError as err:
            raise HomeAssistantError(
                f"GARO could not set the maximum charging current: {err}"
            ) from err

        payload = self.station_data.get("configuration")
        for item in configuration_items(payload):
            if item.get("key") == OWNER_MAX_CURRENT_KEY:
                item["value"] = str(current)
                item["status"] = "Accepted"
                break
        self.coordinator.async_update_listeners()
