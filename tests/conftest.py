"""Shared fixtures for Claude Usage tests.

Mocks the homeassistant package so tests run without a full HA installation.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _stub_module(name: str, attrs: dict[str, Any] | None = None) -> ModuleType:
    """Create a stub module and register it in sys.modules."""
    mod = ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# --- Stub all homeassistant imports before importing integration code ---


class _ConfigEntryAuthFailed(Exception):
    pass


class _UpdateFailed(Exception):
    pass


class _DataUpdateCoordinator:
    def __init__(self, hass, logger, *, config_entry=None, name="", update_interval=None):
        self.hass = hass
        self.logger = logger
        self.config_entry = config_entry
        self.name = name
        self.update_interval = update_interval
        self.data = None

    def __class_getitem__(cls, item):
        return cls


class _CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls


class _SensorEntity:
    pass


class _SensorStateClass:
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class _SensorDeviceClass:
    TIMESTAMP = "timestamp"


@dataclass(frozen=True, kw_only=True)
class _SensorEntityDescription:
    key: str = ""
    name: str | None = None
    native_unit_of_measurement: str | None = None
    state_class: str | None = None
    device_class: str | None = None
    icon: str | None = None
    suggested_display_precision: int | None = None
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    translation_key: str | None = None


class _ConfigEntry:
    def __getitem__(self, item):
        return getattr(self, item)


class _ConfigFlow:
    domain = None

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain


class _ConfigFlowResult:
    pass


class _OptionsFlow:
    pass


class _DeviceInfo:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Platform:
    SENSOR = "sensor"


def _callback(fn):
    return fn


# Register stubs
_stub_module("homeassistant")
_stub_module("homeassistant.const", {"Platform": _Platform})
_stub_module("homeassistant.core", {
    "HomeAssistant": MagicMock,
    "callback": _callback,
})
_stub_module("homeassistant.exceptions", {
    "ConfigEntryAuthFailed": _ConfigEntryAuthFailed,
})
_stub_module("homeassistant.config_entries", {
    "ConfigEntry": _ConfigEntry,
    "ConfigFlow": _ConfigFlow,
    "ConfigFlowResult": _ConfigFlowResult,
    "OptionsFlow": _OptionsFlow,
    "SOURCE_RECONFIGURE": "reconfigure",
})
_stub_module("homeassistant.helpers")
_stub_module("homeassistant.helpers.aiohttp_client", {
    "async_get_clientsession": MagicMock(),
})
_stub_module("homeassistant.helpers.update_coordinator", {
    "DataUpdateCoordinator": _DataUpdateCoordinator,
    "CoordinatorEntity": _CoordinatorEntity,
    "UpdateFailed": _UpdateFailed,
})
_stub_module("homeassistant.helpers.device_registry", {
    "DeviceInfo": _DeviceInfo,
})
_stub_module("homeassistant.helpers.entity_platform", {
    "AddConfigEntryEntitiesCallback": MagicMock,
})
_stub_module("homeassistant.helpers.typing", {
    "StateType": Any,
})
_stub_module("homeassistant.helpers.config_validation", {
    "positive_int": int,
})
_stub_module("homeassistant.components")
_stub_module("homeassistant.components.sensor", {
    "SensorDeviceClass": _SensorDeviceClass,
    "SensorEntity": _SensorEntity,
    "SensorEntityDescription": _SensorEntityDescription,
    "SensorStateClass": _SensorStateClass,
})

# --- Now import integration code ---
import voluptuous  # noqa: E402 - ensure available

import pytest  # noqa: E402

from custom_components.claude_usage.const import (  # noqa: E402
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)


# --- Fixtures & helpers ---

MOCK_CONFIG_DATA: dict[str, Any] = {
    CONF_ACCESS_TOKEN: "test-access-token",
    CONF_REFRESH_TOKEN: "test-refresh-token",
    CONF_EXPIRES_AT: time.time() + 28800,
}

MOCK_USAGE_RESPONSE: dict[str, Any] = {
    "five_hour": {
        "utilization": 44.0,
        "resets_at": "2026-04-11T18:00:00Z",
    },
    "seven_day": {
        "utilization": 16.28,
        "resets_at": "2026-04-14T00:00:00Z",
    },
    "extra_usage": {
        "is_enabled": True,
        "used_credits": 5.25,
        "monthly_limit": 100.0,
        "utilization": 5.25,
    },
}

MOCK_TOKEN_RESPONSE: dict[str, Any] = {
    "access_token": "new-access-token",
    "refresh_token": "new-refresh-token",
    "expires_in": 28800,
}


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = dict(MOCK_CONFIG_DATA)
    entry.options = {}
    return entry


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


def create_mock_response(
    status: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> AsyncMock:
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.headers = headers or {}
    resp.json = AsyncMock(return_value=json_data or {})
    resp.raise_for_status = MagicMock()
    if status >= 400:
        from aiohttp import ClientResponseError

        resp.raise_for_status.side_effect = ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=status,
        )
    # Support async context manager
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp
