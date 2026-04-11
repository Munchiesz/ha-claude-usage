"""Config flow for Claude Usage."""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    TOKEN_SCOPES,
    TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)

MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REFRESH_TOKEN): str,
        vol.Optional(CONF_CLIENT_ID): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): vol.All(
            cv.positive_int,
            vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
        ),
    }
)


async def _async_validate_refresh_token(
    session: aiohttp.ClientSession,
    refresh_token: str,
    client_id: str = CLIENT_ID,
) -> tuple[dict[str, Any] | None, str]:
    """Validate a refresh token by exchanging it.

    Returns (token_data, error_key). On success error_key is empty.
    """
    try:
        async with session.post(
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
            if resp.status >= 500:
                return None, "cannot_connect"
            if resp.status != 200:
                return None, "invalid_token"
            return await resp.json(), ""
    except (aiohttp.ClientError, TimeoutError):
        return None, "cannot_connect"


class ClaudeUsageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Claude Usage."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ClaudeUsageOptionsFlow:
        """Create the options flow."""
        return ClaudeUsageOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — manual token entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            custom_client_id = user_input.get(CONF_CLIENT_ID) or CLIENT_ID
            token_data, error_key = await _async_validate_refresh_token(
                session, user_input[CONF_REFRESH_TOKEN], custom_client_id
            )

            if token_data is None:
                errors["base"] = error_key
            else:
                access_token = token_data.get("access_token")
                if not access_token:
                    errors["base"] = "invalid_token"
                else:
                    data = {
                        CONF_ACCESS_TOKEN: access_token,
                        CONF_REFRESH_TOKEN: token_data.get(
                            "refresh_token", user_input[CONF_REFRESH_TOKEN]
                        ),
                        CONF_EXPIRES_AT: time.time()
                        + token_data.get("expires_in", 28800),
                    }
                    if user_input.get(CONF_CLIENT_ID):
                        data[CONF_CLIENT_ID] = user_input[CONF_CLIENT_ID]
                    return self.async_create_entry(
                        title="Claude Usage",
                        data=data,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=MANUAL_SCHEMA,
            errors=errors,
        )


class ClaudeUsageOptionsFlow(OptionsFlow):
    """Handle options for Claude Usage."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
