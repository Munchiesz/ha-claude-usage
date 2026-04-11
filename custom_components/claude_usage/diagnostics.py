"""Diagnostics support for Claude Usage."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import ClaudeUsageConfigEntry

TO_REDACT_CONFIG = {"access_token", "refresh_token", "client_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClaudeUsageConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT_CONFIG),
        "options": dict(entry.options),
        "coordinator_data": coordinator.data,
    }
