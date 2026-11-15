"""Async client for the GARO Entity CSMS End User API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any

import aiohttp

from .const import (
    DEFAULT_API_BASE_URL,
    DEFAULT_COGNITO_CLIENT_ID,
    DEFAULT_COGNITO_REGION,
)
from .parsers import station_identifier

COGNITO_AUTH_ERRORS = {
    "InvalidParameterException",
    "NotAuthorizedException",
    "PasswordResetRequiredException",
    "ResourceNotFoundException",
    "UserNotConfirmedException",
    "UserNotFoundException",
}


class GaroEntityError(Exception):
    """Base GARO API exception."""


class GaroEntityAuthError(GaroEntityError):
    """Authentication failed."""


class GaroEntityPermissionError(GaroEntityError):
    """The account is authenticated but lacks permission for an operation."""


class GaroEntityConnectionError(GaroEntityError):
    """The GARO API could not be reached or returned an error."""


class GaroEntityCommandError(GaroEntityError):
    """A remote command was rejected."""


class GaroEntityAPI:
    """Async wrapper around GARO's Cognito-backed end-user API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        cognito_client_id: str = DEFAULT_COGNITO_CLIENT_ID,
        cognito_region: str = DEFAULT_COGNITO_REGION,
        api_base_url: str = DEFAULT_API_BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._client_id = cognito_client_id
        self._region = cognito_region
        self._base_url = api_base_url.rstrip("/")
        self._cognito_url = f"https://cognito-idp.{self._region}.amazonaws.com/"
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: datetime | None = None
        self._auth_lock = asyncio.Lock()

    async def _authenticate(self, *, refresh: bool = False) -> None:
        async with self._auth_lock:
            if self._token_is_valid():
                return
            if refresh and self._refresh_token:
                try:
                    response = await self._initiate_auth(
                        "REFRESH_TOKEN_AUTH",
                        {"REFRESH_TOKEN": self._refresh_token},
                    )
                except GaroEntityAuthError:
                    # Refresh tokens can be revoked or expire. A normal sign-in
                    # is still worth trying before Home Assistant requests reauth.
                    self._refresh_token = None
                    response = await self._password_auth()
            else:
                response = await self._password_auth()

            auth = response.get("AuthenticationResult", {})
            token = auth.get("AccessToken")
            if not token:
                raise GaroEntityAuthError("Cognito did not return an access token")
            self._access_token = token
            self._refresh_token = auth.get("RefreshToken", self._refresh_token)
            self._expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(auth.get("ExpiresIn", 3600))
            )

    async def _password_auth(self) -> dict[str, Any]:
        """Sign in with the GARO account through the Cognito app client."""
        return await self._initiate_auth(
            "USER_PASSWORD_AUTH",
            {
                "USERNAME": self._username,
                "PASSWORD": self._password,
            },
        )

    async def _initiate_auth(
        self, auth_flow: str, auth_parameters: dict[str, str]
    ) -> dict[str, Any]:
        """Call Cognito directly without a blocking AWS SDK dependency."""
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        }
        body = {
            "AuthFlow": auth_flow,
            "ClientId": self._client_id,
            "AuthParameters": auth_parameters,
        }
        try:
            async with self._session.post(
                self._cognito_url,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as response:
                response_text = await response.text()
                try:
                    payload = json.loads(response_text) if response_text else {}
                except ValueError as err:
                    raise GaroEntityConnectionError(
                        "AWS Cognito returned an invalid response"
                    ) from err
                if not isinstance(payload, dict):
                    raise GaroEntityConnectionError(
                        "AWS Cognito returned an invalid response"
                    )
                if response.status >= 400:
                    error_code = str(
                        payload.get("__type")
                        or payload.get("code")
                        or f"HTTP {response.status}"
                    ).rsplit("#", maxsplit=1)[-1]
                    if error_code in COGNITO_AUTH_ERRORS or response.status in {
                        401,
                        403,
                    }:
                        raise GaroEntityAuthError(
                            f"Cognito authentication failed: {error_code}"
                        )
                    raise GaroEntityConnectionError(
                        f"AWS Cognito returned {error_code}"
                    )
        except GaroEntityError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GaroEntityConnectionError(
                "Could not contact AWS Cognito"
            ) from err

        if challenge := payload.get("ChallengeName"):
            raise GaroEntityAuthError(
                f"Cognito requires an unsupported sign-in challenge: {challenge}"
            )
        return payload

    def _token_is_valid(self) -> bool:
        return bool(
            self._access_token
            and self._expires_at
            and datetime.now(timezone.utc) < self._expires_at - timedelta(minutes=2)
        )

    async def _ensure_token(self) -> None:
        if not self._token_is_valid():
            await self._authenticate(refresh=bool(self._refresh_token))

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | list[Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        await self._ensure_token()
        url = f"{self._base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=aiohttp.ClientTimeout(total=35),
            ) as response:
                response_text = await response.text()
                if response.status == 401 and retry_auth:
                    self._access_token = None
                    self._expires_at = None
                    await self._authenticate(refresh=bool(self._refresh_token))
                    return await self._request(
                        method,
                        endpoint,
                        params=params,
                        json_data=json_data,
                        retry_auth=False,
                    )
                if response.status == 401:
                    raise GaroEntityAuthError(
                        f"GARO API rejected the credentials ({response.status})"
                    )
                if response.status == 403:
                    raise GaroEntityPermissionError(
                        f"The GARO account lacks permission for {endpoint}"
                    )
                if response.status >= 400:
                    raise GaroEntityConnectionError(
                        f"GARO API returned HTTP {response.status} for {endpoint}"
                    )
                if not response_text.strip():
                    return {}
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    return {"raw_response": response_text}
        except GaroEntityError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GaroEntityConnectionError(
                f"Could not reach GARO API endpoint {endpoint}"
            ) from err

    async def async_get_charging_stations(
        self, contexts: tuple[str, ...] = ("EVDriver", "Owner")
    ) -> list[dict[str, Any]]:
        """Discover stations for the requested roles, preferring Owner metadata."""
        discovered: dict[str, dict[str, Any]] = {}
        last_error: GaroEntityError | None = None
        successful_context = False
        for context in contexts:
            try:
                response = await self._request(
                    "GET",
                    "/charging-stations",
                    params={
                        "context": context,
                        "include_relationships": "true",
                        "limit": 20,
                    },
                )
            except GaroEntityError as err:
                last_error = err
                continue

            successful_context = True

            items = (
                response.get("items", []) if isinstance(response, dict) else response
            )
            if not isinstance(items, list):
                continue
            for raw in items:
                if not isinstance(raw, dict) or raw.get("load_interface") is True:
                    continue
                identifier = station_identifier(raw)
                if not identifier:
                    continue
                station = discovered.setdefault(identifier, dict(raw))
                contexts = set(station.get("_garo_contexts", []))
                contexts.add(context)
                if context == "Owner":
                    station.update(raw)
                station["_garo_contexts"] = sorted(contexts)
                station["_garo_context"] = (
                    "Owner" if "Owner" in contexts else "EVDriver"
                )

        if not discovered and not successful_context and last_error:
            raise last_error
        return list(discovered.values())

    async def async_get_connector_status(self, station_id: str) -> Any:
        return await self._request(
            "GET", f"/charging-stations/{station_id}/connector-status"
        )

    async def async_get_transactions(
        self, station_id: str, context: str, connector_id: int = 1
    ) -> Any:
        return await self._request(
            "GET",
            "/transactions",
            params={
                "context": context,
                "charging_station_id": station_id,
                "connector_id": connector_id,
                "limit": 20,
            },
        )

    async def async_get_latest_meter_values(
        self, station_id: str, context: str, connector_id: int = 1
    ) -> Any:
        return await self._request(
            "GET",
            "/meter-values/latest",
            params={
                "context": context,
                "charging_station_id": station_id,
                "connector_id": connector_id,
                "time_ago": 300,
            },
        )

    async def async_get_configuration(self, station_id: str, keys: list[str]) -> Any:
        return await self._request(
            "PUT",
            f"/actions/get-configuration/{station_id}",
            params={"response_required": "true", "through_proxy": "true"},
            json_data={"key": keys},
        )

    async def async_set_configuration(
        self, station_id: str, key: str, value: str | float
    ) -> Any:
        response = await self._request(
            "PUT",
            f"/actions/change-configuration/{station_id}",
            params={"response_required": "true", "through_proxy": "false"},
            json_data={"configuration_variables": [{"key": key, "value": str(value)}]},
        )
        self._raise_if_rejected(response, key)
        return response

    async def async_remote_start(self, station_id: str, connector_id: int = 1) -> Any:
        response = await self._request(
            "PUT",
            f"/actions/remote-start-transaction/{station_id}",
            params={"response_required": "false"},
            json_data={"connector_id": connector_id},
        )
        self._raise_if_rejected(response)
        return response

    async def async_remote_stop(self, station_id: str, transaction_id: int) -> Any:
        response = await self._request(
            "PUT",
            f"/actions/remote-stop-transaction/{station_id}",
            params={"response_required": "false"},
            json_data={"transaction_id": transaction_id},
        )
        self._raise_if_rejected(response)
        return response

    @staticmethod
    def _raise_if_rejected(response: Any, key: str | None = None) -> None:
        if not isinstance(response, dict):
            return
        status: Any = response.get("status")
        if key and isinstance(status, dict):
            status = status.get(key)
        if isinstance(status, str) and status.lower().replace("_", "") in {
            "rejected",
            "failed",
            "notsupported",
            "error",
        }:
            raise GaroEntityCommandError(f"GARO rejected the command: {status}")
