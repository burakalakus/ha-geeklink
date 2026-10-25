# Validation — 2026-10-25

Release: 2.0.0-beta.2. Tested with the actual `homeassistant==2026.10.2`
package and its pinned dependencies in an isolated CPython 3.14.2 environment.

## Results

25 automated tests passed:

- 15 protocol/UDP tests: IR and RF conversion, all 256 checksum wrapping cases
  for each signal type, invalid input rejection, framing, probe/send exchange,
  learning acknowledgement handling, timeouts, command serialization,
  cancellation cleanup, and sharing the lock between learning and transmission.
- 10 Home Assistant tests: hub config flow; legacy YAML light setup and on/off
  actions; UI draft cancellation; failed relearning preserving existing codes;
  learn/test/accept/save wizard; missing/identical-code validation; actual
  options-flow manager progression, automatic reload and registry deletion;
  full config-entry setup with all five entity platforms, entity actions,
  remote learning/sending/deletion and saved-command persistence across reload.

New recovery tests cover changed IP before sending, concurrent recovery (one
discovery, one shared lock), lost ACK with no replay, discovery failure retaining
the previous address, learning after IP change, startup from a stale saved IP,
and persistence of the new IP while preserving config entry ID, appliance
options, entity IDs, remote commands across reload and YAML client aliases.

The protocol tests communicate with a loopback UDP fake hub. The integration
tests load actual Home Assistant entities and config flows, also using that
fake hub. Learning packets are synthetic fixtures based on the original
scripts, not captured real hardware traffic.

All 22 original on/off command strings from the user's supplied YAML passed
format and additive-checksum validation. Those personal codes are not bundled.
All Python files compiled successfully and all integration modules imported
against Core 2026.10.2.

## Not verified

- Physical Geeklink discovery, firmware behavior, learning responses and
  real-world IR/RF transmission in this test environment. The user reported
  successful learning with other remotes on beta.1. Automatic IP recovery has
  not yet been tested on the physical hub.
- Browser rendering of the setup dialogs on the user's frontend.
- End-to-end installation on Home Assistant OS 17.1 or the user's network.
- Compatibility with other Home Assistant Core versions or Geeklink models.

Home Assistant emits its normal warning that this is an unreviewed custom
integration. This package is not endorsed or certified by Home Assistant.

## Reproduce

Use Python 3.14.2 or a compatible newer interpreter:

```sh
python -m venv .venv
.venv/bin/python -m pip install homeassistant==2026.10.2
.venv/bin/python -m unittest discover -s tests -v
```

The transport-only suite also runs with Python 3.12 and no dependencies:

```sh
python -m unittest discover -s tests -p test_protocol.py -v
```
