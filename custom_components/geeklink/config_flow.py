"""Hub setup and a transactional learn/test/save appliance wizard."""
import asyncio
import logging
from copy import deepcopy
from uuid import uuid4

import probatio as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, KINDS, LEARN_TIMEOUT, command_names
from .hub import get_client
from .protocol import GeeklinkError, discover, ipv4

_LOGGER = logging.getLogger(__name__)


class GeeklinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                host = user_input.get("host", "").strip()
                if not host:
                    hosts = await discover()
                    if not hosts:
                        raise GeeklinkError("No hubs found")
                    self._hosts = hosts
                    return await self.async_step_select_hub()
                return await self._finish(ipv4(host))
            except ValueError:
                errors["base"] = "invalid_host"
            except GeeklinkError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Optional("host", default=""): str,
        }), errors=errors)

    async def async_step_select_hub(self, user_input=None):
        errors = {}
        if user_input:
            try:
                return await self._finish(user_input["host"])
            except GeeklinkError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="select_hub", data_schema=vol.Schema({
            vol.Required("host"): vol.In(self._hosts),
        }), errors=errors)

    async def _finish(self, host):
        # The original protocol does not supply a verified stable hardware ID.
        # Use IP-based duplicate detection and document DHCP reservation.
        await self.async_set_unique_id(f"ipv4:{host}")
        self._abort_if_unique_id_configured()
        await get_client(self.hass, host).probe()
        return self.async_create_entry(title=f"Geeklink {host}", data={"host": host})

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input:
            try:
                host = ipv4(user_input["host"])
                for other in self.hass.config_entries.async_entries(DOMAIN):
                    if other.entry_id != entry.entry_id and other.data["host"] == host:
                        return self.async_abort(reason="already_configured")
                await get_client(self.hass, host).probe()
            except ValueError:
                errors["base"] = "invalid_host"
            except GeeklinkError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(entry, unique_id=f"ipv4:{host}")
                return self.async_update_reload_and_abort(entry, data_updates={"host": host})
        return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema({
            vol.Required("host", default=entry.data["host"]): str,
        }), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GeeklinkOptionsFlow()


class GeeklinkOptionsFlow(config_entries.OptionsFlowWithReload):
    def __init__(self):
        self._task = None
        self._draft = None
        self._pending = None
        self._error = None

    async def async_step_init(self, user_input=None):
        self._original = deepcopy(dict(self.config_entry.options))
        self._options = deepcopy(self._original)
        self._options.setdefault("appliances", [])
        return self.async_show_menu(step_id="init", menu_options=["add", "edit", "remove"])

    @property
    def client(self):
        return get_client(self.hass, self.config_entry.data["host"])

    async def async_step_add(self, user_input=None):
        errors = {}
        if user_input:
            name = user_input["name"].strip()
            if not name:
                errors["base"] = "invalid_name"
            else:
                self._draft = dict(user_input, name=name, id=uuid4().hex, codes={})
                return await self.async_step_commands()
        return self.async_show_form(step_id="add", errors=errors, data_schema=vol.Schema({
            vol.Required("name"): str,
            vol.Required("kind", default="switch"): vol.In(KINDS),
            vol.Required("signal", default="rf"): vol.In({"ir": "Infrared", "rf": "RF 433 MHz"}),
            vol.Optional("stop", default=False): bool,
        }))

    async def _select(self, step, user_input):
        appliances = self._options["appliances"]
        if not appliances:
            return self.async_abort(reason="no_appliances")
        if user_input:
            self._draft = deepcopy(next(a for a in appliances if a["id"] == user_input["appliance"]))
            if step == "remove":
                return await self.async_step_confirm_remove()
            return await self.async_step_commands()
        choices = {a["id"]: f"{a['name']} ({a['kind']})" for a in appliances}
        return self.async_show_form(step_id=step, data_schema=vol.Schema({
            vol.Required("appliance"): vol.In(choices),
        }))

    async def async_step_edit(self, user_input=None):
        return await self._select("edit", user_input)

    async def async_step_remove(self, user_input=None):
        return await self._select("remove", user_input)

    async def async_step_confirm_remove(self, user_input=None):
        if user_input is not None:
            self._options["appliances"] = [a for a in self._options["appliances"] if a["id"] != self._draft["id"]]
            return self._commit()
        return self.async_show_form(step_id="confirm_remove", data_schema=vol.Schema({}),
                                    description_placeholders={"name": self._draft["name"]})

    async def async_step_commands(self, user_input=None):
        errors = {}
        if user_input:
            action = user_input["command"]
            if action == "save":
                if any(name not in self._draft["codes"] for name in command_names(self._draft)):
                    errors["base"] = "missing_commands"
                else:
                    # Do not silently turn one toggle code into separate on/off.
                    codes = self._draft["codes"]
                    if self._draft["kind"] in ("light", "switch") and codes["on"] == codes["off"]:
                        errors["base"] = "identical_codes"
                    else:
                        self._options["appliances"] = [a for a in self._options["appliances"] if a["id"] != self._draft["id"]]
                        self._options["appliances"].append(deepcopy(self._draft))
                        return self._commit()
            else:
                self._command = action
                self._pending = None
                self._error = None
                return await self.async_step_ready()
        choices = {name: f"{name.upper()} — {'learned; select to relearn' if name in self._draft['codes'] else 'not learned'}"
                   for name in command_names(self._draft)}
        choices["save"] = "Save appliance"
        return self.async_show_form(step_id="commands", errors=errors,
            description_placeholders={"name": self._draft["name"]},
            data_schema=vol.Schema({vol.Required("command"): vol.In(choices)}))

    async def async_step_ready(self, user_input=None):
        if user_input is not None:
            self._task = None
            return await self.async_step_learning()
        return self.async_show_form(step_id="ready", data_schema=vol.Schema({}),
            description_placeholders={"command": self._command.upper(), "name": self._draft["name"]})

    async def _learn(self):
        try:
            self._pending = await self.client.learn(self._draft["signal"], LEARN_TIMEOUT)
            self._error = None
        except GeeklinkError as err:
            _LOGGER.warning("Geeklink learning failed: %s", err)
            self._pending = None
            self._error = "learning_failed"

    async def async_step_learning(self, user_input=None):
        if self._task is None:
            self._task = self.hass.async_create_task(self._learn())
        if not self._task.done():
            return self.async_show_progress(step_id="learning", progress_action="learning",
                progress_task=self._task,
                description_placeholders={"command": self._command.upper(), "name": self._draft["name"]})
        self._task.result()
        self._task = None
        return self.async_show_progress_done(next_step_id="review")

    async def async_step_review(self, user_input=None):
        errors = {"base": self._error} if self._error else {}
        message = "Code captured. Test it, then accept it." if self._pending else "No valid code captured. Retry learning."
        if user_input:
            action = user_input["action"]
            if action == "retry":
                self._pending = None
                self._error = None
                return await self.async_step_ready()
            if action == "back":
                return await self.async_step_commands()
            if action == "accept" and self._pending:
                self._draft["codes"][self._command] = self._pending
                return await self.async_step_commands()
            if action == "test" and self._pending:
                try:
                    await self.client.send(self._pending)
                    message = "Command sent. Check the appliance physically; its state cannot be confirmed by the hub reply."
                except GeeklinkError:
                    errors["base"] = "cannot_connect"
        choices = {"retry": "Learn again", "back": "Back without replacing this command"}
        if self._pending:
            choices = {"test": "Test (operates the appliance)", "accept": "Accept this code", **choices}
        return self.async_show_form(step_id="review", errors=errors,
            description_placeholders={"message": message, "command": self._command.upper()},
            data_schema=vol.Schema({vol.Required("action"): vol.In(choices)}))

    def _commit(self):
        if dict(self.config_entry.options) != self._original:
            return self.async_abort(reason="options_changed")
        return self.async_create_entry(title="", data=self._options)
