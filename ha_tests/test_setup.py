"""Integration tests: boot nea_sg_weather inside a real Home Assistant instance.

These tests use pytest-homeassistant-custom-component which spins up a
lightweight but real HA core.  All NEA API HTTP calls are intercepted by the
mock_nea_api fixture (HA's aioclient_mock), so no network access is required.

Run with:
    pytest ha_tests/ -v
"""
from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nea_sg_weather.const import DOMAIN

# ---------------------------------------------------------------------------
# Config entry data fixtures
# ---------------------------------------------------------------------------

WEATHER_ONLY = {
    "name": "Singapore Weather",
    "weather": True,
    "sensor": False,
    "scan_interval": 15,
    "timeout": 60,
}

WITH_AREA_SENSORS = {
    "name": "Singapore Weather",
    "weather": True,
    "sensor": True,
    "scan_interval": 15,
    "timeout": 60,
    "sensors": {
        "prefix": "Singapore Weather",
        "areas": ["Ang Mo Kio", "Bedok"],
        "region": False,
        "rain": False,
    },
}

WITH_REGION_SENSORS = {
    "name": "Singapore Weather",
    "weather": False,
    "sensor": True,
    "scan_interval": 15,
    "timeout": 60,
    "sensors": {
        "prefix": "Singapore Weather",
        "areas": [],
        "region": True,
        "rain": False,
    },
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _load(hass: HomeAssistant, config: dict) -> MockConfigEntry:
    """Create, register, and set up a config entry; return it."""
    entry = MockConfigEntry(domain=DOMAIN, data=config, title=config["name"])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# Entry lifecycle
# ---------------------------------------------------------------------------

async def test_entry_loads_successfully(hass: HomeAssistant, mock_nea_api):
    """Config entry reaches LOADED state."""
    entry = await _load(hass, WEATHER_ONLY)
    assert entry.state == ConfigEntryState.LOADED


async def test_coordinator_stored_in_hass_data(hass: HomeAssistant, mock_nea_api):
    """Coordinator is accessible via hass.data after setup."""
    entry = await _load(hass, WEATHER_ONLY)
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]


async def test_entry_unloads_successfully(hass: HomeAssistant, mock_nea_api):
    """Config entry transitions to NOT_LOADED after unload."""
    entry = await _load(hass, WEATHER_ONLY)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.NOT_LOADED


async def test_unload_removes_coordinator_from_hass_data(hass: HomeAssistant, mock_nea_api):
    """Coordinator is removed from hass.data after unload."""
    entry = await _load(hass, WEATHER_ONLY)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


# ---------------------------------------------------------------------------
# Weather entity
# ---------------------------------------------------------------------------

# The weather entity is the main feature of the config entry's device, so it
# takes the device's name, and its entity ID is derived from that.
WEATHER_ENTITY_ID = "weather.singapore_weather"


async def test_weather_entity_registered(hass: HomeAssistant, mock_nea_api):
    """A weather entity appears in the state machine after setup."""
    await _load(hass, WEATHER_ONLY)
    states = hass.states.async_all("weather")
    assert len(states) == 1
    assert states[0].entity_id == WEATHER_ENTITY_ID
    assert states[0].name == "Singapore Weather"


async def test_weather_entity_has_temperature_attribute(hass: HomeAssistant, mock_nea_api):
    """Weather entity exposes a numeric temperature."""
    await _load(hass, WEATHER_ONLY)
    state = hass.states.get(WEATHER_ENTITY_ID)
    assert state is not None
    temp = state.attributes.get("temperature")
    assert isinstance(temp, (int, float))


async def test_weather_entity_condition_is_valid(hass: HomeAssistant, mock_nea_api):
    """Weather entity condition is a recognised HA weather state string."""
    await _load(hass, WEATHER_ONLY)
    state = hass.states.get(WEATHER_ENTITY_ID)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_weather_entity_humidity_attribute(hass: HomeAssistant, mock_nea_api):
    """Weather entity exposes humidity."""
    await _load(hass, WEATHER_ONLY)
    state = hass.states.get(WEATHER_ENTITY_ID)
    humidity = state.attributes.get("humidity")
    assert isinstance(humidity, (int, float))


# ---------------------------------------------------------------------------
# Sensor entities
# ---------------------------------------------------------------------------

async def test_area_sensor_entities_registered(hass: HomeAssistant, mock_nea_api):
    """Area sensor entities appear in the state machine."""
    await _load(hass, WITH_AREA_SENSORS)
    names = {s.name for s in hass.states.async_all("sensor")}
    assert any("Ang Mo Kio" in name for name in names)
    assert any("Bedok" in name for name in names)


async def test_region_sensor_entities_registered(hass: HomeAssistant, mock_nea_api):
    """Region sensor entities (West/East/Central/South/North) appear in the state machine."""
    await _load(hass, WITH_REGION_SENSORS)
    names = {s.name for s in hass.states.async_all("sensor")}
    regions = ("West", "East", "Central", "South", "North")
    assert any(region in name for name in names for region in regions)


async def test_uv_sensor_has_value_without_weather_entity(hass: HomeAssistant, mock_nea_api):
    """The UV sensor is polled even when only region sensors are configured."""
    await _load(hass, WITH_REGION_SENSORS)
    uv = hass.states.get("sensor.singapore_weather_uv")
    assert uv is not None
    assert uv.state == "5"
    # Distinct from the 24-hour forecast timestamp (12:00) in the fixtures
    assert uv.attributes["Updated at"] == "2024-01-01T11:00:00+08:00"


async def test_pm25_sensor_has_value_without_weather_entity(hass: HomeAssistant, mock_nea_api):
    """Region PM2.5 sensors are polled when only region sensors are configured."""
    await _load(hass, WITH_REGION_SENSORS)
    pm25 = hass.states.get("sensor.singapore_weather_pm25central")
    assert pm25 is not None
    assert pm25.state == "20"
    assert pm25.attributes["Updated at"] == "2024-01-01T11:30:00+08:00"


async def test_pollutant_sensors_registered_but_disabled(hass: HomeAssistant, mock_nea_api):
    """Pollutant concentration sensors exist for every pollutant and region, disabled by default."""
    await _load(hass, WITH_REGION_SENSORS)
    ent_reg = er.async_get(hass)
    for pollutant in ("pm25_24h", "pm10_24h", "so2_24h", "o3_8h", "co_8h", "no2_1h"):
        for region in ("west", "east", "central", "south", "north"):
            entry = ent_reg.async_get(f"sensor.singapore_weather_{pollutant}_{region}")
            assert entry is not None, f"{pollutant} {region}"
            assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
            assert hass.states.get(entry.entity_id) is None


async def test_pollutant_sensor_values_when_enabled(hass: HomeAssistant, mock_nea_api):
    """Enabled pollutant sensors report NEA's concentration, unit and device class."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=WITH_REGION_SENSORS, title=WITH_REGION_SENSORS["name"]
    )
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    expected = {
        ("pm10_24h", "central"): ("28", "μg/m³", "pm10"),
        ("co_8h", "central"): ("0.7", "mg/m³", "carbon_monoxide"),
        ("no2_1h", "north"): ("28", "μg/m³", "nitrogen_dioxide"),
    }
    for pollutant, region in expected:
        ent_reg.async_get_or_create(
            "sensor", DOMAIN, f"Singapore Weather {pollutant} {region.capitalize()}",
            suggested_object_id=f"singapore_weather_{pollutant}_{region}",
            config_entry=entry, disabled_by=None,
        )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for (pollutant, region), (value, unit, device_class) in expected.items():
        state = hass.states.get(f"sensor.singapore_weather_{pollutant}_{region}")
        assert state is not None, f"{pollutant} {region}"
        assert state.state == value
        assert state.attributes["unit_of_measurement"] == unit
        assert state.attributes["device_class"] == device_class
        assert state.attributes["state_class"] == "measurement"
        assert state.attributes["Updated at"] == "2024-01-01T12:00:00+08:00"

    name = hass.states.get("sensor.singapore_weather_co_8h_central").name
    assert name == "Central Singapore CO (8-hour max)"


# ---------------------------------------------------------------------------
# Entity names and devices
# ---------------------------------------------------------------------------

async def test_friendly_names(hass: HomeAssistant, mock_nea_api):
    """Friendly names combine the device name with a short entity name."""
    await _load(hass, WITH_AREA_SENSORS)
    names = {
        "sensor.singapore_weather_ang_mo_kio": "Singapore Weather Ang Mo Kio",
        "sensor.singapore_weather_uv": "Singapore Weather UV index",
    }
    for entity_id, name in names.items():
        assert hass.states.get(entity_id).name == name


async def test_region_entities_belong_to_region_devices(hass: HomeAssistant, mock_nea_api):
    """Each region's entities sit on a child device of the main device."""
    entry = await _load(hass, WITH_REGION_SENSORS)
    names = {
        "sensor.singapore_weather_central": "Central Singapore Forecast",
        "sensor.singapore_weather_pm25west": "Western Singapore PM2.5 (1-hour)",
        "sensor.singapore_weather_psinorth": "Northern Singapore PSI (24-hour)",
    }
    for entity_id, name in names.items():
        assert hass.states.get(entity_id).name == name

    dev_reg = dr.async_get(hass)
    main = dev_reg.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert main.name == "Singapore Weather"
    assert main.entry_type is dr.DeviceEntryType.SERVICE

    entity = er.async_get(hass).async_get("sensor.singapore_weather_psinorth")
    region = dev_reg.async_get(entity.device_id)
    assert region.name == "Northern Singapore"
    assert region.parent_device_id == main.id


async def test_existing_device_is_renamed(hass: HomeAssistant, mock_nea_api):
    """An install from before this change keeps its device, under the new name."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=WITH_REGION_SENSORS, title=WITH_REGION_SENSORS["name"]
    )
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    old = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Weather forecast coordinator",
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device.id == old.id
    assert device.name == "Singapore Weather"
