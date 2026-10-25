# 2.0.0 — HACS catalog submission

- Add HACS and Hassfest validation plus Core 2026.10.2 tests in GitHub Actions.
- Add original integration icon assets and public compatibility guidance.
- Retain the working beta.2 protocol, commands, entities and IP recovery.

# 2.0.0-beta.2 — 2026-10-25

- Assume one Geeklink hub; changing MAC addresses are not used for identity.
- Discover and verify its new IPv4 address after a failed initial handshake.
- Persist the address on the existing Home Assistant entry, preserving entities,
  appliance codes and the separate named command library.
- Recover during initial entry setup, commands and learning.
- Share a recovering client with legacy YAML lights, including old host aliases.
- Never replay a physical command whose acknowledgement was lost.
- Preserve the previous learning conversion, code validation and IR/RF payloads.
- 25 tests pass against Home Assistant Core 2026.10.2 with simulated hardware.

# 2.0.0-beta.1

Initial UI-configured learning release with legacy YAML compatibility.
