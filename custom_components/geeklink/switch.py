"""UI-created switches."""
from homeassistant.components.switch import SwitchEntity
from .entity import GeeklinkToggle


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(GeeklinkSwitch(a, entry) for a in entry.options.get("appliances", []) if a["kind"] == "switch")


class GeeklinkSwitch(GeeklinkToggle, SwitchEntity):
    pass
