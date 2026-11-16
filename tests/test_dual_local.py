"""Regression tests for endpoint isolation and credential migration.

The HA scheduler is stubbed; these exercise the production polling methods with
fake endpoints, without connecting to or controlling any real GARO device.
"""
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_local import const, local_api, _load_component_module

options_module = _load_component_module('local_options')

class FakeCoordinator:
    def __init__(self, *args, **kwargs):
        self.data = None
        self.last_update_success = True

ha_modules = {}
for name in ('homeassistant', 'homeassistant.helpers',
             'homeassistant.helpers.update_coordinator', 'homeassistant.util'):
    ha_modules[name] = types.ModuleType(name)
ha_modules['homeassistant.helpers.update_coordinator'].DataUpdateCoordinator = FakeCoordinator
ha_modules['homeassistant.util'].dt = types.SimpleNamespace(
    now=lambda: datetime(2026, 11, 16, 10),
    utcnow=lambda: datetime.now(timezone.utc))
with patch.dict(sys.modules, ha_modules):
    local_coordinator = _load_component_module('local_coordinator')

class DualEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entry = types.SimpleNamespace(options={
            const.CONF_SCHEDULE_ENABLED: True,
            const.CONF_LOCAL_IS_BALANCER: True,
            const.CONF_SCHEDULE_DEFAULT_LIMIT: 55,
            const.CONF_SCHEDULE_PEAK_LIMIT: 20,
        })

    def coordinator(self, role, meter=1000, limit=55):
        api = types.SimpleNamespace(
            async_get_energy_status=AsyncMock(return_value={'total_power_w': meter}),
            async_get_limit=AsyncMock(return_value=limit),
            async_set_limit=AsyncMock())
        return local_coordinator.GaroLocalCoordinator(None, self.entry, api, role, 60)

    async def test_charger_is_read_only_even_with_schedule_enabled(self):
        charger = self.coordinator('charger', 2300)
        data = await charger._async_update_data()
        self.assertEqual(data['total_power_w'], 2300)
        charger.local_api.async_get_limit.assert_not_awaited()
        charger.local_api.async_set_limit.assert_not_awaited()

    async def test_only_balancer_writes_and_readback_confirms(self):
        charger = self.coordinator('charger', 2300)
        balancer = self.coordinator('balancer', 7000)
        balancer.local_api.async_get_limit.side_effect = [55, 20]
        c, b = await asyncio.gather(charger._async_update_data(), balancer._async_update_data())
        self.assertEqual(c['total_power_w'], 2300)
        self.assertEqual(b['total_power_w'], 7000)
        self.assertEqual(b['current_limit_a'], 20)
        self.assertIsNotNone(b['last_schedule_change'])
        balancer.local_api.async_set_limit.assert_awaited_once_with(20)
        charger.local_api.async_set_limit.assert_not_awaited()

    async def test_legacy_endpoint_cannot_write_until_role_confirmed(self):
        self.entry.options.pop(const.CONF_LOCAL_IS_BALANCER)
        balancer = self.coordinator('balancer')
        data = await balancer._async_update_data()
        self.assertFalse(data['schedule_enabled'])
        balancer.local_api.async_set_limit.assert_not_awaited()

    async def test_failed_limit_read_prevents_writing_and_clears_stale_limit(self):
        balancer = self.coordinator('balancer')
        balancer.data = {'current_limit_a': 55}
        balancer.local_api.async_get_limit.side_effect = local_api.GaroEntityLocalError('offline')
        data = await balancer._async_update_data()
        self.assertTrue(data['meter_available'])
        self.assertFalse(data['limit_available'])
        self.assertNotIn('current_limit_a', data)
        balancer.local_api.async_set_limit.assert_not_awaited()

    async def test_failed_meter_read_does_not_show_old_power(self):
        balancer = self.coordinator('balancer', limit=20)
        balancer.data = {'total_power_w': 9000}
        balancer.local_api.async_get_energy_status.side_effect = local_api.GaroEntityLocalError('offline')
        data = await balancer._async_update_data()
        self.assertFalse(data['meter_available'])
        self.assertTrue(data['limit_available'])
        self.assertNotIn('total_power_w', data)

    async def test_balancer_failure_does_not_stop_charger(self):
        charger = self.coordinator('charger')
        balancer = self.coordinator('balancer')
        balancer.local_api.async_get_limit.side_effect = local_api.GaroEntityLocalError('offline')
        balancer.local_api.async_get_energy_status.side_effect = local_api.GaroEntityLocalError('offline')
        c, b = await asyncio.gather(charger._async_update_data(), balancer._async_update_data())
        self.assertTrue(c['available'])
        self.assertFalse(b['available'])

    async def test_write_response_without_changed_value_is_not_success(self):
        balancer = self.coordinator('balancer', limit=55)
        data = await balancer._async_update_data()
        self.assertEqual(data['current_limit_a'], 55)
        self.assertIsNone(data['last_schedule_change'])

    async def test_no_write_when_already_at_target(self):
        balancer = self.coordinator('balancer', limit=20)
        await balancer._async_update_data()
        balancer.local_api.async_set_limit.assert_not_awaited()

class CredentialTests(unittest.TestCase):
    def test_legacy_credentials_migrate_without_mutating_input(self):
        old = {const.CONF_LOCAL_PASSWORD: 'fixture', const.CONF_LOCAL_USERNAME: 'example',
               const.CONF_LOCAL_HOST: 'balance.example', const.CONF_SCHEDULE_ENABLED: True}
        data, options = options_module.migrate_local_credentials({}, old)
        self.assertEqual(data[const.CONF_LOCAL_PASSWORD], 'fixture')
        self.assertNotIn(const.CONF_LOCAL_PASSWORD, options)
        self.assertEqual(options[const.CONF_LOCAL_HOST], 'balance.example')
        self.assertIn(const.CONF_LOCAL_PASSWORD, old)
        self.assertNotIn(const.CONF_LOCAL_IS_BALANCER, options)

    def test_blank_password_keeps_existing_and_options_never_store_credentials(self):
        data, options = options_module.save_local_options(
            {const.CONF_CHARGER_PASSWORD: 'fixture'}, {},
            {const.CONF_CHARGER_PASSWORD: '', const.CONF_CHARGER_ENABLED: True})
        self.assertEqual(data[const.CONF_CHARGER_PASSWORD], 'fixture')
        self.assertNotIn(const.CONF_CHARGER_PASSWORD, options)

    def test_changing_charger_password_does_not_change_balancer(self):
        data, options = options_module.save_local_options(
            {const.CONF_LOCAL_PASSWORD: 'balance-fixture'}, {},
            {const.CONF_CHARGER_PASSWORD: 'charger-fixture'})
        self.assertEqual(data[const.CONF_LOCAL_PASSWORD], 'balance-fixture')
        self.assertEqual(data[const.CONF_CHARGER_PASSWORD], 'charger-fixture')
        self.assertEqual(options, {})

class LocalAddressTests(unittest.TestCase):
    def api(self, host):
        with patch.object(local_api.aiohttp, 'BasicAuth', create=True, side_effect=lambda *args: args):
            return local_api.GaroEntityLocalAPI(None, host, 'fixture', 'fixture', True)

    def test_normalizes_default_ports_and_hostname(self):
        self.assertEqual(self.api('https://BALANCE.example:443/').base_url,
                         self.api('balance.example').base_url)

    def test_rejects_credentials_and_endpoint_in_address(self):
        for host in ('https://name:secret@balance.example',
                     'https://balance.example/status/energy-meter',
                     'ftp://balance.example'):
            with self.assertRaises(ValueError):
                self.api(host)

class LocalPowerTests(unittest.TestCase):
    def test_aggregate_power_is_not_added_to_phase_power(self):
        data = local_api.parse_energy_status([{'sampledValue': [
            {'measurand': 'Power.Active.Import', 'value': '3000', 'unit': 'W'},
            {'measurand': 'Power.Active.Import', 'phase': 'L1', 'value': '1000', 'unit': 'W'},
            {'measurand': 'Power.Active.Import', 'phase': 'L2', 'value': '1000', 'unit': 'W'},
            {'measurand': 'Power.Active.Import', 'phase': 'L3', 'value': '1000', 'unit': 'W'},
        ]}])
        self.assertEqual(data['total_power_w'], 3000)

    def test_empty_or_nonfinite_meter_does_not_report_zero_power(self):
        for payload in ([], [{'sampledValue': [{'value': 'NaN', 'unit': 'W'}]}]):
            self.assertIsNone(local_api.parse_energy_status(payload)['total_power_w'])

    def test_offered_current_is_not_measured_consumption(self):
        data = local_api.parse_energy_status([{'sampledValue': [
            {'measurand': 'Current.Offered', 'phase': 'L1', 'value': '32', 'unit': 'A'}]}])
        self.assertEqual(data['phase_currents'], {})
        self.assertIsNone(data['total_power_w'])
