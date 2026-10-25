"""One shared recovering client for the user's single Geeklink hub."""
import asyncio

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback

from .const import DOMAIN
from .protocol import Client, GeeklinkError, discover


def domain_data(hass):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {"clients": {}, "legacy_lock": asyncio.Lock(), "legacy_host": None}

        @callback
        def stop(_event):
            for client in hass.data[DOMAIN]["clients"].values():
                client.close()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    return hass.data[DOMAIN]


def get_client(hass, host, recover=False):
    data = domain_data(hass)
    clients = data["clients"]
    if recover and data.get("active_client") is not None:
        clients[host] = data["active_client"]
    if host not in clients:
        clients[host] = Client(host)
    client = clients[host]
    if recover:
        data["active_client"] = client
        client.auto_discover = True

        @callback
        def address_changed(old_host, new_host):
            clients[old_host] = clients[new_host] = client
            data["legacy_host"] = new_host
            persist_host(hass, client)

        client.on_host_changed = address_changed
    return client


@callback
def persist_host(hass, client):
    """Update the same entries; leave entry IDs, options and storage keys alone."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get("host") != client.host:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "host": client.host},
                unique_id=f"ipv4:{client.host}",
            )


async def legacy_client(hass, host=None):
    if host:
        return get_client(hass, host, recover=True)
    data = domain_data(hass)
    if data.get("active_client") is not None:
        return data["active_client"]
    async with data["legacy_lock"]:
        if data["legacy_host"] is None:
            hosts = await discover()
            if len(hosts) != 1:
                raise GeeklinkError("Expected one Geeklink hub. Add host: IPv4 to each YAML light if there are multiple hubs.")
            data["legacy_host"] = hosts[0]
    return get_client(hass, data["legacy_host"], recover=True)
