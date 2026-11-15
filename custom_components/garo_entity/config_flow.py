"""Config and options flows for GARO Entity."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .api import (
    GaroEntityAPI,
    GaroEntityAuthError,
    GaroEntityConnectionError,
    GaroEntityPermissionError,
)
from .const import (
    CONF_COGNITO_CLIENT_ID,
    CONF_LOCAL_ENABLED,
    CONF_LOCAL_HOST,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_USERNAME,
    CONF_LOCAL_VERIFY_SSL,
    CONF_OWNER_COGNITO_CLIENT_ID,
    CONF_OWNER_PASSWORD,
    CONF_OWNER_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DEFAULT_LIMIT,
    CONF_SCHEDULE_ENABLED,
    CONF_SCHEDULE_END,
    CONF_SCHEDULE_MONTHS,
    CONF_SCHEDULE_PEAK_LIMIT,
    CONF_SCHEDULE_START,
    CONF_SCHEDULE_WEEKDAYS,
    DEFAULT_COGNITO_CLIENT_ID,
    DEFAULT_LOCAL_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_DEFAULT_LIMIT,
    DEFAULT_SCHEDULE_END,
    DEFAULT_SCHEDULE_MONTHS,
    DEFAULT_SCHEDULE_PEAK_LIMIT,
    DEFAULT_SCHEDULE_START,
    DEFAULT_SCHEDULE_WEEKDAYS,
    DOMAIN,
    LOCAL_MAX_CURRENT,
    LOCAL_MIN_CURRENT,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .local_api import GaroEntityLocalAPI, GaroEntityLocalError
from .parsers import station_identifier

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD)
)

WEEKDAY_OPTIONS = [
    SelectOptionDict(value="0", label="Mon / Mån"),
    SelectOptionDict(value="1", label="Tue / Tis"),
    SelectOptionDict(value="2", label="Wed / Ons"),
    SelectOptionDict(value="3", label="Thu / Tor"),
    SelectOptionDict(value="4", label="Fri / Fre"),
    SelectOptionDict(value="5", label="Sat / Lör"),
    SelectOptionDict(value="6", label="Sun / Sön"),
]
MONTH_OPTIONS = [
    SelectOptionDict(value=str(month), label=label)
    for month, label in enumerate(
        (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May / Maj",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct / Okt",
            "Nov",
            "Dec",
        ),
        start=1,
    )
]

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(
            CONF_COGNITO_CLIENT_ID, default=DEFAULT_COGNITO_CLIENT_ID
        ): vol.All(str, vol.Length(min=1)),
        vol.Optional(CONF_OWNER_USERNAME): str,
        vol.Optional(CONF_OWNER_PASSWORD): PASSWORD_SELECTOR,
        vol.Optional(
            CONF_OWNER_COGNITO_CLIENT_ID, default=DEFAULT_COGNITO_CLIENT_ID
        ): vol.All(str, vol.Length(min=1)),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
        ),
    }
)


class GaroEntityOwnerAuthError(GaroEntityAuthError):
    """The optional Owner account could not authenticate."""


class GaroEntityOwnerPermissionError(GaroEntityPermissionError):
    """The optional Owner account lacks Owner API access."""


class GaroEntityOwnerStationMismatch(Exception):
    """The Owner and EVDriver accounts do not share a charging station."""


class GaroEntityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle GARO Entity setup."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> GaroEntityOptionsFlow:
        return GaroEntityOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input = _normalize_optional_account(user_input)
                station_count = await _validate_accounts(self.hass, user_input)
            except GaroEntityOwnerAuthError as err:
                _LOGGER.warning("GARO Owner sign-in failed: %s", err)
                errors["base"] = "invalid_owner_auth"
            except GaroEntityOwnerPermissionError as err:
                _LOGGER.warning("GARO Owner permission check failed: %s", err)
                errors["base"] = "owner_permissions"
            except GaroEntityOwnerStationMismatch:
                errors["base"] = "owner_station_mismatch"
            except GaroEntityAuthError as err:
                _LOGGER.warning("GARO EVDriver sign-in failed: %s", err)
                errors["base"] = "invalid_auth"
            except GaroEntityPermissionError as err:
                _LOGGER.warning("GARO EVDriver permission check failed: %s", err)
                errors["base"] = "insufficient_permissions"
            except GaroEntityConnectionError as err:
                _LOGGER.warning("GARO connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "owner_incomplete"
            except Exception:
                _LOGGER.exception("Unexpected GARO setup error")
                errors["base"] = "unknown"
            else:
                if station_count == 0:
                    errors["base"] = "no_stations"
                else:
                    await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"GARO Entity ({user_input[CONF_USERNAME]})",
                        data=user_input,
                    )
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add, replace or remove the cloud accounts without losing entities."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            try:
                user_input = _normalize_optional_account(user_input)
                station_count = await _validate_accounts(self.hass, user_input)
            except GaroEntityOwnerAuthError as err:
                _LOGGER.warning("GARO Owner sign-in failed: %s", err)
                errors["base"] = "invalid_owner_auth"
            except GaroEntityOwnerPermissionError as err:
                _LOGGER.warning("GARO Owner permission check failed: %s", err)
                errors["base"] = "owner_permissions"
            except GaroEntityOwnerStationMismatch:
                errors["base"] = "owner_station_mismatch"
            except GaroEntityAuthError as err:
                _LOGGER.warning("GARO EVDriver sign-in failed: %s", err)
                errors["base"] = "invalid_auth"
            except GaroEntityPermissionError as err:
                _LOGGER.warning("GARO EVDriver permission check failed: %s", err)
                errors["base"] = "insufficient_permissions"
            except GaroEntityConnectionError as err:
                _LOGGER.warning("GARO connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "owner_incomplete"
            except Exception:
                _LOGGER.exception("Unexpected GARO reconfiguration error")
                errors["base"] = "unknown"
            else:
                if station_count == 0:
                    errors["base"] = "no_stations"
                else:
                    await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        entry,
                        data=user_input,
                        title=f"GARO Entity ({user_input[CONF_USERNAME]})",
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, entry.data),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._reauth_entry is not None:
            try:
                data = _normalize_optional_account(
                    {**self._reauth_entry.data, **user_input}
                )
                await _validate_accounts(self.hass, data)
            except GaroEntityOwnerAuthError as err:
                _LOGGER.warning("GARO Owner reauthentication failed: %s", err)
                errors["base"] = "invalid_owner_auth"
            except GaroEntityOwnerPermissionError as err:
                _LOGGER.warning("GARO Owner permission check failed: %s", err)
                errors["base"] = "owner_permissions"
            except GaroEntityOwnerStationMismatch:
                errors["base"] = "owner_station_mismatch"
            except GaroEntityAuthError as err:
                _LOGGER.warning("GARO EVDriver reauthentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except GaroEntityPermissionError as err:
                _LOGGER.warning("GARO API permission check failed: %s", err)
                errors["base"] = "insufficient_permissions"
            except GaroEntityConnectionError as err:
                _LOGGER.warning("GARO connection test failed: %s", err)
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "owner_incomplete"
            except Exception:
                _LOGGER.exception("Unexpected GARO reauthentication error")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry, data=data
                )

        current = self._reauth_entry.data if self._reauth_entry else {}
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_reauth_schema(current),
            errors=errors,
        )


class GaroEntityOptionsFlow(config_entries.OptionsFlowWithReload):
    """Configure the optional local API and current-limit schedule."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_local_options(self.hass, user_input)
            except ValueError:
                errors["base"] = "local_incomplete"
            except GaroEntityLocalError as err:
                _LOGGER.warning("GARO local connection test failed: %s", err)
                errors["base"] = "cannot_connect_local"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.config_entry.options),
            errors=errors,
        )


def _reauth_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(
                CONF_COGNITO_CLIENT_ID,
                default=current.get(
                    CONF_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID
                ),
            ): vol.All(str, vol.Length(min=1)),
            vol.Optional(
                CONF_OWNER_USERNAME,
                default=current.get(CONF_OWNER_USERNAME, ""),
            ): str,
            vol.Optional(CONF_OWNER_PASSWORD): PASSWORD_SELECTOR,
            vol.Optional(
                CONF_OWNER_COGNITO_CLIENT_ID,
                default=current.get(
                    CONF_OWNER_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID
                ),
            ): vol.All(str, vol.Length(min=1)),
        }
    )


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LOCAL_ENABLED,
                default=options.get(CONF_LOCAL_ENABLED, False),
            ): bool,
            vol.Optional(
                CONF_LOCAL_HOST,
                default=options.get(CONF_LOCAL_HOST, ""),
            ): str,
            vol.Optional(
                CONF_LOCAL_USERNAME,
                default=options.get(CONF_LOCAL_USERNAME, ""),
            ): str,
            vol.Optional(
                CONF_LOCAL_PASSWORD,
                default=options.get(CONF_LOCAL_PASSWORD, ""),
            ): PASSWORD_SELECTOR,
            vol.Required(
                CONF_LOCAL_VERIFY_SSL,
                default=options.get(
                    CONF_LOCAL_VERIFY_SSL, DEFAULT_LOCAL_VERIFY_SSL
                ),
            ): bool,
            vol.Required(
                CONF_SCHEDULE_ENABLED,
                default=options.get(CONF_SCHEDULE_ENABLED, False),
            ): bool,
            vol.Required(
                CONF_SCHEDULE_DEFAULT_LIMIT,
                default=options.get(
                    CONF_SCHEDULE_DEFAULT_LIMIT,
                    DEFAULT_SCHEDULE_DEFAULT_LIMIT,
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=LOCAL_MIN_CURRENT, max=LOCAL_MAX_CURRENT),
            ),
            vol.Required(
                CONF_SCHEDULE_PEAK_LIMIT,
                default=options.get(
                    CONF_SCHEDULE_PEAK_LIMIT, DEFAULT_SCHEDULE_PEAK_LIMIT
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=LOCAL_MIN_CURRENT, max=LOCAL_MAX_CURRENT),
            ),
            vol.Required(
                CONF_SCHEDULE_START,
                default=options.get(CONF_SCHEDULE_START, DEFAULT_SCHEDULE_START),
            ): TimeSelector(),
            vol.Required(
                CONF_SCHEDULE_END,
                default=options.get(CONF_SCHEDULE_END, DEFAULT_SCHEDULE_END),
            ): TimeSelector(),
            vol.Required(
                CONF_SCHEDULE_WEEKDAYS,
                default=options.get(
                    CONF_SCHEDULE_WEEKDAYS, DEFAULT_SCHEDULE_WEEKDAYS
                ),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=WEEKDAY_OPTIONS,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_SCHEDULE_MONTHS,
                default=options.get(
                    CONF_SCHEDULE_MONTHS, DEFAULT_SCHEDULE_MONTHS
                ),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=MONTH_OPTIONS,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _normalize_optional_account(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    owner_username = str(normalized.get(CONF_OWNER_USERNAME, "")).strip()
    owner_password = str(normalized.get(CONF_OWNER_PASSWORD, "")).strip()
    if bool(owner_username) != bool(owner_password):
        raise ValueError("Both Owner username and password are required")
    if not owner_username:
        normalized.pop(CONF_OWNER_USERNAME, None)
        normalized.pop(CONF_OWNER_PASSWORD, None)
    return normalized


async def _validate_accounts(hass: HomeAssistant, data: dict[str, Any]) -> int:
    session = async_get_clientsession(hass)
    driver_api = GaroEntityAPI(
        session=session,
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        cognito_client_id=data.get(
            CONF_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID
        ),
    )
    driver_stations = await driver_api.async_get_charging_stations(("EVDriver",))
    if not driver_stations:
        return 0

    if owner_username := data.get(CONF_OWNER_USERNAME):
        owner_api = GaroEntityAPI(
            session=session,
            username=owner_username,
            password=data[CONF_OWNER_PASSWORD],
            cognito_client_id=data.get(
                CONF_OWNER_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID
            ),
        )
        try:
            owner_stations = await owner_api.async_get_charging_stations(("Owner",))
        except GaroEntityAuthError as err:
            raise GaroEntityOwnerAuthError(str(err)) from err
        except GaroEntityPermissionError as err:
            raise GaroEntityOwnerPermissionError(str(err)) from err

        driver_ids = {
            identifier
            for station in driver_stations
            if (identifier := station_identifier(station)) is not None
        }
        owner_ids = {
            identifier
            for station in owner_stations
            if (identifier := station_identifier(station)) is not None
        }
        if not driver_ids.intersection(owner_ids):
            raise GaroEntityOwnerStationMismatch

    return len(driver_stations)


async def _validate_local_options(
    hass: HomeAssistant, options: dict[str, Any]
) -> None:
    if not options.get(CONF_LOCAL_ENABLED, False):
        return
    required = (CONF_LOCAL_HOST, CONF_LOCAL_USERNAME, CONF_LOCAL_PASSWORD)
    if any(not str(options.get(key, "")).strip() for key in required):
        raise ValueError("Local host, username and password are required")
    api = GaroEntityLocalAPI(
        async_get_clientsession(hass),
        options[CONF_LOCAL_HOST],
        options[CONF_LOCAL_USERNAME],
        options[CONF_LOCAL_PASSWORD],
        bool(options.get(CONF_LOCAL_VERIFY_SSL, DEFAULT_LOCAL_VERIFY_SSL)),
    )
    await api.async_get_limit()
