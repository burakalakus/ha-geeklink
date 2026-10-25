"""Stateless power toggles and arbitrary remote buttons."""
from homeassistant.components.button import ButtonEntity
from .entity import GeeklinkEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(GeeklinkButton(a, entry) for a in entry.options.get("appliances", []) if a["kind"] == "button")


class GeeklinkButton(GeeklinkEntity, ButtonEntity):
    async def async_press(self):
        await self.transmit("press")
