"""Tests for the Claude Usage coordinator."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.claude_usage.const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
)
from custom_components.claude_usage.coordinator import (
    ClaudeUsageCoordinator,
    _TokenExpiredError,
)

from .conftest import (
    MOCK_TOKEN_RESPONSE,
    MOCK_USAGE_RESPONSE,
    create_mock_response,
)


def _make_coordinator(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> ClaudeUsageCoordinator:
    """Create a coordinator with mocked dependencies."""
    with patch(
        "custom_components.claude_usage.coordinator.async_get_clientsession"
    ) as mock_get:
        mock_get.return_value = MagicMock()
        coordinator = ClaudeUsageCoordinator(mock_hass, mock_config_entry)
    return coordinator


# --- Token refresh tests ---


@pytest.mark.asyncio
async def test_get_valid_token_not_expired(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a valid, non-expired token is returned without refresh."""
    mock_config_entry.data[CONF_EXPIRES_AT] = time.time() + 3600
    coordinator = _make_coordinator(mock_hass, mock_config_entry)

    token = await coordinator._async_get_valid_token()

    assert token == "test-access-token"


@pytest.mark.asyncio
async def test_get_valid_token_expired_triggers_refresh(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that an expired token triggers a refresh."""
    mock_config_entry.data[CONF_EXPIRES_AT] = time.time() - 100
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    coordinator.session.post = MagicMock(
        return_value=create_mock_response(200, MOCK_TOKEN_RESPONSE)
    )

    token = await coordinator._async_refresh_token()

    assert token == "new-access-token"
    mock_hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_token_invalid_grant_raises_auth_failed(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that invalid_grant during refresh raises ConfigEntryAuthFailed."""
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    resp = create_mock_response(400, {"error": "invalid_grant"})
    resp.raise_for_status = MagicMock()  # won't be reached
    coordinator.session.post = MagicMock(return_value=resp)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_refresh_token()


@pytest.mark.asyncio
async def test_refresh_token_no_access_token_raises_update_failed(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a response without access_token raises UpdateFailed."""
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    coordinator.session.post = MagicMock(
        return_value=create_mock_response(200, {"refresh_token": "new"})
    )

    with pytest.raises(UpdateFailed, match="no access_token"):
        await coordinator._async_refresh_token()


@pytest.mark.asyncio
async def test_refresh_uses_custom_client_id(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a custom client ID from config is used during refresh."""
    mock_config_entry.data[CONF_CLIENT_ID] = "my-custom-id"
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    coordinator.session.post = MagicMock(
        return_value=create_mock_response(200, MOCK_TOKEN_RESPONSE)
    )

    await coordinator._async_refresh_token()

    call_kwargs = coordinator.session.post.call_args
    assert call_kwargs.kwargs["json"]["client_id"] == "my-custom-id"


# --- Fetch usage tests ---


@pytest.mark.asyncio
async def test_fetch_usage_success(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test successful usage fetch."""
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    coordinator.session.get = MagicMock(
        return_value=create_mock_response(200, MOCK_USAGE_RESPONSE)
    )

    data = await coordinator._async_fetch_usage("test-token")

    assert data["five_hour"]["utilization"] == 44.0
    assert data["extra_usage"]["is_enabled"] is True


@pytest.mark.asyncio
async def test_fetch_usage_401_raises_token_expired(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a 401 response raises _TokenExpiredError."""
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    coordinator.session.get = MagicMock(
        return_value=create_mock_response(401)
    )

    with pytest.raises(_TokenExpiredError):
        await coordinator._async_fetch_usage("expired-token")


@pytest.mark.asyncio
async def test_fetch_usage_429_raises_update_failed(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a 429 response raises UpdateFailed."""
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    coordinator.session.get = MagicMock(
        return_value=create_mock_response(429, headers={"Retry-After": "120"})
    )

    with pytest.raises(UpdateFailed, match="Rate limited"):
        await coordinator._async_fetch_usage("test-token")


@pytest.mark.asyncio
async def test_429_increases_update_interval(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a 429 with Retry-After increases the update interval."""
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    original_interval = coordinator.update_interval
    coordinator.session.get = MagicMock(
        return_value=create_mock_response(429, headers={"Retry-After": "600"})
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_fetch_usage("test-token")

    assert coordinator.update_interval == timedelta(seconds=600)
    assert coordinator.update_interval > original_interval


@pytest.mark.asyncio
async def test_success_restores_default_interval(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that a successful fetch restores the default update interval."""
    mock_config_entry.data[CONF_EXPIRES_AT] = time.time() + 3600
    coordinator = _make_coordinator(mock_hass, mock_config_entry)
    # Simulate a previous rate-limit bump
    coordinator.update_interval = timedelta(seconds=600)

    coordinator.session.get = MagicMock(
        return_value=create_mock_response(200, MOCK_USAGE_RESPONSE)
    )

    await coordinator._async_update_data()

    assert coordinator.update_interval == coordinator._default_interval


# --- _async_update_data retry logic ---


@pytest.mark.asyncio
async def test_update_data_retries_on_401(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that _async_update_data refreshes the token and retries on 401."""
    mock_config_entry.data[CONF_EXPIRES_AT] = time.time() + 3600
    coordinator = _make_coordinator(mock_hass, mock_config_entry)

    # First GET returns 401, second GET returns success
    resp_401 = create_mock_response(401)
    resp_ok = create_mock_response(200, MOCK_USAGE_RESPONSE)
    coordinator.session.get = MagicMock(side_effect=[resp_401, resp_ok])
    coordinator.session.post = MagicMock(
        return_value=create_mock_response(200, MOCK_TOKEN_RESPONSE)
    )

    data = await coordinator._async_update_data()

    assert data["five_hour"]["utilization"] == 44.0
    coordinator.session.post.assert_called_once()


@pytest.mark.asyncio
async def test_update_data_double_401_raises_auth_failed(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test that two consecutive 401s raise ConfigEntryAuthFailed."""
    mock_config_entry.data[CONF_EXPIRES_AT] = time.time() + 3600
    coordinator = _make_coordinator(mock_hass, mock_config_entry)

    resp_401 = create_mock_response(401)
    coordinator.session.get = MagicMock(return_value=resp_401)
    coordinator.session.post = MagicMock(
        return_value=create_mock_response(200, MOCK_TOKEN_RESPONSE)
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
