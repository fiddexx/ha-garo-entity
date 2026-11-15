"""Async client for the local GARO Entity controller API."""

from __future__ import annotations

import asyncio
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
        self.base_url = (
            clean_host
            if clean_host.startswith(("http://", "https://"))
            else f"https://{clean_host}"
        )
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
            return float(value)
        except (TypeError, ValueError) as err:
            raise GaroEntityLocalError(
                "The local controller returned an invalid current limit"
            ) from err

    async def async_set_limit(self, value: int | float) -> None:
        """Set GaroConnectionGroupMaxCurrent in ampere."""
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
    reported_power_w = 0.0
    has_reported_power = False
    for sample in samples:
        try:
            value = float(sample.get("value"))
        except (TypeError, ValueError):
            continue
        phase = str(sample.get("phase") or "")
        measurand = str(sample.get("measurand") or sample.get("measure_name") or "")
        unit = str(sample.get("unit") or "").lower()

        if phase in {"L1", "L2", "L3"} and (
            not measurand or "current" in measurand.lower() or unit == "a"
        ):
            phase_currents[phase] = value
        if "power" in measurand.lower() or unit in {"w", "kw"}:
            reported_power_w += value * (1000 if unit == "kw" else 1)
            has_reported_power = True

    total_power_w = (
        reported_power_w
        if has_reported_power
        else sum(phase_currents.values()) * 230.0
    )
    return {
        "phase_currents": phase_currents,
        "total_power_w": round(total_power_w, 1),
        "power_estimated": not has_reported_power,
        "timestamp": timestamp,
    }
