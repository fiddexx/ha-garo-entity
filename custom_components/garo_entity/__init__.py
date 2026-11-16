"""The GARO Entity integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GaroEntityAPI
from .const import (
    CONF_API_BASE_URL,
    CONF_COGNITO_CLIENT_ID,
    CONF_COGNITO_REGION,
    CONF_LOCAL_ENABLED,
    CONF_LOCAL_HOST,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_USERNAME,
    CONF_LOCAL_VERIFY_SSL,
    CONF_OWNER_COGNITO_CLIENT_ID,
    CONF_OWNER_PASSWORD,
    CONF_OWNER_USERNAME,
    CONF_SCAN_INTERVAL,
    DATA_API,
    DATA_COORDINATOR,
    DATA_OWNER_API,
    DEFAULT_API_BASE_URL,
    DEFAULT_COGNITO_CLIENT_ID,
    DEFAULT_COGNITO_REGION,
    DEFAULT_LOCAL_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import GaroEntityCoordinator
from .local_coordinator import GaroLocalCoordinator
from .local_options import migrate_local_credentials
from .const import (
    CONF_CHARGER_ENABLED, CONF_CHARGER_HOST, CONF_CHARGER_USERNAME,
    CONF_CHARGER_PASSWORD, CONF_CHARGER_VERIFY_SSL,
    DATA_BALANCER_COORDINATOR, DATA_CHARGER_COORDINATOR,
)
from .local_api import GaroEntityLocalAPI

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GARO Entity from a config entry."""
    data, options = migrate_local_credentials(dict(entry.data), dict(entry.options))
    if data != dict(entry.data) or options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, data=data, options=options)
    session = async_get_clientsession(hass)
    driver_api = GaroEntityAPI(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        cognito_client_id=entry.data.get(
            CONF_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID
        ),
        cognito_region=entry.data.get(CONF_COGNITO_REGION, DEFAULT_COGNITO_REGION),
        api_base_url=entry.data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL),
    )
    owner_api = None
    if owner_username := entry.data.get(CONF_OWNER_USERNAME):
        owner_api = GaroEntityAPI(
            session=session,
            username=owner_username,
            password=entry.data[CONF_OWNER_PASSWORD],
            cognito_client_id=entry.data.get(
                CONF_OWNER_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID
            ),
            cognito_region=entry.data.get(
                CONF_COGNITO_REGION, DEFAULT_COGNITO_REGION
            ),
            api_base_url=entry.data.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL),
        )

    coordinator = GaroEntityCoordinator(
        hass,
        entry,
        driver_api,
        owner_api,
        int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()

    local_coordinators = {}
    for role, enabled, host, username, password, verify, key in (
        ("balancer", CONF_LOCAL_ENABLED, CONF_LOCAL_HOST, CONF_LOCAL_USERNAME,
         CONF_LOCAL_PASSWORD, CONF_LOCAL_VERIFY_SSL, DATA_BALANCER_COORDINATOR),
        ("charger", CONF_CHARGER_ENABLED, CONF_CHARGER_HOST, CONF_CHARGER_USERNAME,
         CONF_CHARGER_PASSWORD, CONF_CHARGER_VERIFY_SSL, DATA_CHARGER_COORDINATOR),
    ):
        local_coordinators[key] = None
        if entry.options.get(enabled, False):
            api = GaroEntityLocalAPI(session, entry.options[host],
                entry.data[username], entry.data[password],
                bool(entry.options.get(verify, DEFAULT_LOCAL_VERIFY_SSL)))
            local = GaroLocalCoordinator(hass, entry, api, role,
                int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
            await local.async_config_entry_first_refresh()
            local_coordinators[key] = local

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_API: driver_api,
        DATA_OWNER_API: owner_api,
        **local_coordinators,
        DATA_COORDINATOR: coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
