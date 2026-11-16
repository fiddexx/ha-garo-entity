"""Credential storage and endpoint validation shared by setup and options."""
from .const import (
    CONF_LOCAL_USERNAME, CONF_LOCAL_PASSWORD,
    CONF_CHARGER_USERNAME, CONF_CHARGER_PASSWORD,
)

LOCAL_CREDENTIAL_KEYS = (
    CONF_LOCAL_USERNAME, CONF_LOCAL_PASSWORD,
    CONF_CHARGER_USERNAME, CONF_CHARGER_PASSWORD,
)


def migrate_local_credentials(data, options):
    """Move old option credentials to redacted entry data without losing settings."""
    data, options = dict(data), dict(options)
    for key in LOCAL_CREDENTIAL_KEYS:
        if key in options:
            data.setdefault(key, options.pop(key))
    return data, options


def save_local_options(data, previous_options, submitted):
    """Blank password inputs retain existing credentials; options contain no secrets."""
    data, _ = migrate_local_credentials(data, previous_options)
    options = dict(submitted)
    for key in LOCAL_CREDENTIAL_KEYS:
        value = options.pop(key, None)
        if value:
            data[key] = value
    return data, options
