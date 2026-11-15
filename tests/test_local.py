"""Unit tests for local GARO parsing and scheduling."""

from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest

COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "garo_entity"
PACKAGE_NAME = "garo_entity_local_test"


def _load_component_module(name: str) -> types.ModuleType:
    module_name = f"{PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(
        module_name, COMPONENT_PATH / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = package
const = _load_component_module("const")
local_api = _load_component_module("local_api")
schedule = _load_component_module("schedule")


class LocalMeterTests(unittest.TestCase):
    def test_phase_current_power_estimate(self) -> None:
        payload = [
            {
                "timestamp": "2026-01-05T08:00:00Z",
                "sampledValue": [
                    {"phase": "L1", "value": "10", "unit": "A"},
                    {"phase": "L2", "value": "11", "unit": "A"},
                    {"phase": "L3", "value": "12", "unit": "A"},
                ],
            }
        ]

        result = local_api.parse_energy_status(payload)

        self.assertEqual(result["phase_currents"], {"L1": 10, "L2": 11, "L3": 12})
        self.assertEqual(result["total_power_w"], 7590.0)
        self.assertTrue(result["power_estimated"])

    def test_reported_power_is_preferred(self) -> None:
        payload = [
            {
                "sampledValue": [
                    {
                        "measurand": "Power.Active.Import",
                        "value": "7.2",
                        "unit": "kW",
                    }
                ]
            }
        ]

        result = local_api.parse_energy_status(payload)

        self.assertEqual(result["total_power_w"], 7200.0)
        self.assertFalse(result["power_estimated"])


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.options = {
            const.CONF_SCHEDULE_ENABLED: True,
            const.CONF_SCHEDULE_DEFAULT_LIMIT: 55,
            const.CONF_SCHEDULE_PEAK_LIMIT: 20,
            const.CONF_SCHEDULE_START: "07:00:00",
            const.CONF_SCHEDULE_END: "20:00:00",
            const.CONF_SCHEDULE_WEEKDAYS: ["0", "1", "2", "3", "4"],
            const.CONF_SCHEDULE_MONTHS: ["1", "2", "3", "11", "12"],
        }

    def test_winter_weekday_peak_period(self) -> None:
        self.assertEqual(
            schedule.scheduled_limit(self.options, datetime(2026, 1, 5, 8)),
            (20, True),
        )

    def test_weekend_and_summer_use_standard_limit(self) -> None:
        self.assertEqual(
            schedule.scheduled_limit(self.options, datetime(2026, 1, 10, 8)),
            (55, False),
        )
        self.assertEqual(
            schedule.scheduled_limit(self.options, datetime(2026, 6, 8, 8)),
            (55, False),
        )

    def test_overnight_rule_uses_previous_day(self) -> None:
        self.options[const.CONF_SCHEDULE_START] = "22:00:00"
        self.options[const.CONF_SCHEDULE_END] = "06:00:00"
        self.options[const.CONF_SCHEDULE_WEEKDAYS] = ["4"]

        self.assertEqual(
            schedule.scheduled_limit(self.options, datetime(2026, 1, 10, 1)),
            (20, True),
        )


if __name__ == "__main__":
    unittest.main()
