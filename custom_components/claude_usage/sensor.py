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
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
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


def _parse_timestamp(iso_ts: str | None) -> datetime | None:
    """Parse an ISO timestamp string into a datetime object."""
    if not iso_ts:
        return None
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, kw_only=True)
class ClaudeUsageSensorDescription(SensorEntityDescription):
    """Describe a Claude Usage sensor."""

    value_fn: Callable[[dict[str, Any]], StateType]
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]]


SENSOR_DESCRIPTIONS: tuple[ClaudeUsageSensorDescription, ...] = (
    ClaudeUsageSensorDescription(
        key="session_utilization",
        translation_key="session_utilization",
        name="Session Utilization",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
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
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
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
        state_class=SensorStateClass.TOTAL,
        icon="mdi:currency-usd",
        value_fn=lambda d: d.get("extra_usage", {}).get("used_credits"),
        extra_attrs_fn=lambda d: {
            "monthly_limit": d.get("extra_usage", {}).get("monthly_limit"),
            "resets_at": d.get("extra_usage", {}).get("resets_at", ""),
        },
    ),
    ClaudeUsageSensorDescription(
        key="extra_utilization",
        translation_key="extra_utilization",
        name="Extra Usage Utilization",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:credit-card-clock",
        value_fn=lambda d: d.get("extra_usage", {}).get("utilization"),
        extra_attrs_fn=lambda d: {
            "monthly_limit": d.get("extra_usage", {}).get("monthly_limit"),
            "used_credits": d.get("extra_usage", {}).get("used_credits"),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeUsageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Claude Usage sensors from a config entry."""
    coordinator: ClaudeUsageCoordinator = entry.runtime_data

    descriptions: list[ClaudeUsageSensorDescription] = list(SENSOR_DESCRIPTIONS)

    # Conditionally add extra usage sensors
    extra = coordinator.data.get("extra_usage") if coordinator.data else None
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
            # SERVICE hides the device from the "physical devices" dashboard
            # where a cloud subscription doesn't belong.
            entry_type=DeviceEntryType.SERVICE,
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
        if self.coordinator.data is None:
            return None
        return self.entity_description.extra_attrs_fn(self.coordinator.data)
