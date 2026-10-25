"""Geeklink integration constants."""
DOMAIN = "geeklink"
PLATFORMS = ["light", "switch", "cover", "button", "remote"]
DEFAULT_PORT = 9001
DEFAULT_TIMEOUT = 5
DEFAULT_DELAY = 0.5
LEARN_TIMEOUT = 30
KINDS = {"light": "Light (separate on/off)", "switch": "Switch (separate on/off)",
         "cover": "Cover (open/close)", "button": "Button / power toggle"}


def command_names(appliance):
    if appliance["kind"] == "cover":
        return ["open", "close", "stop"] if appliance.get("stop") else ["open", "close"]
    return ["press"] if appliance["kind"] == "button" else ["on", "off"]
