"""DataUpdateCoordinator for Claude Usage."""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    TOKEN_REFRESH_BUFFER_SECS,
    TOKEN_SCOPES,
    TOKEN_URL,
    USAGE_URL,
)

_LOGGER = logging.getLogger(__name__)

type ClaudeUsageConfigEntry = ConfigEntry[ClaudeUsageCoordinator]


class _TokenExpiredError(Exception):
    """Raised when the API returns 401, indicating the token has expired."""


class ClaudeUsageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Claude usage API and manages token refresh."""

    config_entry: ClaudeUsageConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ClaudeUsageConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.session = async_get_clientsession(hass)
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._default_interval = timedelta(seconds=interval)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._default_interval,
        )

    async def _async_refresh_token(self) -> str:
        """Refresh the OAuth token and persist the new tokens."""
        refresh_token = self.config_entry.data[CONF_REFRESH_TOKEN]
        client_id = self.config_entry.data.get(CONF_CLIENT_ID, CLIENT_ID)

        try:
            async with self.session.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "scope": TOKEN_SCOPES,
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 400:
                    body = await resp.json()
                    error = body.get("error", "")
                    # Anthropic may return {"error": "invalid_grant"} or
                    # {"error": {"type": "...", "message": "..."}}.
                    error_type = (
                        error.get("type", "") if isinstance(error, dict) else error
                    )
                    if error_type in ("invalid_grant", "invalid_request_error"):
                        raise ConfigEntryAuthFailed(
                            "Refresh token is invalid. Re-authenticate the integration."
                        )
                resp.raise_for_status()
                data = await resp.json()
        except ConfigEntryAuthFailed:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Token refresh failed: {err}") from err

        new_access = data.get("access_token")
        if not new_access:
            raise UpdateFailed("Token refresh returned no access_token")
        new_refresh = data.get("refresh_token", refresh_token)
        expires_at = time.time() + data.get("expires_in", 28800)

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_ACCESS_TOKEN: new_access,
                CONF_REFRESH_TOKEN: new_refresh,
                CONF_EXPIRES_AT: expires_at,
            },
        )

        _LOGGER.debug("Token refreshed, expires at %s", expires_at)
        return new_access

    async def _async_get_valid_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        expires_at = self.config_entry.data.get(CONF_EXPIRES_AT, 0)
        if time.time() + TOKEN_REFRESH_BUFFER_SECS < expires_at:
            return self.config_entry.data[CONF_ACCESS_TOKEN]
        return await self._async_refresh_token()

    async def _async_fetch_usage(self, token: str) -> dict[str, Any]:
        """Fetch usage data from the Anthropic API."""
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        }
        async with self.session.get(
            USAGE_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 401:
                raise _TokenExpiredError
            if resp.status == 429:
                retry_after = resp.headers.get("Retry-After")
                msg = "Rate limited by Claude API"
                if retry_after:
                    try:
                        delay = int(retry_after)
                        self.update_interval = timedelta(
                            seconds=max(delay, int(self._default_interval.total_seconds()))
                        )
                        msg += f" (retry after {retry_after}s)"
                    except ValueError:
                        self.update_interval = self._default_interval * 2
                        msg += f" (retry after {retry_after})"
                else:
                    self.update_interval = self._default_interval * 2
                _LOGGER.warning(msg)
                raise UpdateFailed(msg)
            resp.raise_for_status()
            return await resp.json()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch usage data, handling token refresh and 401 retry."""
        try:
            token = await self._async_get_valid_token()
            data = await self._async_fetch_usage(token)
            self.update_interval = self._default_interval
            return data

        except _TokenExpiredError:
            _LOGGER.warning("Got 401 — forcing token refresh and retrying")
            try:
                token = await self._async_refresh_token()
                data = await self._async_fetch_usage(token)
                self.update_interval = self._default_interval
                return data
            except _TokenExpiredError:
                raise ConfigEntryAuthFailed(
                    "API returned 401 after token refresh"
                )

        except ConfigEntryAuthFailed:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching usage data: {err}") from err
