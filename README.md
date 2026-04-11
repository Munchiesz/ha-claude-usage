# Claude Usage for Home Assistant

A custom Home Assistant integration that monitors your [Claude](https://claude.ai) (Anthropic) subscription usage in real time.

Track session limits, weekly utilization, extra credit spending, and reset timers — all from your HA dashboard.

## Sensors

| Sensor | Description |
|--------|-------------|
| **Session Utilization** | Current 5-hour usage window (%) with reset countdown |
| **Session Resets At** | Timestamp when the session window resets |
| **Weekly Utilization** | Rolling 7-day usage (%) with reset countdown |
| **Weekly Resets At** | Timestamp when the weekly window resets |
| **Extra Credits Used** | Cumulative extra credits spent this billing cycle (if enabled) |
| **Extra Usage Utilization** | Extra credit usage as a percentage of your monthly limit (if enabled) |

All sensors include extra attributes like `minutes_until_reset`, `monthly_limit`, and `resets_at` for use in automations and templates.

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right and select **Custom repositories**
3. Add `https://github.com/Munchiesz/ha-claude-usage` as an **Integration**
4. Search for "Claude Usage" and install it
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/claude_usage` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

## Setup

You need a **refresh token** from Claude Code.

1. Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on any machine
2. Sign in with your Claude account
3. Open the credentials file at `~/.claude/.credentials.json`
4. Copy the `refreshToken` value from the `claudeAiOauth` section
5. In Home Assistant, go to **Settings > Devices & Services > Add Integration**
6. Search for **Claude Usage** and paste your refresh token

### Custom OAuth Client ID (optional)

The integration uses Claude Code's OAuth client ID by default. If you have your own Anthropic OAuth client ID, you can enter it during setup as a fallback in case the default is ever revoked.

## Configuration

After setup, click **Configure** on the integration to adjust:

- **Update interval** — How often to poll the API (default: 5 minutes, range: 1-30 minutes)

If your refresh token expires, use the **Reconfigure** option on the integration page to enter a new one without losing your entity history.

## Diagnostics

The integration supports Home Assistant's built-in diagnostics. Go to the integration page, click the three dots, and select **Download diagnostics**. Tokens are automatically redacted from the output.

## Requirements

- Home Assistant 2025.1.0 or newer
- A Claude Pro, Team, or Max subscription

## Security Notes

- Tokens are stored in Home Assistant's `.storage` directory in plaintext. This is standard for all HA OAuth integrations.
- The default OAuth client ID belongs to Claude Code. Anthropic could change or revoke it at any time. Use the custom client ID option if you need guaranteed stability.
- Diagnostics output automatically redacts `access_token`, `refresh_token`, and `client_id`.

## License

MIT
