"""Geeklink local integration with UI learning and legacy YAML support."""
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PLATFORMS
from .hub import domain_data, get_client, persist_host
from .protocol import GeeklinkError


async def async_setup(hass, config):
    domain_data(hass)
    return True


async def async_setup_entry(hass, entry):
    client = get_client(hass, entry.data["host"], recover=True)
    try:
        await client.probe()
    except GeeklinkError as err:
        raise ConfigEntryNotReady(str(err)) from err
    persist_host(hass, client)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.commands")
    import asyncio
    entry.runtime_data = {
        "client": client, "store": store,
        "commands": await store.async_load() or {}, "storage_lock": asyncio.Lock(),
    }
    # Remove only UI appliance entities explicitly deleted through our options.
    active_ids = {f"{entry.entry_id}:appliance:{a['id']}" for a in entry.options.get("appliances", [])}
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.startswith(f"{entry.entry_id}:appliance:") and entity.unique_id not in active_ids:
            registry.async_remove(entity.entity_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass, entry):
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.commands").async_remove()
