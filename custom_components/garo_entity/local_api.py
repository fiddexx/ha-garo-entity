"""Async client for the local GARO Entity controller API."""

from __future__ import annotations

import asyncio
import math
from urllib.parse import urlsplit
from typing import Any

import aiohttp

LOCAL_LIMIT_GROUP = "ocpp16"
LOCAL_LIMIT_PARAMETER = "GaroConnectionGroupMaxCurrent"


class GaroEntityLocalError(Exception):
    """The local GARO controller could not be reached or parsed."""


class GaroEntityLocalAPI:
    """Read and control a GARO charger or load-interface over the LAN."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool,
    ) -> None:
        clean_host = host.strip().rstrip("/")
        parsed = urlsplit(clean_host if "://" in clean_host else f"https://{clean_host}")
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment):
            raise ValueError("Enter a host address without credentials or an API path")
        port = parsed.port  # Also validates malformed port numbers.
        hostname = parsed.hostname.lower()
        if ":" in hostname:
            hostname = f"[{hostname}]"
        default_port = 443 if parsed.scheme == "https" else 80
        suffix = f":{port}" if port and port != default_port else ""
        self.base_url = f"{parsed.scheme}://{hostname}{suffix}"
        self._session = session
        self._auth = aiohttp.BasicAuth(username, password)
        self._verify_ssl = verify_ssl

    async def async_get_limit(self) -> float:
        """Return GaroConnectionGroupMaxCurrent in ampere."""
        payload = await self._request(
            "GET",
            "/config/config-parameter",
            params={
                "group": LOCAL_LIMIT_GROUP,
                "parameter": LOCAL_LIMIT_PARAMETER,
            },
        )
        value = payload.get("value") if isinstance(payload, dict) else None
        try:
            result = float(value)
            if not math.isfinite(result):
                raise ValueError("Non-finite current")
            return result
        except (TypeError, ValueError) as err:
            raise GaroEntityLocalError(
                "The local controller returned an invalid current limit"
            ) from err

    async def async_set_limit(self, value: int | float) -> None:
        """Set GaroConnectionGroupMaxCurrent in ampere."""
        if not math.isfinite(value) or not 6 <= value <= 63 or int(value) != value:
            raise GaroEntityLocalError("Group current must be an integer between 6 and 63 A")
        await self._request(
            "PUT",
            "/config/config-parameter",
            form_data={
                "group": LOCAL_LIMIT_GROUP,
                "parameter": LOCAL_LIMIT_PARAMETER,
                "value": str(int(value)),
            },
        )

    async def async_get_energy_status(self) -> dict[str, Any]:
        """Return phase currents and total power from the local meter."""
        payload = await self._request("GET", "/status/energy-meter")
        return parse_energy_status(payload)

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        form_data: dict[str, str] | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self.base_url}{endpoint}",
                params=params,
                data=form_data,
                auth=self._auth,
                ssl=self._verify_ssl,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response_text = await response.text()
                if response.status in {401, 403}:
                    raise GaroEntityLocalError(
                        "The local controller rejected its username or password"
                    )
                if response.status >= 400:
                    raise GaroEntityLocalError(
                        f"The local controller returned HTTP {response.status}"
                    )
                if not response_text.strip():
                    return {}
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    if method == "PUT":
                        return {"raw_response": response_text}
                    raise GaroEntityLocalError(
                        "The local controller returned an invalid response"
                    ) from err
        except GaroEntityLocalError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GaroEntityLocalError(
                "Could not contact the local GARO controller"
            ) from err


def parse_energy_status(payload: Any) -> dict[str, Any]:
    """Extract phase current and power from GARO's local meter payload."""
    frames = payload if isinstance(payload, list) else [payload]
    samples: list[dict[str, Any]] = []
    timestamp: str | None = None
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        timestamp = (
            str(frame.get("timestamp") or frame.get("time") or timestamp or "")
            or None
        )
        values = frame.get("sampledValue") or frame.get("sampled_value") or []
        if isinstance(values, list):
            samples.extend(item for item in values if isinstance(item, dict))

    phase_currents: dict[str, float] = {}
    powers: dict[str, float] = {}
    for sample in samples:
        try:
            value = float(sample.get("value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        phase = str(sample.get("phase") or "")
        measurand = str(sample.get("measurand") or sample.get("measure_name") or "")
        unit = str(sample.get("unit") or "").lower()

        if phase in {"L1", "L2", "L3"} and (
            measurand.lower() == "current.import" or (not measurand and unit in {"", "a"})
        ):
            phase_currents[phase] = value
        if measurand.lower() == "power.active.import" or (not measurand and unit in {"w", "kw"}):
            powers[phase] = value * (1000 if unit == "kw" else 1)

    has_reported_power = bool(powers)
    total_power_w = powers.get("") if "" in powers else sum(powers.values()) if powers else (
        sum(phase_currents.values()) * 230.0 if phase_currents else None
    )
    return {
        "phase_currents": phase_currents,
        "total_power_w": round(total_power_w, 1) if total_power_w is not None else None,
        "power_estimated": not has_reported_power,
        "timestamp": timestamp,
    }
