"""Unit tests for API payload parsing."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "garo_entity" / "parsers.py"
)
SPEC = importlib.util.spec_from_file_location("garo_parsers", MODULE_PATH)
assert SPEC and SPEC.loader
parsers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parsers)


class ParserTests(unittest.TestCase):
    def test_completed_transaction_energy_is_kwh(self) -> None:
        transaction = {
            "id": "42",
            "state": "Finished",
            "meter_start": 100_000,
            "meter_stop": 112_345,
            "start_time": "2026-08-19T18:00:00Z",
            "end_time": "2026-08-19T20:00:00Z",
        }
        self.assertEqual(parsers.transaction_energy_kwh(transaction), 12.345)

    def test_active_transaction_uses_current_kwh_register(self) -> None:
        transaction = {
            "id": "43",
            "state": "Started",
            "meter_start": 100_000,
            "start_time": "2026-08-19T20:00:00Z",
        }
        self.assertEqual(
            parsers.transaction_energy_kwh(transaction, 104.25, "kWh"), 4.25
        )

    def test_active_transaction_and_integer_stop_id(self) -> None:
        payload = {
            "items": [
                {
                    "id": "123",
                    "state": "Started",
                    "meter_start": 50,
                    "start_time": "2026-08-19T20:00:00Z",
                },
                {
                    "id": "122",
                    "state": "Finished",
                    "meter_start": 0,
                    "meter_stop": 50,
                    "start_time": "2026-08-19T18:00:00Z",
                },
            ]
        }
        active = parsers.active_transaction(payload)
        self.assertEqual(parsers.transaction_identifier(active), 123)

    def test_connector_and_meter_list_payloads(self) -> None:
        self.assertEqual(
            parsers.connector_status(
                [{"connector_id": 1, "status": "Charging", "limited": False}]
            ),
            "Charging",
        )
        sample = parsers.meter_sample(
            [
                {
                    "measure_name": "Energy.Active.Import.Register",
                    "measure_value": "12.5",
                    "unit": "kWh",
                    "time": "2026-08-19T20:00:00Z",
                }
            ],
            "Energy.Active.Import.Register",
        )
        self.assertEqual(parsers.sample_value(sample), 12.5)
        self.assertEqual(parsers.sample_unit(sample), "kWh")

    def test_configuration_response(self) -> None:
        payload = {"configuration_key": [{"key": "GaroOwnerMaxCurrent", "value": "16"}]}
        self.assertEqual(
            parsers.configuration_value(payload, "GaroOwnerMaxCurrent"), "16"
        )


if __name__ == "__main__":
    unittest.main()
