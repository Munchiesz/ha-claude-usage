"""Config flow for Claude Usage."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

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
    AUTHORIZE_URL,
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
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
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            "scan_interval", default=DEFAULT_SCAN_INTERVAL
        ): vol.All(
            cv.positive_int,
            vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
        ),
    }
)


async def _async_validate_refresh_token(
    session: aiohttp.ClientSession, refresh_token: str
) -> dict[str, Any] | None:
    """Validate a refresh token by exchanging it. Returns token data or None."""
    try:
        async with session.post(
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
            if resp.status != 200:
                return None
            return await resp.json()
    except (aiohttp.ClientError, TimeoutError):
        return None


class ClaudeUsageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Claude Usage."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._code_verifier: str | None = None

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
        """Handle the initial menu step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_show_menu(
            step_id="user",
            menu_options=["oauth", "manual"],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual refresh token entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            token_data = await _async_validate_refresh_token(
                session, user_input[CONF_REFRESH_TOKEN]
            )

            if token_data is None:
                errors["base"] = "invalid_token"
            else:
                return self.async_create_entry(
                    title="Claude Usage",
                    data={
                        CONF_ACCESS_TOKEN: token_data["access_token"],
                        CONF_REFRESH_TOKEN: token_data.get(
                            "refresh_token", user_input[CONF_REFRESH_TOKEN]
                        ),
                        CONF_EXPIRES_AT: time.time()
                        + token_data.get("expires_in", 28800),
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=MANUAL_SCHEMA,
            errors=errors,
        )

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the OAuth authorization flow."""
        self._code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(self._code_verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )

        params = urlencode({
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self._get_redirect_url(),
            "scope": TOKEN_SCOPES,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
        auth_url = f"{AUTHORIZE_URL}?{params}"

        return self.async_external_step(step_id="oauth", url=auth_url)

    def _get_redirect_url(self) -> str:
        """Get the OAuth redirect URL."""
        return "https://my.home-assistant.io/redirect/oauth"

    async def async_step_oauth_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the OAuth callback after user authorizes."""
        if user_input is None or "code" not in user_input:
            return self.async_abort(reason="oauth_failed")

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "code": user_input["code"],
                    "client_id": CLIENT_ID,
                    "code_verifier": self._code_verifier,
                    "redirect_uri": self._get_redirect_url(),
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return self.async_abort(reason="oauth_failed")
                token_data = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            return self.async_abort(reason="oauth_failed")

        return self.async_create_entry(
            title="Claude Usage",
            data={
                CONF_ACCESS_TOKEN: token_data["access_token"],
                CONF_REFRESH_TOKEN: token_data["refresh_token"],
                CONF_EXPIRES_AT: time.time()
                + token_data.get("expires_in", 28800),
            },
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
