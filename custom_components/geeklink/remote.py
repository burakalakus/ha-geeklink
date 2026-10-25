"""Standard learn/send/delete actions for a named command library."""
import asyncio
from copy import deepcopy

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.components import persistent_notification
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .protocol import GeeklinkError


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([GeeklinkRemote(entry)])


def names(value):
    result = [value] if isinstance(value, str) else list(value or [])
    if not result or any(not isinstance(x, str) or not x.strip() for x in result):
        raise HomeAssistantError("Specify at least one non-empty command name")
    return result


class GeeklinkRemote(RemoteEntity):
    _attr_should_poll = False
    _attr_is_on = True
    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND

    def __init__(self, entry):
        self.entry = entry
        self.runtime = entry.runtime_data
        self._jobs = set()
        self._attr_unique_id = f"{entry.entry_id}:remote"
        self._attr_name = f"{entry.title} Remote"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}, "name": entry.title,
                                  "manufacturer": "Geeklink", "model": "Local IR/RF hub"}

    @property
    def extra_state_attributes(self):
        return {"saved_commands": {device: list(commands) for device, commands in self.runtime["commands"].items()}}

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_send_command(self, command, **kwargs):
        if not self._attr_is_on:
            raise HomeAssistantError("Enable the remote before sending commands")
        if kwargs.get("hold_secs", 0):
            raise HomeAssistantError("Hold duration is not supported by this protocol")
        device = kwargs.get("device", "default")
        saved = self.runtime["commands"].get(device, {})
        commands = names(command)
        if any(name not in saved for name in commands):
            raise HomeAssistantError(f"Unknown command for device {device}; learn it first")
        codes = [saved[name] for name in commands]
        repeats = kwargs.get("num_repeats", 1)
        delay = kwargs.get("delay_secs", 0.5)
        if not 1 <= repeats <= 20 or not 0 <= delay <= 10:
            raise HomeAssistantError("Use 1–20 repeats and a delay of 0–10 seconds")
        try:
            for repeat in range(repeats):
                for code in codes:
                    await self.runtime["client"].send(code)
                    if delay > 0.5:
                        await asyncio.sleep(delay - 0.5)
        except GeeklinkError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_learn_command(self, **kwargs):
        if kwargs.get("alternative"):
            raise HomeAssistantError("Alternative code sequences are not supported")
        commands = names(kwargs.get("command"))
        device = kwargs.get("device", "default")
        kind = kwargs.get("command_type", "ir")
        timeout = kwargs.get("timeout", 30)
        task = asyncio.current_task()
        self._jobs.add(task)
        notification_id = f"geeklink_learn_{self.entry.entry_id}"
        try:
            async with self.runtime["storage_lock"]:
                updated = deepcopy(self.runtime["commands"])
                for command in commands:
                    persistent_notification.async_create(self.hass,
                        f"Press {command} on the original remote for {device} within {timeout} seconds.",
                        title="Geeklink learning", notification_id=notification_id)
                    code = await self.runtime["client"].learn(kind, timeout)
                    updated.setdefault(device, {})[command] = code
                await self.runtime["store"].async_save(updated)
                self.runtime["commands"] = updated
                self.async_write_ha_state()
        except GeeklinkError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            self._jobs.discard(task)
            persistent_notification.async_dismiss(self.hass, notification_id)

    async def async_delete_command(self, **kwargs):
        commands = names(kwargs.get("command"))
        device = kwargs.get("device", "default")
        async with self.runtime["storage_lock"]:
            updated = deepcopy(self.runtime["commands"])
            for command in commands:
                updated.get(device, {}).pop(command, None)
            if device in updated and not updated[device]:
                del updated[device]
            await self.runtime["store"].async_save(updated)
            self.runtime["commands"] = updated
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        for job in list(self._jobs):
            job.cancel()
        if self._jobs:
            await asyncio.gather(*self._jobs, return_exceptions=True)
        await super().async_will_remove_from_hass()
