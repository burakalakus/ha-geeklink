"""Open/close/optional stop, without invented position estimates."""
from homeassistant.components.cover import CoverEntity, CoverEntityFeature, CoverDeviceClass
from .entity import GeeklinkEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(GeeklinkCover(a, entry) for a in entry.options.get("appliances", []) if a["kind"] == "cover")


class GeeklinkCover(GeeklinkEntity, CoverEntity):
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_is_closed = None

    @property
    def is_closed(self):
        return self._attr_is_closed

    def __init__(self, appliance, entry):
        super().__init__(appliance, entry)
        self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if "stop" in appliance["codes"]:
            self._attr_supported_features |= CoverEntityFeature.STOP

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) and state.state in ("open", "closed"):
            self._attr_is_closed = state.state == "closed"

    async def async_open_cover(self, **kwargs):
        await self.transmit("open")
        self._attr_is_closed = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs):
        await self.transmit("close")
        self._attr_is_closed = True
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs):
        await self.transmit("stop")
        self._attr_is_closed = None
        self.async_write_ha_state()
