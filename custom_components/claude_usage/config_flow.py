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

_LOGGER = logging.getLogger(__name__)

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUTH_REDIRECT_URI,
    AUTHORIZE_URL,
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOKEN_LIFETIME_SECS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    OAUTH_AUTHORIZE_SCOPES,
    TOKEN_SCOPES,
    TOKEN_URL,
)

MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REFRESH_TOKEN): str,
        vol.Optional(CONF_CLIENT_ID): str,
    }
)

AUTH_SCHEMA = vol.Schema({vol.Required("code"): str})

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


# --- PKCE helpers ---


def _compute_code_challenge(verifier: str) -> str:
    """Compute the S256 PKCE challenge for a given verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    return verifier, _compute_code_challenge(verifier)


def _build_authorize_url(client_id: str, code_challenge: str, state: str) -> str:
    """Build the Claude OAuth authorize URL."""
    params = {
        # Nonstandard param: mirrors the Claude Code CLI. Tells Claude's
        # authorize endpoint to display the authorization code on the redirect
        # page (manual-paste flow) instead of doing a normal HTTP redirect.
        "code": "true",
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": AUTH_REDIRECT_URI,
        "scope": OAUTH_AUTHORIZE_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _split_code_and_state(raw: str) -> tuple[str, str | None]:
    """Split a pasted 'code#state' string. Returns (code, state_or_None)."""
    raw = raw.strip()
    if "#" in raw:
        code, _, state = raw.partition("#")
        return code.strip(), state.strip() or None
    return raw, None


# --- Token exchange helpers ---


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
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "scope": TOKEN_SCOPES,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status >= 500:
                _LOGGER.error("Token validate: server error %s", resp.status)
                return None, "cannot_connect"
            if resp.status != 200:
                body = await resp.text()
                _LOGGER.error(
                    "Token validate failed: status=%s body=%s",
                    resp.status,
                    body[:500],
                )
                return None, "invalid_token"
            return await resp.json(), ""
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.error("Token validate network error: %s", err)
        return None, "cannot_connect"


async def _async_exchange_code(
    session: aiohttp.ClientSession,
    code: str,
    code_verifier: str,
    client_id: str = CLIENT_ID,
) -> tuple[dict[str, Any] | None, str]:
    """Exchange an authorization code for tokens.

    Returns (token_data, error_key). On success error_key is empty.
    """
    try:
        async with session.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": AUTH_REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status >= 500:
                _LOGGER.error("Code exchange: server error %s", resp.status)
                return None, "cannot_connect"
            if resp.status != 200:
                body = await resp.text()
                _LOGGER.error(
                    "Code exchange failed: status=%s body=%s",
                    resp.status,
                    body[:500],
                )
                return None, "invalid_code"
            return await resp.json(), ""
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.error("Code exchange network error: %s", err)
        return None, "cannot_connect"


def _token_data_to_entry(token_data: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an OAuth token response into config entry data.

    Returns None if the response is missing required fields.
    """
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token or not refresh_token:
        # Log which fields are present (redact values) to diagnose missing tokens
        _LOGGER.error(
            "Token response missing required fields: has_access_token=%s, "
            "has_refresh_token=%s, keys=%s",
            bool(access_token),
            bool(refresh_token),
            list(token_data.keys()),
        )
        return None
    return {
        CONF_ACCESS_TOKEN: access_token,
        CONF_REFRESH_TOKEN: refresh_token,
        CONF_EXPIRES_AT: time.time()
        + token_data.get("expires_in", DEFAULT_TOKEN_LIFETIME_SECS),
    }


class ClaudeUsageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Claude Usage."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._code_verifier: str | None = None
        self._state: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ClaudeUsageOptionsFlow:
        """Create the options flow."""
        return ClaudeUsageOptionsFlow()

    # --- Entry points ---

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup — offer OAuth or manual token entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="user",
            menu_options=["auth", "manual"],
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfiguration — offer OAuth re-auth or manual token update."""
        # raise_on_progress=False: a previous reconfigure flow may still be
        # registered (e.g. user closed the dialog after an expired-code error
        # without explicitly aborting). Default behavior would trip
        # "already_in_progress" and lock the user out of retrying.
        await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
        self._abort_if_unique_id_mismatch()
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["auth", "manual"],
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the refresh token becomes invalid."""
        return self.async_show_menu(
            step_id="reauth",
            menu_options=["auth", "manual"],
        )

    # --- OAuth flow ---

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in via Claude's OAuth authorize page (PKCE)."""
        if self._code_verifier is None or self._state is None:
            self._code_verifier, challenge = _generate_pkce_pair()
            self._state = secrets.token_urlsafe(32)
        else:
            challenge = _compute_code_challenge(self._code_verifier)

        auth_url = _build_authorize_url(CLIENT_ID, challenge, self._state)
        errors: dict[str, str] = {}

        if user_input is not None:
            code, pasted_state = _split_code_and_state(user_input["code"])
            # Require the pasted input to carry state and match what we issued.
            # PKCE covers code-injection but state binds this callback to this
            # flow instance (CSRF); don't let a bare-code paste skip it.
            if pasted_state is None or pasted_state != self._state:
                errors["base"] = "invalid_state"
            elif not code:
                errors["base"] = "invalid_code"
            else:
                session = async_get_clientsession(self.hass)
                token_data, error_key = await _async_exchange_code(
                    session, code, self._code_verifier
                )
                if token_data is None:
                    errors["base"] = error_key
                else:
                    data = _token_data_to_entry(token_data)
                    if data is None:
                        errors["base"] = "invalid_code"
                    else:
                        return await self._async_finish(data)

        return self.async_show_form(
            step_id="auth",
            data_schema=AUTH_SCHEMA,
            description_placeholders={"auth_url": auth_url},
            errors=errors,
        )

    # --- Manual token entry ---

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual refresh-token entry."""
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
                        + token_data.get(
                            "expires_in", DEFAULT_TOKEN_LIFETIME_SECS
                        ),
                    }
                    if user_input.get(CONF_CLIENT_ID):
                        data[CONF_CLIENT_ID] = user_input[CONF_CLIENT_ID]
                    return await self._async_finish(data)

        return self.async_show_form(
            step_id="manual",
            data_schema=MANUAL_SCHEMA,
            errors=errors,
        )

    # --- Finish helper: branches on initial setup vs reconfigure ---

    async def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create or update the config entry with the given token data."""
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=data,
            )
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data=data,
            )
        return self.async_create_entry(title="Claude Usage", data=data)


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
