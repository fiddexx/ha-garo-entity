"""Diagnostics support for GARO Entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .local_options import LOCAL_CREDENTIAL_KEYS
from .const import (
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_USERNAME,
    CONF_OWNER_PASSWORD,
    CONF_OWNER_USERNAME,
    DATA_COORDINATOR,
    DATA_BALANCER_COORDINATOR,
    DATA_CHARGER_COORDINATOR,
    DOMAIN,
)

TO_REDACT = {
    *LOCAL_CREDENTIAL_KEYS,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_OWNER_PASSWORD,
    CONF_OWNER_USERNAME,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_USERNAME,
    "access_token",
    "refresh_token",
    "id_token",
    "connected_task_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted data useful when reporting a problem."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "stations": async_redact_data(coordinator.data or {}, TO_REDACT),
        "local": {
            key: async_redact_data(local.data or {}, TO_REDACT)
            for key in (DATA_BALANCER_COORDINATOR, DATA_CHARGER_COORDINATOR)
            if (local := hass.data[DOMAIN][entry.entry_id].get(key)) is not None
        },
    }
