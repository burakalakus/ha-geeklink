"""Geeklink lights, with backwards-compatible YAML loading."""
import probatio as vol

from homeassistant.components.light import LightEntity, ColorMode, PLATFORM_SCHEMA
from homeassistant.helpers import config_validation as cv

from .entity import GeeklinkToggle
from .protocol import GeeklinkError, ipv4, validate_code


def code_validator(value):
    try:
        return validate_code(value)
    except GeeklinkError as err:
        raise vol.Invalid(str(err)) from err


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required("name"): cv.string,
    vol.Required("command_on"): code_validator,
    vol.Required("command_off"): code_validator,
    vol.Optional("unique_id"): cv.string,
    vol.Optional("host"): ipv4,
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    appliance = {"name": config["name"], "codes": {"on": config["command_on"], "off": config["command_off"]}}
    async_add_entities([GeeklinkLight(appliance, host=config.get("host"))])


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(GeeklinkLight(a, entry) for a in entry.options.get("appliances", []) if a["kind"] == "light")


class GeeklinkLight(GeeklinkToggle, LightEntity):
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
