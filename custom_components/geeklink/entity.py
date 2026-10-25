"""Shared entity behavior; state is assumed, never measured."""
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .hub import legacy_client
from .protocol import GeeklinkError


class GeeklinkEntity(RestoreEntity):
    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, appliance, entry=None, host=None):
        self.appliance = appliance
        self.entry = entry
        self.host = host
        self._attr_name = appliance["name"]
        if entry:
            self._attr_unique_id = f"{entry.entry_id}:appliance:{appliance['id']}"
            self._attr_device_info = {
                "identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title,
                "manufacturer": "Geeklink", "model": "Local IR/RF hub",
            }
        # Original YAML entities did not expose unique_id, despite accepting it.
        # Leave that behavior unchanged so existing entity IDs remain stable.

    async def transmit(self, command):
        try:
            client = self.entry.runtime_data["client"] if self.entry else await legacy_client(self.hass, self.host)
            await client.send(self.appliance["codes"][command])
        except GeeklinkError as err:
            raise HomeAssistantError(str(err)) from err


class GeeklinkToggle(GeeklinkEntity):
    _attr_is_on = None

    @property
    def is_on(self):
        # Explicit property avoids cached ToggleEntity attributes being shadowed
        # by the shared RestoreEntity mixin in multiple inheritance.
        return self._attr_is_on

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) and state.state in ("on", "off"):
            self._attr_is_on = state.state == "on"

    async def async_turn_on(self, **kwargs):
        await self.transmit("on")
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.transmit("off")
        self._attr_is_on = False
        self.async_write_ha_state()
