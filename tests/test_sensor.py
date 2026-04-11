"""Tests for the Claude Usage sensor platform."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from homeassistant.components.sensor import SensorStateClass

from custom_components.claude_usage.sensor import (
    EXTRA_USAGE_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    _minutes_until,
    _parse_timestamp,
)

from .conftest import MOCK_USAGE_RESPONSE


# --- Helper function tests ---


def test_minutes_until_future() -> None:
    """Test _minutes_until with a future timestamp."""
    future = datetime.now(timezone.utc).replace(microsecond=0)
    # Use a timestamp 90 minutes from now
    from datetime import timedelta

    future = future + timedelta(minutes=90)
    iso = future.isoformat().replace("+00:00", "Z")

    result = _minutes_until(iso)

    assert result is not None
    assert 88 <= result <= 91


def test_minutes_until_past() -> None:
    """Test _minutes_until with a past timestamp returns 0."""
    assert _minutes_until("2020-01-01T00:00:00Z") == 0


def test_minutes_until_none() -> None:
    """Test _minutes_until with None returns None."""
    assert _minutes_until(None) is None


def test_minutes_until_empty_string() -> None:
    """Test _minutes_until with empty string returns None."""
    assert _minutes_until("") is None


def test_minutes_until_invalid() -> None:
    """Test _minutes_until with invalid string returns None."""
    assert _minutes_until("not-a-date") is None


def test_parse_timestamp_valid() -> None:
    """Test _parse_timestamp with a valid ISO timestamp."""
    result = _parse_timestamp("2026-04-11T18:00:00Z")

    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert result.year == 2026
    assert result.month == 4
    assert result.hour == 18


def test_parse_timestamp_none() -> None:
    """Test _parse_timestamp with None returns None."""
    assert _parse_timestamp(None) is None


def test_parse_timestamp_invalid() -> None:
    """Test _parse_timestamp with invalid string returns None."""
    assert _parse_timestamp("bad-date") is None


# --- Sensor description tests ---


def test_sensor_descriptions_count() -> None:
    """Test the expected number of base sensors."""
    assert len(SENSOR_DESCRIPTIONS) == 4


def test_extra_usage_descriptions_count() -> None:
    """Test the expected number of extra usage sensors."""
    assert len(EXTRA_USAGE_DESCRIPTIONS) == 2


def test_all_descriptions_have_unique_keys() -> None:
    """Test that all sensor keys are unique."""
    all_descs = [*SENSOR_DESCRIPTIONS, *EXTRA_USAGE_DESCRIPTIONS]
    keys = [d.key for d in all_descs]
    assert len(keys) == len(set(keys))


def test_session_utilization_value() -> None:
    """Test session_utilization sensor reads correct value."""
    desc = SENSOR_DESCRIPTIONS[0]
    assert desc.key == "session_utilization"
    assert desc.value_fn(MOCK_USAGE_RESPONSE) == 44.0


def test_weekly_utilization_value() -> None:
    """Test weekly_utilization sensor reads correct value."""
    desc = SENSOR_DESCRIPTIONS[2]
    assert desc.key == "weekly_utilization"
    assert desc.value_fn(MOCK_USAGE_RESPONSE) == 16.28


def test_session_resets_at_value() -> None:
    """Test session_resets_at sensor parses timestamp."""
    desc = SENSOR_DESCRIPTIONS[1]
    assert desc.key == "session_resets_at"
    result = desc.value_fn(MOCK_USAGE_RESPONSE)
    assert isinstance(result, datetime)


def test_weekly_resets_at_value() -> None:
    """Test weekly_resets_at sensor parses timestamp."""
    desc = SENSOR_DESCRIPTIONS[3]
    assert desc.key == "weekly_resets_at"
    result = desc.value_fn(MOCK_USAGE_RESPONSE)
    assert isinstance(result, datetime)


def test_extra_credits_used_value() -> None:
    """Test extra_credits_used sensor reads correct value."""
    desc = EXTRA_USAGE_DESCRIPTIONS[0]
    assert desc.key == "extra_credits_used"
    assert desc.value_fn(MOCK_USAGE_RESPONSE) == 5.25


def test_extra_utilization_value() -> None:
    """Test extra_utilization sensor reads correct value."""
    desc = EXTRA_USAGE_DESCRIPTIONS[1]
    assert desc.key == "extra_utilization"
    assert desc.value_fn(MOCK_USAGE_RESPONSE) == 5.25


def test_extra_credits_used_is_total_state_class() -> None:
    """Test extra_credits_used uses TOTAL state class for cumulative values."""
    desc = EXTRA_USAGE_DESCRIPTIONS[0]
    assert desc.state_class == SensorStateClass.TOTAL


def test_utilization_sensors_have_display_precision() -> None:
    """Test that all utilization sensors have suggested_display_precision=1."""
    utilization_sensors = [
        d for d in (*SENSOR_DESCRIPTIONS, *EXTRA_USAGE_DESCRIPTIONS)
        if d.native_unit_of_measurement == "%"
    ]
    assert len(utilization_sensors) == 3  # session, weekly, extra
    for desc in utilization_sensors:
        assert desc.suggested_display_precision == 1, (
            f"{desc.key} missing suggested_display_precision"
        )


def test_value_fn_handles_missing_data() -> None:
    """Test that value functions return None for empty API data."""
    empty_data: dict = {}
    for desc in (*SENSOR_DESCRIPTIONS, *EXTRA_USAGE_DESCRIPTIONS):
        result = desc.value_fn(empty_data)
        assert result is None, f"{desc.key} should return None for empty data"


def test_extra_attrs_fn_handles_missing_data() -> None:
    """Test that extra attribute functions handle empty data gracefully."""
    empty_data: dict = {}
    for desc in (*SENSOR_DESCRIPTIONS, *EXTRA_USAGE_DESCRIPTIONS):
        if desc.extra_attrs_fn is not None:
            result = desc.extra_attrs_fn(empty_data)
            assert isinstance(result, dict), (
                f"{desc.key} extra_attrs_fn should return a dict"
            )


def test_session_utilization_extra_attrs() -> None:
    """Test session_utilization extra attributes contain expected keys."""
    desc = SENSOR_DESCRIPTIONS[0]
    attrs = desc.extra_attrs_fn(MOCK_USAGE_RESPONSE)
    assert "resets_at" in attrs
    assert "minutes_until_reset" in attrs
    assert attrs["resets_at"] == "2026-04-11T18:00:00Z"
