"""Exercise real switch methods with fake cloud responses and HA entity bases."""
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
from test_local import PACKAGE_NAME, _load_component_module

class Base:
    def __init__(self, coordinator, entry, station_id):
        self.coordinator = coordinator
        self.station_id = station_id
        self.station_data = {}
        self.station = {'_garo_context': 'Owner'}

modules = {}
for name in ('homeassistant', 'homeassistant.components', 'homeassistant.components.switch',
             'homeassistant.config_entries', 'homeassistant.core', 'homeassistant.exceptions',
             'homeassistant.helpers', 'homeassistant.helpers.entity_platform',
             f'{PACKAGE_NAME}.entity', f'{PACKAGE_NAME}.coordinator'):
    modules[name] = types.ModuleType(name)
modules['homeassistant.components.switch'].SwitchEntity = type('SwitchEntity', (), {})
modules['homeassistant.config_entries'].ConfigEntry = object
modules['homeassistant.core'].HomeAssistant = object
modules['homeassistant.exceptions'].HomeAssistantError = RuntimeError
modules['homeassistant.helpers.entity_platform'].AddEntitiesCallback = object
modules[f'{PACKAGE_NAME}.entity'].GaroEntityBase = Base
modules[f'{PACKAGE_NAME}.coordinator'].GaroEntityCoordinator = object
_load_component_module('parsers')
_load_component_module('api')
with patch.dict(sys.modules, modules):
    switch = _load_component_module('switch')

class CloudControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = types.SimpleNamespace(
            async_remote_start=AsyncMock(), async_remote_stop=AsyncMock(),
            async_get_transactions=AsyncMock(return_value=[]))
        self.coordinator = types.SimpleNamespace(async_refresh_after_command=AsyncMock())
        self.entity = switch.GaroChargingSwitch(
            self.coordinator, self.api, types.SimpleNamespace(entry_id='test'), 'station-1')

    async def test_start_uses_cloud_evdriver_client(self):
        await self.entity.async_turn_on()
        self.api.async_remote_start.assert_awaited_once_with('station-1', 1)
        self.coordinator.async_refresh_after_command.assert_awaited_once()

    async def test_stop_lookup_uses_evdriver_even_when_owner_metadata_present(self):
        with self.assertRaises(RuntimeError):
            await self.entity.async_turn_off()
        self.api.async_get_transactions.assert_awaited_once_with('station-1', 'EVDriver', 1)
        self.api.async_remote_stop.assert_not_awaited()
