"""Integration tests on actual Core 2026.10.2 with simulated UDP hardware."""
import asyncio
from copy import deepcopy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeassistant import loader
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.setup import async_setup_component
from homeassistant.helpers import entity_registry, device_registry, area_registry
from custom_components.geeklink.config_flow import GeeklinkConfigFlow, GeeklinkOptionsFlow
from custom_components.geeklink.protocol import Client
from custom_components.geeklink.hub import domain_data
from custom_components.geeklink.const import command_names
from test_protocol import FakeHub, code


class HomeAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        shutil.copytree(Path(__file__).resolve().parents[1] / "custom_components", Path(self.temp.name) / "custom_components",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.hass = HomeAssistant(self.temp.name)
        self.hass.config.skip_pip = True
        self.hass.config_entries = ConfigEntries(self.hass, {})
        loader.async_setup(self.hass)
        await self.hass.config_entries.async_initialize()
        device_registry.async_setup(self.hass)
        await area_registry.async_load(self.hass)
        await device_registry.async_load(self.hass)
        await entity_registry.async_load(self.hass)
        self.transport, self.server = await asyncio.get_running_loop().create_datagram_endpoint(FakeHub, local_addr=("127.0.0.1", 0))
        self.client = Client("127.0.0.1", self.transport.get_extra_info("sockname")[1], timeout=0.05, delay=0.001)
        domain_data(self.hass)["clients"]["127.0.0.1"] = self.client
        await async_setup_component(self.hass, "persistent_notification", {})

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        self.client.close()
        self.transport.close()
        self.temp.cleanup()

    def entry(self, appliances=()):
        entry = ConfigEntry(version=1, minor_version=1, domain="geeklink", title="Test Geeklink",
            data={"host":"127.0.0.1"}, options={"appliances":list(appliances)}, source="user", unique_id="ipv4:127.0.0.1",
            discovery_keys=MappingProxyType({}), subentries_data=[])
        self.hass.config_entries._entries[entry.entry_id] = entry
        return entry

    def flow(self, entry):
        flow = GeeklinkOptionsFlow()
        flow.hass = self.hass
        flow.handler = entry.entry_id
        return flow

    async def test_user_flow(self):
        flow = GeeklinkConfigFlow()
        flow.hass = self.hass
        flow.context = {"source":"user"}
        result = await flow.async_step_user({"host":"127.0.0.1"})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["host"], "127.0.0.1")

    async def test_legacy_yaml_light(self):
        config = {"light":[{"platform":"geeklink", "name":"Legacy lamp", "unique_id":"old_yaml_id",
                            "host":"127.0.0.1", "command_on":code(), "command_off":code("ir")}]}
        self.assertTrue(await async_setup_component(self.hass,"light",config))
        await self.hass.async_block_till_done()
        self.assertIsNotNone(self.hass.states.get("light.legacy_lamp"))
        await self.hass.services.async_call("light","turn_on",{"entity_id":"light.legacy_lamp"},blocking=True)
        self.assertEqual(self.hass.states.get("light.legacy_lamp").state,"on")
        await self.hass.services.async_call("light","turn_off",{"entity_id":"light.legacy_lamp"},blocking=True)
        self.assertEqual(self.hass.states.get("light.legacy_lamp").state,"off")

    async def test_options_manager_save_reload_and_delete(self):
        entry = self.entry()
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        manager = self.hass.config_entries.options
        result = await manager.async_init(entry.entry_id)
        flow_id = result["flow_id"]
        await manager.async_configure(flow_id, {"next_step_id":"add"})
        await manager.async_configure(flow_id, {"name":"New button", "kind":"button", "signal":"rf", "stop":False})
        await manager.async_configure(flow_id, {"command":"press"})
        result = await manager.async_configure(flow_id, {})
        self.assertEqual(result["type"], "progress")
        await self.hass.async_block_till_done()
        result = await manager.async_configure(flow_id)
        # Core automatically advances the task completion to the review form.
        self.assertEqual(result["step_id"], "review")
        await manager.async_configure(flow_id, {"action":"accept"})
        result = await manager.async_configure(flow_id, {"command":"save"})
        self.assertEqual(result["type"], "create_entry")
        await self.hass.async_block_till_done()
        self.assertEqual(len(entry.options["appliances"]), 1)
        button_id = next(s.entity_id for s in self.hass.states.async_all() if s.entity_id.startswith("button."))
        await self.hass.services.async_call("button","press",{"entity_id":button_id},blocking=True)
        result = await manager.async_init(entry.entry_id)
        flow_id = result["flow_id"]
        await manager.async_configure(flow_id, {"next_step_id":"remove"})
        await manager.async_configure(flow_id, {"appliance":entry.options["appliances"][0]["id"]})
        await manager.async_configure(flow_id, {})
        await self.hass.async_block_till_done()
        self.assertIsNone(entity_registry.async_get(self.hass).async_get(button_id))

    async def test_cancel_draft_leaves_entry_unchanged(self):
        entry = self.entry()
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        manager = self.hass.config_entries.options
        result = await manager.async_init(entry.entry_id)
        fid = result["flow_id"]
        await manager.async_configure(fid,{"next_step_id":"add"})
        await manager.async_configure(fid,{"name":"Unsaved", "kind":"button", "signal":"rf", "stop":False})
        await manager.async_configure(fid,{"command":"press"})
        self.server.learning_silent = True
        await manager.async_configure(fid,{})
        manager.async_abort(fid)
        await self.hass.async_block_till_done()
        self.assertEqual(list(entry.options["appliances"]),[])
        self.assertFalse(self.client._sockets)

    async def test_ip_recovery_preserves_entry_entities_commands_and_yaml_client(self):
        from custom_components.geeklink.hub import legacy_client, get_client
        appliance = {"id":"same", "name":"Existing button", "kind":"button", "signal":"rf", "codes":{"press":code()}}
        entry = self.entry([appliance])
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        await self.hass.async_block_till_done()
        entry_id = entry.entry_id
        options = deepcopy(dict(entry.options))
        states_before = {s.entity_id for s in self.hass.states.async_all()}
        entry.runtime_data["commands"] = {"tv":{"mute":code("ir")}}
        await entry.runtime_data["store"].async_save(entry.runtime_data["commands"])
        transport, new_hub = await asyncio.get_running_loop().create_datagram_endpoint(
            FakeHub, local_addr=("127.0.0.2",self.client.port))
        try:
            self.server.silent = True
            with patch("custom_components.geeklink.protocol.discover",AsyncMock(return_value=["127.0.0.2"])):
                await self.client.send(code())
            self.assertEqual(entry.entry_id,entry_id)
            self.assertEqual(entry.data["host"],"127.0.0.2")
            self.assertEqual(entry.unique_id,"ipv4:127.0.0.2")
            self.assertEqual(dict(entry.options),options)
            self.assertEqual({s.entity_id for s in self.hass.states.async_all()},states_before)
            self.assertIs(await legacy_client(self.hass,"127.0.0.1"),self.client)
            self.assertIs(await legacy_client(self.hass),self.client)
            self.assertIs(get_client(self.hass,"127.0.0.2"),self.client)
            self.assertTrue(await self.hass.config_entries.async_reload(entry_id))
            self.assertEqual(entry.runtime_data["commands"]["tv"]["mute"],code("ir"))
        finally:
            transport.close()

    async def test_entry_setup_recovers_stale_saved_ip(self):
        entry = self.entry()
        transport, new_hub = await asyncio.get_running_loop().create_datagram_endpoint(
            FakeHub,local_addr=("127.0.0.2",self.client.port))
        self.server.silent = True
        try:
            with patch("custom_components.geeklink.protocol.discover",AsyncMock(return_value=["127.0.0.2"])):
                self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
            self.assertEqual(entry.data["host"],"127.0.0.2")
        finally:
            transport.close()

    async def test_wizard_learn_save(self):
        entry = self.entry()
        flow = self.flow(entry)
        await flow.async_step_init()
        await flow.async_step_add({"name":"Test button", "kind":"button", "signal":"rf", "stop":False})
        await flow.async_step_commands({"command":"press"})
        result = await flow.async_step_ready({})
        self.assertEqual(result["type"], "progress")
        await flow._task
        result = await flow.async_step_learning()
        self.assertEqual(result["step_id"], "review")
        await flow.async_step_review({"action":"test"})
        await flow.async_step_review({"action":"accept"})
        result = await flow.async_step_commands({"command":"save"})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["appliances"][0]["codes"]["press"], code())
        self.assertEqual(list(entry.options["appliances"]), [])

    async def test_wizard_missing_and_identical_codes(self):
        flow = self.flow(self.entry())
        await flow.async_step_init()
        await flow.async_step_add({"name":"Lamp", "kind":"light", "signal":"rf"})
        result = await flow.async_step_commands({"command":"save"})
        self.assertEqual(result["errors"]["base"], "missing_commands")
        flow._draft["codes"] = {"on":code(), "off":code()}
        result = await flow.async_step_commands({"command":"save"})
        self.assertEqual(result["errors"]["base"], "identical_codes")

    async def test_failed_relearn_preserves_saved_data(self):
        original = {"id":"a", "name":"Button", "kind":"button", "signal":"rf", "codes":{"press":code()}}
        entry = self.entry([original])
        flow = self.flow(entry)
        await flow.async_step_init()
        await flow.async_step_edit({"appliance":"a"})
        await flow.async_step_commands({"command":"press"})
        self.server.silent = True
        await flow.async_step_ready({})
        await flow._task
        await flow.async_step_learning()
        result = await flow.async_step_review()
        self.assertEqual(result["errors"]["base"], "learning_failed")
        self.assertEqual(entry.options["appliances"][0]["codes"]["press"], code())

    async def test_full_entry_setup_entities_actions_and_reload(self):
        appliances = []
        for kind in ("light","switch","cover","button"):
            a = {"id":kind, "name":f"Test {kind}", "kind":kind, "signal":"rf"}
            a["codes"] = {n:code() for n in command_names(a)}
            appliances.append(a)
        entry = self.entry(appliances)
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        await self.hass.async_block_till_done()
        states = self.hass.states.async_all()
        ids = {s.entity_id for s in states}
        for kind in ("light","switch","cover","button"):
            self.assertIn(f"{kind}.test_geeklink_test_{kind}", ids)
        await self.hass.services.async_call("light","turn_on",{"entity_id":"light.test_geeklink_test_light"},blocking=True)
        self.assertEqual(self.hass.states.get("light.test_geeklink_test_light").state,"on")
        await self.hass.services.async_call("cover","close_cover",{"entity_id":"cover.test_geeklink_test_cover"},blocking=True)
        self.assertEqual(self.hass.states.get("cover.test_geeklink_test_cover").state,"closed")
        remote_id = next(x for x in ids if x.startswith("remote."))
        await self.hass.services.async_call("remote","learn_command",{"entity_id":remote_id,"device":"tv","command":"mute","command_type":"ir"},blocking=True)
        await self.hass.services.async_call("remote","send_command",{"entity_id":remote_id,"device":"tv","command":"mute"},blocking=True)
        self.assertTrue(await self.hass.config_entries.async_reload(entry.entry_id))
        await self.hass.async_block_till_done()
        self.assertIn("mute",entry.runtime_data["commands"]["tv"])
        await self.hass.services.async_call("remote","delete_command",{"entity_id":remote_id,"device":"tv","command":"mute"},blocking=True)
        self.assertNotIn("tv",entry.runtime_data["commands"])


if __name__ == "__main__":
    unittest.main()
