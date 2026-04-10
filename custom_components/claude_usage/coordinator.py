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
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    TOKEN_REFRESH_BUFFER_SECS,
    TOKEN_SCOPES,
    TOKEN_URL,
    USAGE_URL,
)

_LOGGER = logging.getLogger(__name__)

type ClaudeUsageConfigEntry = ConfigEntry[ClaudeUsageCoordinator]


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
        interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

    async def _async_refresh_token(self) -> str:
        """Refresh the OAuth token and persist the new tokens."""
        refresh_token = self.config_entry.data[CONF_REFRESH_TOKEN]

        try:
            async with self.session.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "scope": TOKEN_SCOPES,
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 400:
                    body = await resp.json()
                    if body.get("error") == "invalid_grant":
                        raise ConfigEntryAuthFailed(
                            "Refresh token is invalid. Re-authenticate the integration."
                        )
                resp.raise_for_status()
                data = await resp.json()
        except ConfigEntryAuthFailed:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Token refresh failed: {err}") from err

        new_access = data["access_token"]
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
                return {"_needs_retry": True}
            resp.raise_for_status()
            return await resp.json()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch usage data, handling token refresh and 401 retry."""
        try:
            token = await self._async_get_valid_token()
            data = await self._async_fetch_usage(token)

            # On 401, force-refresh and retry once
            if data.get("_needs_retry"):
                _LOGGER.warning("Got 401 — forcing token refresh and retrying")
                token = await self._async_refresh_token()
                data = await self._async_fetch_usage(token)
                if data.get("_needs_retry"):
                    raise ConfigEntryAuthFailed(
                        "API returned 401 after token refresh"
                    )

            return data

        except ConfigEntryAuthFailed:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching usage data: {err}") from err
