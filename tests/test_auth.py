"""Unit tests for the direct AWS Cognito authentication client."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from typing import Any

COMPONENT_PATH = (
    Path(__file__).parents[1] / "custom_components" / "garo_entity"
)
PACKAGE_NAME = "garo_entity_auth_test"


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


try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        """Stand-in used when aiohttp is not installed in the unit-test runtime."""

    class ContentTypeError(ClientError):
        """Stand-in for aiohttp.ContentTypeError."""

    class ClientTimeout:
        def __init__(self, *, total: int) -> None:
            self.total = total

    aiohttp.ClientError = ClientError
    aiohttp.ContentTypeError = ContentTypeError
    aiohttp.ClientTimeout = ClientTimeout
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = package
_load_component_module("const")
_load_component_module("parsers")
api = _load_component_module("api")


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._text = json.dumps(payload)

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def text(self) -> str:
        return self._text


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.last_post: dict[str, Any] | None = None

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.last_post = {"url": url, **kwargs}
        return self.response


class CognitoAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_password_auth_uses_configured_client_id(self) -> None:
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "AuthenticationResult": {
                        "AccessToken": "test-token",
                        "RefreshToken": "test-refresh",
                        "ExpiresIn": 3600,
                    }
                },
            )
        )
        client = api.GaroEntityAPI(
            session=session,
            username="user@example.com",
            password="secret",
            cognito_client_id="working-client-id",
        )

        await client._authenticate()

        assert session.last_post is not None
        self.assertEqual(
            session.last_post["url"], "https://cognito-idp.eu-west-1.amazonaws.com/"
        )
        self.assertEqual(session.last_post["json"]["ClientId"], "working-client-id")
        self.assertEqual(
            session.last_post["json"]["AuthFlow"], "USER_PASSWORD_AUTH"
        )
        self.assertEqual(client._access_token, "test-token")

    async def test_not_authorized_error_is_reported_safely(self) -> None:
        session = FakeSession(
            FakeResponse(400, {"__type": "NotAuthorizedException"})
        )
        client = api.GaroEntityAPI(
            session=session,
            username="user@example.com",
            password="wrong",
        )

        with self.assertRaisesRegex(
            api.GaroEntityAuthError, "NotAuthorizedException"
        ):
            await client._authenticate()

    async def test_non_object_cognito_response_is_connection_error(self) -> None:
        client = api.GaroEntityAPI(
            session=FakeSession(FakeResponse(200, [])),
            username="user@example.com",
            password="secret",
        )

        with self.assertRaises(api.GaroEntityConnectionError):
            await client._authenticate()


if __name__ == "__main__":
    unittest.main()
