# Claude Usage HA Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom integration that polls Claude subscription usage and exposes it as sensor entities.

**Architecture:** Config flow (menu → OAuth or manual token) creates a config entry with OAuth tokens. A DataUpdateCoordinator polls the Anthropic usage API every 5 minutes, auto-refreshing tokens as needed. Six sensor entities (four always, two conditional on extra_usage) are grouped under a single device.

**Tech Stack:** Python 3.14, aiohttp (bundled with HA), Home Assistant 2026.4+ APIs (runtime_data, AddConfigEntryEntitiesCallback, frozen dataclass descriptions)

---

### Task 1: Constants, Manifest, and HACS metadata

**Files:**
- Create: `custom_components/claude_usage/const.py`
- Create: `custom_components/claude_usage/manifest.json`
- Create: `hacs.json`

- [ ] **Step 1: Create const.py**

```python
"""Constants for the Claude Usage integration."""

DOMAIN = "claude_usage"

DEFAULT_SCAN_INTERVAL = 300  # seconds (5 minutes)
MIN_SCAN_INTERVAL = 60  # 1 minute
MAX_SCAN_INTERVAL = 1800  # 30 minutes

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
AUTHORIZE_URL = "https://platform.claude.com/v1/oauth/authorize"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
TOKEN_REFRESH_BUFFER_SECS = 300  # refresh when token expires within 5 min

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
```

- [ ] **Step 2: Create manifest.json**

```json
{
  "domain": "claude_usage",
  "name": "Claude Usage",
  "version": "1.0.0",
  "documentation": "https://github.com/theilya/ha-claude-usage",
  "issue_tracker": "https://github.com/theilya/ha-claude-usage/issues",
  "codeowners": ["@theilya"],
  "dependencies": [],
  "requirements": [],
  "config_flow": true,
  "iot_class": "cloud_polling",
  "integration_type": "service"
}
```

- [ ] **Step 3: Create hacs.json at repo root**

```json
{
  "name": "Claude Usage",
  "render_readme": true
}
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/claude_usage/const.py custom_components/claude_usage/manifest.json hacs.json
git commit -m "feat: add constants, manifest, and HACS metadata"
```

---

### Task 2: Strings and translations

**Files:**
- Create: `custom_components/claude_usage/strings.json`
- Create: `custom_components/claude_usage/translations/en.json`

- [ ] **Step 1: Create strings.json**

```json
{
  "config": {
    "step": {
      "user": {
        "menu_options": {
          "oauth": "Login with Claude",
          "manual": "Enter token manually"
        }
      },
      "manual": {
        "title": "Enter refresh token",
        "description": "Paste your Claude refresh token. You can find it in `~/.claude/.credentials.json` on a machine with Claude Code installed — look for the `refreshToken` field under `claudeAiOauth`.",
        "data": {
          "refresh_token": "Refresh token"
        }
      }
    },
    "error": {
      "invalid_token": "Token is invalid or expired. Please check and try again.",
      "cannot_connect": "Cannot connect to Claude API. Check your network connection.",
      "unknown": "An unexpected error occurred."
    },
    "abort": {
      "already_configured": "Claude Usage is already configured.",
      "oauth_failed": "OAuth login failed. Please use the manual token option instead."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Claude Usage settings",
        "data": {
          "scan_interval": "Update interval (seconds)"
        }
      }
    }
  }
}
```

- [ ] **Step 2: Create translations/en.json (identical content)**

Copy the exact same content from `strings.json` to `custom_components/claude_usage/translations/en.json`.

- [ ] **Step 3: Commit**

```bash
git add custom_components/claude_usage/strings.json custom_components/claude_usage/translations/en.json
git commit -m "feat: add config flow strings and translations"
```

---

### Task 3: Data coordinator with token refresh

**Files:**
- Create: `custom_components/claude_usage/coordinator.py`

This is the core logic: token lifecycle management + API polling.

- [ ] **Step 1: Create coordinator.py**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add custom_components/claude_usage/coordinator.py
git commit -m "feat: add data coordinator with token refresh and usage polling"
```

---

### Task 4: Sensor entities

**Files:**
- Create: `custom_components/claude_usage/sensor.py`

- [ ] **Step 1: Create sensor.py**

```python
"""Sensor platform for Claude Usage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClaudeUsageConfigEntry, ClaudeUsageCoordinator


def _minutes_until(iso_ts: str | None) -> int | None:
    """Return minutes from now until the given ISO-8601 timestamp."""
    if not iso_ts:
        return None
    try:
        target = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = target - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds() // 60))
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, kw_only=True)
class ClaudeUsageSensorDescription(SensorEntityDescription):
    """Describe a Claude Usage sensor."""

    value_fn: Callable[[dict[str, Any]], StateType]
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[ClaudeUsageSensorDescription, ...] = (
    ClaudeUsageSensorDescription(
        key="session_utilization",
        translation_key="session_utilization",
        name="Session Utilization",
        native_unit_of_measurement="%",
        icon="mdi:gauge",
        value_fn=lambda d: d.get("five_hour", {}).get("utilization"),
        extra_attrs_fn=lambda d: {
            "resets_at": d.get("five_hour", {}).get("resets_at", ""),
            "minutes_until_reset": _minutes_until(
                d.get("five_hour", {}).get("resets_at")
            ),
        },
    ),
    ClaudeUsageSensorDescription(
        key="session_resets_at",
        translation_key="session_resets_at",
        name="Session Resets At",
        icon="mdi:timer-sand",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _parse_timestamp(d.get("five_hour", {}).get("resets_at")),
        extra_attrs_fn=lambda d: {
            "minutes_until_reset": _minutes_until(
                d.get("five_hour", {}).get("resets_at")
            ),
        },
    ),
    ClaudeUsageSensorDescription(
        key="weekly_utilization",
        translation_key="weekly_utilization",
        name="Weekly Utilization",
        native_unit_of_measurement="%",
        icon="mdi:chart-line",
        value_fn=lambda d: d.get("seven_day", {}).get("utilization"),
        extra_attrs_fn=lambda d: {
            "resets_at": d.get("seven_day", {}).get("resets_at", ""),
            "minutes_until_reset": _minutes_until(
                d.get("seven_day", {}).get("resets_at")
            ),
        },
    ),
    ClaudeUsageSensorDescription(
        key="weekly_resets_at",
        translation_key="weekly_resets_at",
        name="Weekly Resets At",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _parse_timestamp(d.get("seven_day", {}).get("resets_at")),
        extra_attrs_fn=lambda d: {
            "minutes_until_reset": _minutes_until(
                d.get("seven_day", {}).get("resets_at")
            ),
        },
    ),
)

EXTRA_USAGE_DESCRIPTIONS: tuple[ClaudeUsageSensorDescription, ...] = (
    ClaudeUsageSensorDescription(
        key="extra_credits_used",
        translation_key="extra_credits_used",
        name="Extra Credits Used",
        native_unit_of_measurement="credits",
        icon="mdi:currency-usd",
        value_fn=lambda d: d.get("extra_usage", {}).get("used_credits"),
        extra_attrs_fn=lambda d: {
            "monthly_limit": d.get("extra_usage", {}).get("monthly_limit"),
        },
    ),
    ClaudeUsageSensorDescription(
        key="extra_utilization",
        translation_key="extra_utilization",
        name="Extra Usage Utilization",
        native_unit_of_measurement="%",
        icon="mdi:credit-card-clock",
        value_fn=lambda d: d.get("extra_usage", {}).get("utilization"),
        extra_attrs_fn=lambda d: {
            "monthly_limit": d.get("extra_usage", {}).get("monthly_limit"),
            "used_credits": d.get("extra_usage", {}).get("used_credits"),
        },
    ),
)


def _parse_timestamp(iso_ts: str | None) -> datetime | None:
    """Parse an ISO timestamp string into a datetime object."""
    if not iso_ts:
        return None
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeUsageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Claude Usage sensors from a config entry."""
    coordinator: ClaudeUsageCoordinator = entry.runtime_data

    descriptions: list[ClaudeUsageSensorDescription] = list(SENSOR_DESCRIPTIONS)

    # Conditionally add extra usage sensors
    extra = coordinator.data.get("extra_usage")
    if extra and extra.get("is_enabled"):
        descriptions.extend(EXTRA_USAGE_DESCRIPTIONS)

    async_add_entities(
        ClaudeUsageSensor(coordinator, description)
        for description in descriptions
    )


class ClaudeUsageSensor(CoordinatorEntity[ClaudeUsageCoordinator], SensorEntity):
    """A Claude Usage sensor."""

    entity_description: ClaudeUsageSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ClaudeUsageCoordinator,
        description: ClaudeUsageSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="Claude Subscription",
            manufacturer="Anthropic",
            model="Claude Max",
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if (
            self.coordinator.data is None
            or self.entity_description.extra_attrs_fn is None
        ):
            return None
        return self.entity_description.extra_attrs_fn(self.coordinator.data)
```

- [ ] **Step 2: Commit**

```bash
git add custom_components/claude_usage/sensor.py
git commit -m "feat: add sensor platform with 6 entity types"
```

---

### Task 5: Config flow (menu, manual token, OAuth, options)

**Files:**
- Create: `custom_components/claude_usage/config_flow.py`

- [ ] **Step 1: Create config_flow.py**

```python
"""Config flow for Claude Usage."""

from __future__ import annotations

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
        # Only allow one instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_show_menu(
            step_id="user",
            menu_options=["oauth", "manual"],
        )

    # ── Manual path ──────────────────────────────────────────────

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

    # ── OAuth path ───────────────────────────────────────────────

    async def async_step_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the OAuth authorization flow."""
        self._code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            hashlib.sha256(self._code_verifier.encode())
            .digest()
            .hex()
        )
        # Note: proper base64url encoding for PKCE
        import base64

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
```

- [ ] **Step 2: Commit**

```bash
git add custom_components/claude_usage/config_flow.py
git commit -m "feat: add config flow with OAuth and manual paths, plus options flow"
```

---

### Task 6: Integration setup (__init__.py)

**Files:**
- Create: `custom_components/claude_usage/__init__.py`

- [ ] **Step 1: Create __init__.py**

```python
"""The Claude Usage integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import ClaudeUsageConfigEntry, ClaudeUsageCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ClaudeUsageConfigEntry
) -> bool:
    """Set up Claude Usage from a config entry."""
    coordinator = ClaudeUsageCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ClaudeUsageConfigEntry
) -> None:
    """Handle options update — adjust the coordinator poll interval."""
    coordinator: ClaudeUsageCoordinator = entry.runtime_data
    coordinator.update_interval = timedelta(
        seconds=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    )


async def async_unload_entry(
    hass: HomeAssistant, entry: ClaudeUsageConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 2: Commit**

```bash
git add custom_components/claude_usage/__init__.py
git commit -m "feat: add integration setup with coordinator and options listener"
```

---

### Task 7: Deploy to Home Assistant and test

**Files:**
- No new files — deploy and verify existing files

- [ ] **Step 1: Copy the integration to HA**

Copy the `custom_components/claude_usage/` directory to the HA config directory at `/config/custom_components/claude_usage/`. This can be done via:
- Samba share (if configured on the HA Synology VM)
- File editor add-on
- SCP/SSH (Terminal & SSH add-on is installed)

Verify all 8 files are present:
```
/config/custom_components/claude_usage/__init__.py
/config/custom_components/claude_usage/manifest.json
/config/custom_components/claude_usage/config_flow.py
/config/custom_components/claude_usage/coordinator.py
/config/custom_components/claude_usage/sensor.py
/config/custom_components/claude_usage/const.py
/config/custom_components/claude_usage/strings.json
/config/custom_components/claude_usage/translations/en.json
```

- [ ] **Step 2: Restart Home Assistant**

Settings → System → Restart. Wait for HA to come back online.

- [ ] **Step 3: Add the integration**

Settings → Devices & Services → Add Integration → search "Claude Usage". Select it.

- [ ] **Step 4: Configure via manual token path**

Choose "Enter token manually". Paste the refresh token:
```
<your-refresh-token-here>
```

Note: you will need a fresh refresh token first — run `claude` on your PC to regenerate one, then copy from `~/.claude/.credentials.json`.

Verify: the integration creates successfully with no errors.

- [ ] **Step 5: Verify sensors**

Go to Developer Tools → States. Filter for `sensor.claude_`. Verify 6 sensors exist:
- `sensor.claude_subscription_session_utilization` — value is a percentage
- `sensor.claude_subscription_session_resets_at` — value is an ISO timestamp
- `sensor.claude_subscription_weekly_utilization` — value is a percentage
- `sensor.claude_subscription_weekly_resets_at` — value is an ISO timestamp
- `sensor.claude_subscription_extra_credits_used` — value is a number (if extra usage enabled)
- `sensor.claude_subscription_extra_usage_utilization` — value is a percentage (if extra usage enabled)

Check that each sensor has the expected `icon`, `unit_of_measurement`, and extra attributes (`resets_at`, `minutes_until_reset`, `monthly_limit`).

- [ ] **Step 6: Verify options flow**

Settings → Devices & Services → Claude Usage → Configure. Change the scan interval to 120 seconds. Save. Check the HA logs to confirm the coordinator picks up the new interval.

- [ ] **Step 7: Test OAuth path (optional)**

Re-add the integration and choose "Login with Claude". If Anthropic accepts the redirect, complete the flow. If it fails with an error, confirm the abort message suggests using the manual path. This path is experimental — failure is expected and acceptable.

- [ ] **Step 8: Commit final state**

```bash
git add -A
git commit -m "feat: Claude Usage HA integration v1.0.0 — tested and working"
```
