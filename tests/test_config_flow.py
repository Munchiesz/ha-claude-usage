"""Tests for the Claude Usage config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.claude_usage.config_flow import _async_validate_refresh_token
from custom_components.claude_usage.const import CLIENT_ID

from .conftest import MOCK_TOKEN_RESPONSE, create_mock_response


# --- _async_validate_refresh_token tests ---


@pytest.mark.asyncio
async def test_validate_token_success() -> None:
    """Test successful token validation."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(200, MOCK_TOKEN_RESPONSE))

    data, error = await _async_validate_refresh_token(session, "good-token")

    assert data == MOCK_TOKEN_RESPONSE
    assert error == ""


@pytest.mark.asyncio
async def test_validate_token_invalid() -> None:
    """Test invalid token returns invalid_token error."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(401))

    data, error = await _async_validate_refresh_token(session, "bad-token")

    assert data is None
    assert error == "invalid_token"


@pytest.mark.asyncio
async def test_validate_token_server_error_500() -> None:
    """Test 500 server error returns cannot_connect, not invalid_token."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(500))

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_server_error_502() -> None:
    """Test 502 returns cannot_connect."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(502))

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_403_is_invalid() -> None:
    """Test 403 returns invalid_token (client error, not server error)."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(403))

    data, error = await _async_validate_refresh_token(session, "forbidden-token")

    assert data is None
    assert error == "invalid_token"


@pytest.mark.asyncio
async def test_validate_token_connection_error() -> None:
    """Test network error returns cannot_connect."""
    import aiohttp

    session = MagicMock()
    resp = AsyncMock()
    resp.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("connection failed"))
    session.post = MagicMock(return_value=resp)

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_timeout() -> None:
    """Test timeout returns cannot_connect."""
    session = MagicMock()
    resp = AsyncMock()
    resp.__aenter__ = AsyncMock(side_effect=TimeoutError)
    session.post = MagicMock(return_value=resp)

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_custom_client_id() -> None:
    """Test that a custom client ID is used in the request."""
    session = MagicMock()
    mock_resp = create_mock_response(200, MOCK_TOKEN_RESPONSE)
    session.post = MagicMock(return_value=mock_resp)

    data, error = await _async_validate_refresh_token(
        session, "good-token", client_id="custom-id"
    )

    assert data == MOCK_TOKEN_RESPONSE
    assert error == ""
    call_kwargs = session.post.call_args
    assert call_kwargs.kwargs["json"]["client_id"] == "custom-id"


@pytest.mark.asyncio
async def test_validate_token_default_client_id() -> None:
    """Test that the default client ID is used when none is provided."""
    session = MagicMock()
    mock_resp = create_mock_response(200, MOCK_TOKEN_RESPONSE)
    session.post = MagicMock(return_value=mock_resp)

    await _async_validate_refresh_token(session, "good-token")

    call_kwargs = session.post.call_args
    assert call_kwargs.kwargs["json"]["client_id"] == CLIENT_ID
