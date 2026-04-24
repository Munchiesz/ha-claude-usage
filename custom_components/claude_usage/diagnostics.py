"""Diagnostics support for Claude Usage."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import ClaudeUsageConfigEntry

TO_REDACT_CONFIG = {"access_token", "refresh_token", "client_id"}

# Defensive allowlist for the usage API response. Today Anthropic returns only
# utilization numbers and reset timestamps, but if they ever enrich the payload
# with identifiers (org name, email, subscription id), we want those redacted
# by default rather than leaking into issue reports.
_USAGE_RESPONSE_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "five_hour",
        "seven_day",
        "extra_usage",
    }
)
_USAGE_RESPONSE_ALLOWED_SUBKEYS: frozenset[str] = frozenset(
    {
        "utilization",
        "resets_at",
        "is_enabled",
        "used_credits",
        "monthly_limit",
    }
)


def _filter_usage_data(data: Any) -> Any:
    """Strip unexpected keys from the usage response for diagnostics output."""
    if not isinstance(data, dict):
        return data
    filtered: dict[str, Any] = {}
    for key, value in data.items():
        if key not in _USAGE_RESPONSE_ALLOWED_KEYS:
            filtered[key] = "**UNKNOWN_REDACTED**"
            continue
        if isinstance(value, dict):
            filtered[key] = {
                sub_key: (
                    sub_value
                    if sub_key in _USAGE_RESPONSE_ALLOWED_SUBKEYS
                    else "**UNKNOWN_REDACTED**"
                )
                for sub_key, sub_value in value.items()
            }
        else:
            filtered[key] = value
    return filtered


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClaudeUsageConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT_CONFIG),
        "options": dict(entry.options),
        "coordinator_data": _filter_usage_data(coordinator.data),
    }
