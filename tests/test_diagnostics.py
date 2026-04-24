"""Tests for the Claude Usage diagnostics output."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.claude_usage.diagnostics import (
    TO_REDACT_CONFIG,
    _filter_usage_data,
    async_get_config_entry_diagnostics,
)
from custom_components.claude_usage.const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
)


# --- async_get_config_entry_diagnostics ---


@pytest.mark.asyncio
async def test_diagnostics_redacts_known_token_fields() -> None:
    """H6: diagnostics must redact access_token, refresh_token, and client_id.

    Regression test — if someone renames a field or reorganizes the entry data,
    we want this test to fail loud rather than silently start leaking tokens
    into issue reports.
    """
    coordinator = MagicMock()
    coordinator.data = {
        "five_hour": {"utilization": 44.0, "resets_at": "2026-04-11T18:00:00Z"},
    }

    entry = MagicMock()
    entry.data = {
        CONF_ACCESS_TOKEN: "secret-access-token",
        CONF_REFRESH_TOKEN: "secret-refresh-token",
        CONF_CLIENT_ID: "secret-client-id",
        "non_secret": "visible",
    }
    entry.options = {"scan_interval": 300}
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    # None of the three secret values should appear anywhere in the output.
    rendered = repr(result)
    assert "secret-access-token" not in rendered
    assert "secret-refresh-token" not in rendered
    assert "secret-client-id" not in rendered
    # Non-secret fields are preserved.
    assert result["config_entry"]["non_secret"] == "visible"
    assert result["options"] == {"scan_interval": 300}


def test_to_redact_config_covers_all_token_like_fields() -> None:
    """Regression guard: the redaction set must cover every token-ish field
    we store on the config entry. Anyone who adds a new token field must
    remember to update this set."""
    assert CONF_ACCESS_TOKEN in TO_REDACT_CONFIG
    assert CONF_REFRESH_TOKEN in TO_REDACT_CONFIG
    assert CONF_CLIENT_ID in TO_REDACT_CONFIG


# --- _filter_usage_data (M8: defensive whitelist) ---


def test_filter_usage_data_passes_known_keys() -> None:
    """Known keys and subkeys are passed through unchanged."""
    data = {
        "five_hour": {"utilization": 44.0, "resets_at": "2026-04-11T18:00:00Z"},
        "seven_day": {"utilization": 16.28, "resets_at": "2026-04-14T00:00:00Z"},
        "extra_usage": {
            "is_enabled": True,
            "used_credits": 5.25,
            "monthly_limit": 100.0,
            "utilization": 5.25,
        },
    }

    filtered = _filter_usage_data(data)

    assert filtered == data


def test_filter_usage_data_redacts_unknown_top_level_keys() -> None:
    """M8: if Anthropic enriches the payload with a new field (e.g. email,
    subscription_id), diagnostics redacts it instead of leaking it."""
    data = {
        "five_hour": {"utilization": 44.0, "resets_at": "2026-04-11T18:00:00Z"},
        "user_email": "user@example.com",
        "organization_id": "org-12345",
    }

    filtered = _filter_usage_data(data)

    assert filtered["five_hour"] == data["five_hour"]
    assert filtered["user_email"] == "**UNKNOWN_REDACTED**"
    assert filtered["organization_id"] == "**UNKNOWN_REDACTED**"


def test_filter_usage_data_redacts_unknown_nested_keys() -> None:
    """A new subkey under a known section (e.g. five_hour.user_tier) is also
    redacted until explicitly whitelisted."""
    data = {
        "five_hour": {
            "utilization": 44.0,
            "resets_at": "2026-04-11T18:00:00Z",
            "user_tier_id": "pii-data",
        },
    }

    filtered = _filter_usage_data(data)

    assert filtered["five_hour"]["utilization"] == 44.0
    assert filtered["five_hour"]["user_tier_id"] == "**UNKNOWN_REDACTED**"


def test_filter_usage_data_handles_none() -> None:
    """None (no coordinator.data yet) is returned as-is."""
    assert _filter_usage_data(None) is None


def test_filter_usage_data_handles_non_dict() -> None:
    """Non-dict input (unexpected shape) is returned as-is rather than crashing."""
    assert _filter_usage_data("some-string") == "some-string"
    assert _filter_usage_data(42) == 42
