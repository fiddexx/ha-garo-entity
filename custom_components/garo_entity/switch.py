"""Charging control switch for GARO Entity."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GaroEntityAPI, GaroEntityError
from .const import CONNECTOR_ID, DATA_API, DATA_COORDINATOR, DOMAIN
from .coordinator import GaroEntityCoordinator
from .entity import GaroEntityBase
from .parsers import (
    active_transaction,
    connector_status,
    station_identifier,
    transaction_identifier,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: GaroEntityCoordinator = runtime[DATA_COORDINATOR]
    api: GaroEntityAPI = runtime[DATA_API]
    async_add_entities(
        GaroChargingSwitch(coordinator, api, entry, station_id)
        for station in coordinator.stations
        if (station_id := station_identifier(station)) is not None
        and station.get("_garo_driver_access") is True
    )


class GaroChargingSwitch(GaroEntityBase, SwitchEntity):
    """Start or stop a charging transaction."""

    _attr_translation_key = "charging"
    _attr_icon = "mdi:ev-station"

    def __init__(
        self,
        coordinator: GaroEntityCoordinator,
        api: GaroEntityAPI,
        entry: ConfigEntry,
        station_id: str,
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self.api = api
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_charging_control"

    @property
    def is_on(self) -> bool:
        if active_transaction(self.station_data.get("transactions")):
            return True
        return connector_status(self.station_data.get("connector"), CONNECTOR_ID) in {
            "Charging",
            "SuspendedEV",
            "SuspendedEVSE",
            "Finishing",
        }

    async def async_turn_on(self, **kwargs: object) -> None:
        if self.is_on:
            return
        try:
            await self.api.async_remote_start(self.station_id, CONNECTOR_ID)
            await self.coordinator.async_refresh_after_command()
        except GaroEntityError as err:
            raise HomeAssistantError(f"GARO could not start charging: {err}") from err

    async def async_turn_off(self, **kwargs: object) -> None:
        transaction = active_transaction(self.station_data.get("transactions"))
        transaction_id = transaction_identifier(transaction)
        if transaction_id is None:
            context = "EVDriver"
            try:
                transactions = await self.api.async_get_transactions(
                    self.station_id, context, CONNECTOR_ID
                )
            except GaroEntityError as err:
                raise HomeAssistantError(
                    f"GARO could not find the active transaction: {err}"
                ) from err
            transaction_id = transaction_identifier(active_transaction(transactions))
        if transaction_id is None:
            raise HomeAssistantError("No active GARO charging transaction was found")
        try:
            await self.api.async_remote_stop(self.station_id, transaction_id)
            await self.coordinator.async_refresh_after_command()
        except GaroEntityError as err:
            raise HomeAssistantError(f"GARO could not stop charging: {err}") from err
