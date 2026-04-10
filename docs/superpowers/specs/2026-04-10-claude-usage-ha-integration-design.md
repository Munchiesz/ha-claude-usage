# Claude Usage — Home Assistant Custom Integration

**Date:** 2026-04-10
**Status:** Approved

## Overview

A Home Assistant custom integration that polls Claude (Anthropic) subscription usage via the OAuth API and exposes the data as HA sensor entities. Installable via HACS, configurable through the HA UI, with automatic OAuth token lifecycle management.

## Problem

The user wants real-time visibility into their Claude subscription usage (session limits, weekly limits, extra usage credits) directly in Home Assistant dashboards and automations — without running external scripts or relying on a separate machine.

## Architecture

```
custom_components/claude_usage/
├── __init__.py              # Integration setup, platform forwarding, token refresh
├── manifest.json            # Integration metadata, HACS compatibility
├── config_flow.py           # Two-path setup: OAuth login OR manual token paste
├── coordinator.py           # DataUpdateCoordinator — polls API every 5 min
├── sensor.py                # 6 sensor entities grouped under 1 device
├── const.py                 # Constants: URLs, client ID, sensor definitions
├── strings.json             # Config flow UI text
└── translations/
    └── en.json              # English translations (mirrors strings.json)
```

### Data Flow

1. User installs via HACS, adds integration via HA UI
2. Config flow authenticates (OAuth redirect or manual token paste)
3. Validated tokens stored in HA config entry (encrypted at rest)
4. `__init__.py` creates a `DataUpdateCoordinator` on setup
5. Coordinator polls `GET https://api.anthropic.com/api/oauth/usage` every 5 minutes
6. Before each poll, checks token expiry — refreshes if expiring within 5 minutes
7. Sensor entities read state from coordinator data
8. On 401, force-refresh token and retry once

## Authentication

### API Endpoints

- **Usage API:** `GET https://api.anthropic.com/api/oauth/usage`
  - Header: `Authorization: Bearer <access_token>`
  - Header: `anthropic-beta: oauth-2025-04-20`
- **Token Refresh:** `POST https://platform.claude.com/v1/oauth/token`
  - Body (JSON): `{ grant_type, refresh_token, client_id, scope }`
  - Client ID: `9d1c250a-e61b-44d9-88ed-5944d1962f5e`
  - Scopes: `user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload`

### Token Lifecycle

- Access tokens expire every ~8 hours (`expires_in: 28800`)
- Refresh tokens rotate on each use (response includes new `refresh_token`)
- Coordinator checks `expires_at` before each poll
- If token expires within 5 minutes (`TOKEN_REFRESH_BUFFER_SECS = 300`), refresh first
- Updated tokens (both access + refresh) written back to config entry via `hass.config_entries.async_update_entry()`
- On 401 response: force-refresh and retry once
- On refresh failure: log error, retry on next poll cycle; do not crash

### Config Flow — Two Paths

User sees a menu with two options:

**Path 1 — "Login with Claude" (OAuth2 Authorization Code + PKCE):**
- Initiates standard OAuth2 flow using HA's `config_entry_oauth2_flow`
- Authorization URL: `https://platform.claude.com/v1/oauth/authorize` (needs verification)
- Redirects user to Anthropic login page
- On callback, exchanges authorization code for tokens
- Risk: Anthropic may reject HA's redirect URI since the client ID belongs to Claude Code. If this fails, user falls back to Path 2.

**Path 2 — "Enter token manually":**
- User pastes a refresh token (obtained from `~/.claude/.credentials.json` on their PC)
- Config flow validates by calling the refresh endpoint
- On success, stores the returned access_token, refresh_token, and computed expires_at
- Guaranteed to work — already validated during development

Both paths produce the same config entry structure:
```json
{
  "access_token": "sk-ant-oat01-...",
  "refresh_token": "sk-ant-ort01-...",
  "expires_at": 1775710800.0
}
```

## Usage API Response

```json
{
  "five_hour": {
    "utilization": 44.0,
    "resets_at": "2026-04-11T02:00:00.496905+00:00"
  },
  "seven_day": {
    "utilization": 13.0,
    "resets_at": "2026-04-16T18:00:00.496927+00:00"
  },
  "extra_usage": {
    "is_enabled": true,
    "monthly_limit": 10000,
    "used_credits": 1628,
    "utilization": 16.28
  }
}
```

## Sensors

All sensors grouped under device:
- **Name:** "Claude Subscription"
- **Manufacturer:** "Anthropic"
- **Model:** "Claude Max" (or derived from subscription type if available)
- **Identifier:** derived from account info or config entry ID

| Entity ID | Source Field | State | Unit | Icon | device_class | Extra Attributes |
|---|---|---|---|---|---|---|
| `sensor.claude_session_utilization` | `five_hour.utilization` | float | `%` | `mdi:gauge` | — | `resets_at`, `minutes_until_reset` |
| `sensor.claude_session_resets_at` | `five_hour.resets_at` | ISO timestamp | — | `mdi:timer-sand` | `timestamp` | `minutes_until_reset` |
| `sensor.claude_weekly_utilization` | `seven_day.utilization` | float | `%` | `mdi:chart-line` | — | `resets_at`, `minutes_until_reset` |
| `sensor.claude_weekly_resets_at` | `seven_day.resets_at` | ISO timestamp | — | `mdi:calendar-clock` | `timestamp` | `minutes_until_reset` |
| `sensor.claude_extra_credits_used` | `extra_usage.used_credits` | float | `credits` | `mdi:currency-usd` | — | `monthly_limit` |
| `sensor.claude_extra_utilization` | `extra_usage.utilization` | float | `%` | `mdi:credit-card-clock` | — | `monthly_limit`, `used_credits` |

### Conditional Sensors

- Extra usage sensors (`claude_extra_credits_used`, `claude_extra_utilization`) are only created when `extra_usage` is present and `is_enabled` is `true` in the first API response
- If `extra_usage` is absent or `is_enabled: false`, these sensors are not registered
- The `minutes_until_reset` attribute is computed at each update (not a separate sensor)

## Options Flow

After initial setup, user can configure:
- **Update interval:** 1–30 minutes (default: 5)

Accessible via the integration's "Configure" button in HA settings.

## Error Handling

| Scenario | Behavior |
|---|---|
| Token refresh fails | Log warning, keep stale data, retry next cycle |
| API returns non-200 (not 401) | Log error, keep stale data, retry next cycle |
| API returns 401 | Force-refresh token, retry once; if still 401, log error |
| Network timeout | Treat as API error, retry next cycle |
| `extra_usage` absent or disabled | Skip those sensors (don't create them) |
| Invalid token on setup | Config flow shows error, user retries |

The integration should never crash or require manual intervention after initial setup. All errors are recoverable via retry on the next poll cycle.

## HACS Compatibility

`manifest.json` includes:
- `"version"` field
- `"documentation"` pointing to GitHub repo README
- `"issue_tracker"` pointing to GitHub issues
- `"iot_class": "cloud_polling"`
- `"config_flow": true`

A `hacs.json` file at the repo root with `"render_readme": true`.

User installs by adding the GitHub repo URL as a custom repository in HACS (category: Integration), installing, restarting HA, then adding via Settings > Integrations.

## Dependencies

- No external Python packages — uses only `aiohttp` (bundled with HA) and stdlib
- No filesystem access, no browser, no Playwright
- Fully self-contained within HA

## Future Considerations (not in scope)

- Mushroom dashboard card YAML (separate task after integration works)
- Multiple Claude accounts
- Automations triggered on high utilization thresholds
