"""Sensor entities for GARO Entity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONNECTOR_ID, DATA_COORDINATOR, DATA_LOCAL_API, DOMAIN
from .coordinator import GaroEntityCoordinator
from .entity import GaroEntityBase, GaroLocalEntity
from .parsers import (
    active_transaction,
    connector,
    connector_status,
    energy_to_kwh,
    extract_meter_samples,
    latest_transaction,
    meter_sample,
    parse_timestamp,
    power_to_w,
    sample_unit,
    sample_value,
    station_identifier,
    transaction_energy_kwh,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one set of sensors per discovered charging station."""
    coordinator: GaroEntityCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    entities: list[SensorEntity] = []
    for station in coordinator.stations:
        station_id = station_identifier(station)
        if station_id is None:
            continue
        entities.extend(
            (
                GaroConnectorStatusSensor(coordinator, entry, station_id),
                GaroSessionEnergySensor(coordinator, entry, station_id),
                GaroSessionStartSensor(coordinator, entry, station_id),
                GaroSessionEndSensor(coordinator, entry, station_id),
                GaroTotalEnergySensor(coordinator, entry, station_id),
                GaroPowerSensor(coordinator, entry, station_id),
                GaroOfferedCurrentSensor(coordinator, entry, station_id),
            )
        )
    if hass.data[DOMAIN][entry.entry_id][DATA_LOCAL_API] is not None:
        entities.extend(
            (
                GaroLocalPowerSensor(coordinator, entry),
                GaroLocalPhaseCurrentSensor(coordinator, entry, "L1"),
                GaroLocalPhaseCurrentSensor(coordinator, entry, "L2"),
                GaroLocalPhaseCurrentSensor(coordinator, entry, "L3"),
                GaroLocalCurrentLimitSensor(coordinator, entry),
                GaroScheduleStatusSensor(coordinator, entry),
            )
        )
    async_add_entities(entities)


class GaroConnectorStatusSensor(GaroEntityBase, SensorEntity):
    """Current OCPP connector status."""

    _attr_translation_key = "connector_status"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_connector_{CONNECTOR_ID}"

    @property
    def native_value(self) -> str | None:
        return connector_status(self.station_data.get("connector"), CONNECTOR_ID)

    @property
    def icon(self) -> str:
        status = self.native_value
        if status == "Charging":
            return "mdi:ev-station"
        if status in {"Faulted", "Unavailable"}:
            return "mdi:alert-circle"
        if status in {"Preparing", "Occupied", "Reserved"}:
            return "mdi:ev-plug-type2"
        return "mdi:ev-plug-type2"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        item = connector(self.station_data.get("connector"), CONNECTOR_ID)
        if not item:
            return None
        return {
            "limited": item.get("limited"),
            "timestamp": item.get("timestamp"),
            "connector_id": item.get("connector_id", CONNECTOR_ID),
        }


class GaroSessionEnergySensor(GaroEntityBase, SensorEntity):
    """Energy used by the active or latest charging session."""

    _attr_translation_key = "session_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-charging"
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_transaction_energy"

    @property
    def native_value(self) -> float | None:
        transaction = latest_transaction(self.station_data.get("transactions"))
        sample = _energy_sample(self.station_data.get("meter_values"))
        return transaction_energy_kwh(
            transaction,
            sample_value(sample),
            sample_unit(sample),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        transaction = latest_transaction(self.station_data.get("transactions"))
        if not transaction:
            return None
        return {
            "transaction_id": transaction.get("id"),
            "state": transaction.get("state"),
            "connector_id": transaction.get("connector_id"),
            "start_time": transaction.get("start_time"),
            "end_time": transaction.get("end_time"),
            "active": active_transaction(self.station_data.get("transactions"))
            is not None,
        }


class _GaroSessionTimestampSensor(GaroEntityBase, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    transaction_field: str

    @property
    def native_value(self) -> datetime | None:
        transaction = latest_transaction(self.station_data.get("transactions"))
        return (
            parse_timestamp(transaction.get(self.transaction_field))
            if transaction
            else None
        )


class GaroSessionStartSensor(_GaroSessionTimestampSensor):
    """Start time for the active or latest session."""

    _attr_translation_key = "session_start"
    _attr_icon = "mdi:clock-start"
    transaction_field = "start_time"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_transaction_start_time"


class GaroSessionEndSensor(_GaroSessionTimestampSensor):
    """End time for the latest completed session."""

    _attr_translation_key = "session_end"
    _attr_icon = "mdi:clock-end"
    transaction_field = "end_time"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_transaction_end_time"


class GaroTotalEnergySensor(GaroEntityBase, SensorEntity):
    """Cumulative imported charger energy."""

    _attr_translation_key = "total_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_total_energy"

    @property
    def native_value(self) -> float | None:
        sample = _energy_sample(self.station_data.get("meter_values"))
        value = sample_value(sample)
        if value is None:
            return None
        return round(energy_to_kwh(value, sample_unit(sample)), 3)


class GaroPowerSensor(GaroEntityBase, SensorEntity):
    """Latest active charging power."""

    _attr_translation_key = "charging_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:flash"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_charging_power"

    @property
    def native_value(self) -> float | None:
        sample = _preferred_sample(
            self.station_data.get("meter_values"), "Power.Active.Import"
        )
        value = sample_value(sample)
        if value is None:
            return None
        return round(power_to_w(value, sample_unit(sample)), 1)


class GaroOfferedCurrentSensor(GaroEntityBase, SensorEntity):
    """Latest current offered to the vehicle."""

    _attr_translation_key = "offered_current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-ac"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry, station_id: str
    ) -> None:
        super().__init__(coordinator, entry, station_id)
        self._attr_unique_id = f"{entry.entry_id}_{station_id}_offered_current"

    @property
    def native_value(self) -> float | None:
        sample = _preferred_sample(
            self.station_data.get("meter_values"), "Current.Offered"
        )
        return sample_value(sample)


class GaroLocalPowerSensor(GaroLocalEntity, SensorEntity):
    """Total power reported or estimated by the local controller."""

    _attr_translation_key = "local_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:home-lightning-bolt"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_local_total_power"

    @property
    def native_value(self) -> float | None:
        value = self.local_data.get("total_power_w")
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "estimated": self.local_data.get("power_estimated"),
            "timestamp": self.local_data.get("timestamp"),
        }


class GaroLocalPhaseCurrentSensor(GaroLocalEntity, SensorEntity):
    """Current on one phase from the local controller."""

    _attr_translation_key = "phase_current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:current-ac"

    def __init__(
        self,
        coordinator: GaroEntityCoordinator,
        entry: ConfigEntry,
        phase: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self.phase = phase
        self._attr_translation_placeholders = {"phase": phase}
        self._attr_unique_id = f"{entry.entry_id}_local_current_{phase.lower()}"

    @property
    def native_value(self) -> float | None:
        value = self.local_data.get("phase_currents", {}).get(self.phase)
        return float(value) if value is not None else None


class GaroScheduleStatusSensor(GaroLocalEntity, SensorEntity):
    """Status of the optional local peak-period current schedule."""

    _attr_translation_key = "schedule_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["disabled", "standard", "peak"]
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_local_schedule_status"

    @property
    def native_value(self) -> str:
        if not self.local_data.get("schedule_enabled"):
            return "disabled"
        return "peak" if self.local_data.get("schedule_active") else "standard"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "target_current_a": self.local_data.get("schedule_target_a"),
            "last_change": self.local_data.get("last_schedule_change"),
        }


class GaroLocalCurrentLimitSensor(GaroLocalEntity, SensorEntity):
    """Current GaroConnectionGroupMaxCurrent value from the LAN API."""

    _attr_translation_key = "connection_group_max_current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:transmission-tower"

    def __init__(
        self, coordinator: GaroEntityCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_local_connection_group_max_current"

    @property
    def native_value(self) -> float | None:
        value = self.local_data.get("current_limit_a")
        return float(value) if value is not None else None


def _preferred_sample(payload: Any, measure_name: str) -> dict[str, Any] | None:
    """Prefer an aggregate/unphased sample over a single phase value."""
    samples = [
        item
        for item in extract_meter_samples(payload)
        if item.get("measure_name") == measure_name
    ]
    aggregate = [item for item in samples if not item.get("phase")]
    if aggregate:
        return max(aggregate, key=lambda item: str(item.get("time") or ""))
    return meter_sample(payload, measure_name)


def _energy_sample(payload: Any) -> dict[str, Any] | None:
    """Prefer GARO's charger-specific EV register when available."""
    return _preferred_sample(payload, "Energy.EV.Import.Register") or _preferred_sample(
        payload, "Energy.Active.Import.Register"
    )
