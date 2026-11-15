"""Pure parsing helpers for GARO Entity API payloads."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

TERMINAL_TRANSACTION_STATES = {
    "aborted",
    "cancelled",
    "completed",
    "ended",
    "finished",
    "stopped",
}


def _items(payload: Any, keys: Iterable[str]) -> list[dict[str, Any]]:
    """Return dictionaries from common GARO response envelopes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def station_identifier(station: dict[str, Any]) -> str | None:
    """Return the stable UUID/string accepted by GARO station endpoints."""
    value = station.get("id") or station.get("uid") or station.get("device_id")
    return str(value) if value else None


def station_name(station: dict[str, Any]) -> str:
    """Return a human-friendly station name."""
    value = station.get("name") or station.get("uid") or station_identifier(station)
    return str(value or "GARO Entity")


def extract_connectors(payload: Any) -> list[dict[str, Any]]:
    """Extract connector status objects."""
    if isinstance(payload, dict) and "connector_id" in payload:
        return [payload]
    return _items(payload, ("items", "connectors", "connector_status"))


def connector(payload: Any, connector_id: int = 1) -> dict[str, Any] | None:
    """Return one connector, preferring the requested connector id."""
    connectors = extract_connectors(payload)
    for item in connectors:
        try:
            if int(item.get("connector_id", -1)) == connector_id:
                return item
        except (TypeError, ValueError):
            continue
    return connectors[0] if len(connectors) == 1 else None


def connector_status(payload: Any, connector_id: int = 1) -> str | None:
    """Return the raw GARO/OCPP connector state."""
    item = connector(payload, connector_id)
    value = item.get("status") if item else None
    return str(value) if value is not None else None


def extract_transactions(payload: Any) -> list[dict[str, Any]]:
    """Extract and newest-first sort transactions."""
    values = _items(payload, ("items", "transactions", "data"))
    return sorted(values, key=_transaction_sort_key, reverse=True)


def _transaction_sort_key(transaction: dict[str, Any]) -> tuple[str, str]:
    timestamp = (
        transaction.get("start_time")
        or transaction.get("started_at")
        or transaction.get("end_time")
        or ""
    )
    identifier = transaction.get("id") or transaction.get("transaction_id") or ""
    return str(timestamp), str(identifier)


def is_active_transaction(transaction: dict[str, Any]) -> bool:
    """Return whether a transaction appears to still be active."""
    state = str(transaction.get("state") or transaction.get("status") or "").lower()
    if state in TERMINAL_TRANSACTION_STATES:
        return False
    if transaction.get("meter_stop") is not None or transaction.get("end_time"):
        return False
    return bool(transaction.get("id") or transaction.get("transaction_id"))


def active_transaction(payload: Any) -> dict[str, Any] | None:
    """Return the newest active transaction."""
    return next(
        (item for item in extract_transactions(payload) if is_active_transaction(item)),
        None,
    )


def latest_transaction(payload: Any) -> dict[str, Any] | None:
    """Return the newest transaction, active or completed."""
    values = extract_transactions(payload)
    return values[0] if values else None


def latest_completed_transaction(payload: Any) -> dict[str, Any] | None:
    """Return the newest completed transaction."""
    return next(
        (
            item
            for item in extract_transactions(payload)
            if not is_active_transaction(item)
        ),
        None,
    )


def transaction_identifier(transaction: dict[str, Any] | None) -> int | None:
    """Return the integer transaction id required by RemoteStopTransaction."""
    if not transaction:
        return None
    value = transaction.get("id") or transaction.get("transaction_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def transaction_energy_kwh(
    transaction: dict[str, Any] | None,
    current_meter_value: float | None = None,
    current_meter_unit: str | None = None,
) -> float | None:
    """Calculate transaction energy in kWh from OCPP Wh meter registers."""
    if not transaction:
        return None
    meter_start = _float(transaction.get("meter_start"))
    meter_stop = _float(transaction.get("meter_stop"))
    if meter_start is None:
        direct = _float(
            transaction.get("energy_kwh") or transaction.get("energy_consumed_kwh")
        )
        return round(direct, 3) if direct is not None else None

    if meter_stop is None and current_meter_value is not None:
        meter_stop = energy_to_wh(current_meter_value, current_meter_unit)
    if meter_stop is None:
        return 0.0 if is_active_transaction(transaction) else None

    delta_wh = meter_stop - meter_start
    if delta_wh < 0:
        return None
    return round(delta_wh / 1000.0, 3)


def extract_meter_samples(payload: Any) -> list[dict[str, Any]]:
    """Extract meter samples from GARO's list response or common envelopes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "measures", "meter_values", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if "measure_name" in payload or "name" in payload:
        return [payload]
    return []


def meter_sample(payload: Any, measure_name: str) -> dict[str, Any] | None:
    """Return the newest matching meter sample."""
    matches: list[dict[str, Any]] = []
    for item in extract_meter_samples(payload):
        name = item.get("measure_name") or item.get("name") or item.get("measurand")
        if name == measure_name:
            matches.append(item)
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: str(
            item.get("time") or item.get("timestamp") or item.get("sampled_at") or ""
        ),
    )


def sample_value(sample: dict[str, Any] | None) -> float | None:
    """Return the numeric value from a meter sample."""
    if not sample:
        return None
    value = (
        sample.get("measure_value")
        if "measure_value" in sample
        else sample.get("value")
    )
    return _float(value)


def sample_unit(sample: dict[str, Any] | None) -> str | None:
    """Return the unit from a meter sample."""
    if not sample:
        return None
    value = sample.get("unit") or sample.get("unit_of_measurement")
    return str(value) if value else None


def energy_to_wh(value: float, unit: str | None) -> float:
    """Normalize an energy value to Wh."""
    normalized = (unit or "Wh").strip().lower().replace(" ", "")
    if normalized in {"kwh", "kilowatthour", "kilowatt-hour"}:
        return value * 1000.0
    if normalized in {"mwh", "megawatthour", "megawatt-hour"}:
        return value * 1_000_000.0
    return value


def energy_to_kwh(value: float, unit: str | None) -> float:
    """Normalize an energy value to kWh."""
    return energy_to_wh(value, unit) / 1000.0


def power_to_w(value: float, unit: str | None) -> float:
    """Normalize a power value to W."""
    normalized = (unit or "W").strip().lower().replace(" ", "")
    if normalized in {"kw", "kilowatt"}:
        return value * 1000.0
    if normalized in {"mw", "megawatt"}:
        return value * 1_000_000.0
    return value


def configuration_items(payload: Any) -> list[dict[str, Any]]:
    """Extract configuration key/value entries."""
    return _items(payload, ("configuration_key", "configuration", "items", "data"))


def configuration_value(payload: Any, key: str) -> str | None:
    """Return one configuration value."""
    for item in configuration_items(payload):
        if item.get("key") == key and item.get("value") is not None:
            return str(item["value"])
    return None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp for a timestamp sensor."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
