"""Constants for the GARO Entity integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "garo_entity"

DEFAULT_COGNITO_CLIENT_ID: Final = "2tbuisnbl1t2a5gc36lhb2b6c3"
DEFAULT_COGNITO_REGION: Final = "eu-west-1"
DEFAULT_API_BASE_URL: Final = "https://end-user-api.prod.garo-next-gen.com"

CONF_COGNITO_CLIENT_ID: Final = "cognito_client_id"
CONF_COGNITO_REGION: Final = "cognito_region"
CONF_API_BASE_URL: Final = "api_base_url"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_OWNER_USERNAME: Final = "owner_username"
CONF_OWNER_PASSWORD: Final = "owner_password"
CONF_OWNER_COGNITO_CLIENT_ID: Final = "owner_cognito_client_id"

CONF_LOCAL_ENABLED: Final = "local_enabled"
CONF_LOCAL_HOST: Final = "local_host"
CONF_LOCAL_USERNAME: Final = "local_username"
CONF_LOCAL_PASSWORD: Final = "local_password"
CONF_LOCAL_VERIFY_SSL: Final = "local_verify_ssl"
CONF_SCHEDULE_ENABLED: Final = "schedule_enabled"
CONF_SCHEDULE_DEFAULT_LIMIT: Final = "schedule_default_limit"
CONF_SCHEDULE_PEAK_LIMIT: Final = "schedule_peak_limit"
CONF_SCHEDULE_START: Final = "schedule_start"
CONF_SCHEDULE_END: Final = "schedule_end"
CONF_SCHEDULE_WEEKDAYS: Final = "schedule_weekdays"
CONF_SCHEDULE_MONTHS: Final = "schedule_months"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 900

DEFAULT_LOCAL_VERIFY_SSL: Final = False
DEFAULT_SCHEDULE_DEFAULT_LIMIT: Final = 55
DEFAULT_SCHEDULE_PEAK_LIMIT: Final = 20
DEFAULT_SCHEDULE_START: Final = "07:00:00"
DEFAULT_SCHEDULE_END: Final = "20:00:00"
DEFAULT_SCHEDULE_WEEKDAYS: Final = ["0", "1", "2", "3", "4"]
DEFAULT_SCHEDULE_MONTHS: Final = ["1", "2", "3", "11", "12"]
LOCAL_MIN_CURRENT: Final = 6
LOCAL_MAX_CURRENT: Final = 63

CONNECTOR_ID: Final = 1
OWNER_MAX_CURRENT_KEY: Final = "GaroOwnerMaxCurrent"

DATA_API: Final = "api"
DATA_OWNER_API: Final = "owner_api"
DATA_LOCAL_API: Final = "local_api"
DATA_COORDINATOR: Final = "coordinator"
