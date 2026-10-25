# Geeklink for Home Assistant — 2.0.0-beta.2

Target: Home Assistant Core **2026.10.2**, on Home Assistant OS. Local UDP port 9001; no cloud account or external Python process required.

This beta adds automatic IP recovery under a single-hub assumption. The user reported that learning worked with other remotes on the previous beta. Automated tests still use simulated hardware; real reboot/IP recovery needs confirmation on the hub. The learn conversion and IR/RF transmission payloads are unchanged.

## Install through HACS (recommended)

1. Open **HACS → menu → Custom repositories**.
2. Add `https://github.com/burakalakus/ha-geeklink` with category **Integration**.
3. Find **Geeklink** in HACS and download it. Restart Home Assistant.
4. If already using this integration, keep its existing entry and learned codes.
   Otherwise add **Geeklink** under Settings → Devices & services.
5. Future updates can be downloaded through HACS, followed by a restart.

This is a HACS custom repository, not a listing in the default catalog. Until
GitHub releases are published, HACS installs the default branch. Back up your
existing Geeklink directory before your first HACS installation. The package
keeps the same `geeklink` domain, options format and command-storage keys.

## Manual installation

1. Make a Home Assistant backup. Keep a copy of your current `custom_components/geeklink` directory for rollback.
2. Extract this archive on your computer. Copy the enclosed **custom_components/geeklink** folder into your Home Assistant **/config/custom_components/** folder, replacing the old Geeklink integration files. The final path must be `/config/custom_components/geeklink/manifest.json` (not a nested `geeklink/geeklink` folder).
3. Keep your existing `light: - platform: geeklink` entries and template switches/covers exactly as they are. This release supports them.
4. Check configuration, then restart Home Assistant fully. A YAML reload alone does not load new Python code.
5. Go to **Settings → Devices & services → Add integration → Geeklink**. Enter its IPv4 address, or leave the field blank to discover devices. Choose your hub if discovery returns a list.
6. Open **Configure** on the Geeklink integration. Choose **Add appliance**.

If Geeklink is not listed after restarting, refresh the browser and inspect Settings → System → Logs. Report the full exception without posting private command data publicly.

## Learn a new appliance

1. Enter a descriptive name, such as `Test Lamp`.
2. Choose Light, Switch, Cover, or Button / power toggle.
3. Choose IR or RF 433 MHz. Enable STOP only for a cover with a dedicated stop button.
4. Select a command (ON/OFF, OPEN/CLOSE/STOP, or PRESS).
5. Have the original remote ready. Submit the preparation page, wait for learning mode, then press the corresponding button. The learning timeout is 30 seconds, after any currently running transaction completes.
6. On the review screen, choose **Test** to physically operate the appliance. Select **Accept** to keep that code in the current draft.
7. Repeat for the remaining commands, then choose **Save appliance**. Only this final step persists the appliance. The integration reloads automatically to create it.

Close/cancel discards unsaved draft changes. Relearning keeps the previous code until you accept and save the replacement. Failed learning never replaces a saved code.

Use **Configure → Relearn appliance commands** to replace individual codes. Use **Remove appliance** to remove an appliance and its UI-created entity. New UI entities belong to the hub device. Rename entities or assign areas using Home Assistant's normal entity settings.

A toggle-only power remote should be a Button, not an ON/OFF entity. The wizard rejects identical ON/OFF codes. Your existing YAML codes are accepted unchanged, including existing toggles.

## First hardware check

Start with an existing, noncritical light and verify that legacy sending still works. Then add a new `Test Lamp` appliance, learn one command, and test it. Do not recreate all existing appliances yet. If learning fails while sending works, capture the Home Assistant error and identify whether IR or RF was used; a sanitized raw response may be needed to confirm the reverse-engineered packet layout.

Keep the Geeklink app and standalone learning scripts idle during testing: they do not share this integration's communication lock.

## Existing YAML compatibility

All 22 on/off code strings in the supplied old configuration pass the new format and checksum validator. Codes are not included in this distributable package.

Legacy YAML light names and the original absence of a published entity unique ID are preserved. Although your old YAML has `unique_id`, your original Python class did not expose it to Home Assistant; this release does not silently introduce registry migration for those entities.

Legacy lights without `host` discover the only responding hub on their first command. An optional `host` supplies an initial address. In this single-hub release, all legacy and UI entities share one recovering client:

```yaml
light:
  - platform: geeklink
    name: "Existing Light"
    host: 192.168.1.50
    command_on: "YOUR_EXISTING_CODE"
    command_off: "YOUR_EXISTING_CODE"
```

Use the actual existing codes; the placeholders above will fail validation. New UI appliances and legacy lights addressed to the same IP share one communication lock. Adding the hub through the UI does not import, duplicate, or delete existing YAML entities. Automatic YAML-to-UI migration is not implemented in this beta. Keep your existing templates while you use the compatibility mode.

## Automatic recovery when the hub IP changes

This release assumes **one Geeklink hub**. It does not use MAC addresses to match the rediscovered device.

- During startup, or before sending/learning, try the remembered IP first.
- If the handshake fails, broadcast discovery on UDP 9001. Verify the responder using a fresh handshake.
- Update the **same existing config entry** with the new IP. Entry ID, appliances, learned commands, entity IDs, and command storage keys remain unchanged. No reconfiguration or reinstallation is needed.
- Continue the requested operation when recovery succeeds **before** any physical command has been sent.
- If a command has already been sent but its reply is lost, rediscover for subsequent calls but report the original command failure. Never automatically replay that potentially executed command.
- During a hub reboot, discovery may find nothing. The current operation then fails normally; a later action retries. Home Assistant also retries failed config-entry setup automatically. There is no background polling when an already-loaded integration is idle.
- Legacy YAML lights share this recovery, including explicit old `host` values. YAML files are not rewritten. With YAML-only setup, recovery repeats when needed after a Home Assistant restart.

Discovery requires broadcast reachability on the local IPv4 network; it will not generally cross VLANs. More than one responder is treated as an error rather than choosing arbitrarily. A reachable hub at the old IP is used normally because this protocol provides no verified stable hardware identity. The original integration title may still contain the initial IP; the saved connection address is updated independently.

## Standard remote actions

The integration creates a remote entity, for example `remote.geeklink_192_168_1_50_remote`; select the actual entity from the action picker.

The remote command library is separate from UI appliance codes. Use named commands for arbitrary remote buttons and automation sequences. Commands saved here do not automatically create appliance entities.

```yaml
action: remote.learn_command
target:
  entity_id: remote.YOUR_GEEKLINK_REMOTE
data:
  device: soundbar
  command: volume_up
  command_type: ir
  timeout: 30
```

A Home Assistant notification prompts you to press the button. RF learning uses `command_type: rf`. Supported learning timeout: 5–120 seconds. A list of command names is learned in order and committed together only if all succeed.

```yaml
action: remote.send_command
target:
  entity_id: remote.YOUR_GEEKLINK_REMOTE
data:
  device: soundbar
  command: volume_up
  num_repeats: 1
```

```yaml
action: remote.delete_command
target:
  entity_id: remote.YOUR_GEEKLINK_REMOTE
data:
  device: soundbar
  command: volume_up
```

The remote entity's `saved_commands` attribute lists device and command names, never code bytes. Turning that remote entity off disables its `send_command` action; it does **not** power off the hub or disable the light/switch/cover entities. Hold-duration and alternative-code sequences are unsupported and return an explicit error. Repeats must be 1–20; the minimum hardware spacing remains 0.5 seconds even when `delay_secs` is smaller.

## State and reliability

- Light and switch state is assumed from successful transmissions, not measured from the appliance. A restored state is only the previous assumption.
- Cover OPEN/CLOSE also records an assumed state immediately; no travel time or percentage is fabricated. STOP makes the position unknown.
- Power-toggle buttons deliberately have no on/off state.
- Socket operations have timeouts. Failures raise action errors without changing the last assumed state.
- Learning and sending are serialized per hub with a 500 ms quiet period.
- IP recovery can retry the handshake before transmission; it never repeats a physical command after a missing acknowledgement. A timeout can mean the command was transmitted but its reply was lost.
- Cancellation closes the socket. The original scripts expose no verified command for exiting hardware learning mode; the physical hub may remain in learning mode until its own timeout.
- Responses are checked for framing and matching IP/port. The original scripts do not document ACK status fields, so a framed send reply is not proof of appliance execution.
- Learned transmit packets must match the supported IR/RF headers and additive checksum. Unknown learning formats fail rather than saving corrupt codes.
- UI appliances persist in Home Assistant config-entry options; standard remote commands use Home Assistant Store. Include Home Assistant configuration in backups. Do not edit `.storage` by hand.

## Rollback

Remove any newly created UI Geeklink entry, restore your saved old `custom_components/geeklink` folder, and restart. Keep the original YAML. Removing the UI entry deletes its separate command library, so retain a backup first if you want to preserve new learning.

## Development and attribution

Protocol derived from https://github.com/burakalakus/geeklink-python by Burak Alakuş. Distributed under the upstream GPLv3 license included in LICENSE. The original scripts remain in that repository; this dedicated integration repository contains the Home Assistant implementation.

Run protocol tests with `python -m unittest discover -s tests -p 'test_protocol.py' -v` from this directory. See VALIDATION.md for the exact checks performed and limitations.
