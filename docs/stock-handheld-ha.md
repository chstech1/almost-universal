# Almost Universal Home Assistant bench build

Match Home Assistant **0.1.3** to the stock ARM v4.8 **Almost Universal handheld** DSP. Select **Stock ARM v4.8 · Almost Universal handheld** in the existing integration entry. The **DSP key reports v1** Home/Controls profile and its saved switch binding remain available for the fallback DSP.

| Package | SHA-256 |
| --- | --- |
| `ununiversal-remote-stock-v48-ha-0.1.3.HANDHELD.STAGED.zip` | `c8277cef5ce6088fbffa283572f99eacd79e48fa419b2aee52f87fc273c13d41` |
| `WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-LAYOUT.CANDIDATE.zip` | `cb23fbee3d86c9bad4faff06d19bf409f2fd78042ed320ef4fc5256c64775519` |
| Text checkpoint with the same wire contract `WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-HANDHELD.OFFLINE.zip` | `074ef125fb46c75d01d315c3f0a163ee94d9e08a2e47fe61a8516523495a9c13` |
| Home Assistant rollback `ununiversal-remote-stock-v48-ha-0.1.2.STAGED.zip` | `618a95e12a6a5b2c8668c41d4db497c14e77ca8df516ffc2b188382dda763029` |
| Controls A fallback DSP `WoRWS-v4.8-DSP-CONTROLS-A-V1.CANDIDATE.zip` | `10d28049e790ba732902894bd3b08451b04dc71b5e605753d19ad3da062a1572` |

The staged packages are in the Switchbot workspace under `artifacts/universal-remote/`. Verify both candidate ZIPs before the handoff. For firmware pinning and transfer ownership, follow the [DSP build notes](../firmware/dsp-v48-native-menu/HANDHELD.md) and the [bench sequence](first-hardware-milestone.md#bench-sequence).

The graphical candidate uses native LVGL tiles in the stock 240 × 320 container, a lime focus highlight, and four aligned TV captions. The text checkpoint uses a single stock label and marks the focused tile with `>`. Both send identical TV reports. The graphical candidate still uses the stock font and fixed captions. Live status, battery, receipts, and menu actions have no linked data path.

## Transport and editor

- Home Assistant verifies the selected address and SwitchBot manufacturer prefix. It subscribes on the stock normal-mode GATT service and sends the existing v4.8 version query. MQTT is off in this profile.
- The 14-byte `7e 00 00 00 55 52 01 01` envelope carries `screen=03` for `tv`, one control byte, then a four-byte little-endian DSP timestamp. Eligible controls are `01`–`03`, `07`–`0d`, and `0f`–`13`. The integration publishes `ununiversal_remote_input` with `transport=stock_v48_handheld`, the source screen and control, and `kind=press`. Duplicate frames are suppressed per connection. Disconnect discards stale input and queued actions from the old session.
- **Remote Menus** opens the matching fixed-screen editor and interactive preview. TV A–C, direction pad, OK, channel, volume, mute, physical Back, and physical Home can toggle a switch or run a script. Unassigned keys can produce an input event but run no Home Assistant action. The preview reports the configured action without calling services. **Save bindings** writes the profile’s bindings independently of the existing Controls A and URM1 profiles.
- Cursor navigation, physical Back on menu screens, entering TV, and TV D are local. Physical Back and Home in TV mode are forwarded. Stock On, Off, KATA, and Reset retain stock handling. Wheel, menu action tiles, editable captions, inbound state, command receipts, and menu upload are unavailable. The layout DSP uses stock LVGL tiles with fixed labels and a four-slot TV footer. The Home Assistant preview uses the approved visual layout.
- The DSP holds entry OK behind a release fence. A different eligible solitary press lifts the fence. An immediate second OK can be suppressed even after physical release. There are no separate hold, release, or wheel reports in this build. The matching preview models the entry fence. [Wire contract](../firmware/dsp-v48/PROTOCOL.md#almost-universal-handheld-staging-contract)

## Install after the live handoff

1. Preserve the exact 0.1.2 component archive and any existing Home Assistant backup. Record the current entry's version, stock address and manufacturer prefix, MQTT off, and the saved **Controls → A → SwitchBot A Bench Test** binding. Keep the original entry and saved menu data. Disable only this entry and verify the spare disappears from Home Assistant's Bluetooth connection monitor so the firmware operator can take the BLE link.
2. Verify the 0.1.3 ZIP, then replace the component files via the approved Home Assistant file workflow. The archive has 11 files under `custom_components/ununiversal_remote/`, including `handheld-draft.js`. Restart Core once to load the changed Python modules. Confirm **Version 0.1.3** and leave the entry disabled while firmware transfer and physical recovery are checked.
3. After the firmware operator confirms that the graphical DSP is active, recovery passed, and the Mac has released BLE, enable only the existing entry. Open **Configure**, select **Stock ARM v4.8 · Almost Universal handheld**, keep the same address and manufacturer prefix, and leave MQTT off. Submitting triggers an entry reload. Open **Remote Menus** again and confirm the stock normal-mode handshake and `ble_active=true`. The version handshake verifies the ARM/GATT path. A valid `tv` report verifies the DSP contract during the press test.

## First physical action

1. In **Remote Menus → Screen: Watch TV → TV key: A · Input**, select **Toggle switch → SwitchBot A Bench Test** (`switch.switchbot_a_bench_test`) and save. Leave the other TV keys unassigned. The old **Controls A** binding remains in its own profile. Wait for readiness again after Save.
2. Arm the **Developer Tools → Events** listener for `ununiversal_remote_input`. Record the pager total and open the newest event. Record the current state of the disposable switch and `input_boolean.switchbot_a_bench_state`. Use History scoped to those two entities for exact transitions.
3. Enter **Watch TV** with a fresh OK on Activities. That entry press is local. Use one short physical **A** tap from the TV screen. Require one `stock_v48_handheld / tv / soft_1 / press` event with `control_id=1` and one matching transition on each entity. Press **D** to verify local return without a TV event or additional transition. Leave the entity in the state produced by the one tested press.

## Rollback

With 0.1.3 still running, return the entry to **DSP key reports v1** and keep MQTT off for the pinned Controls A fallback DSP. The existing action is stored separately. Changing profiles requires only the reload from Configure. If rolling the Home Assistant code back too, select that fallback profile first, replace the component with the pinned 0.1.2 ZIP, then restart Core. If 0.1.3 cannot start so Configure is unavailable, use the approved Home Assistant backup restore to recover the previous code and entry options together. Keep the 0.1.3 backup if the new TV bindings must be recovered later.

## Office controls in 0.1.4

The staged `ununiversal-remote-stock-v48-ha-0.1.4.OFFICE.STAGED.zip` has SHA-256 `f517bc4b88be0e91fd2355e2a3fb8ec09106d3129c9b4c826587d45bc32a680b`. Match it to a DSP build that emits the Office screen IDs. Existing Watch TV and Controls bindings are restored from storage. Room bindings start empty.

| Device screen | Screen ID | Bindable soft keys |
| --- | --- | --- |
| Lights | `0x05` | A toggles a light or switch |
| Blinds | `0x06` | A opens, B closes, C stops a supported cover |
| Curtains | `0x07` | A opens, B closes, C stops a supported cover |
| Fan | `0x08` | A toggles a fan |

Remote Menus also allows a script for any of those action keys. Back and D are handled by the handheld on the Office screens. Home Assistant publishes the semantic `button_id` (`toggle`, `open`, `close`, or `stop`) and the physical `control_id` (1–3) on `ununiversal_remote_input`. Device operations use outbound key reports over the existing stock Bluetooth connection. Climate still needs a live state path to the DSP.

Run `python -m unittest discover -s tests -v` from this repository with Home Assistant Core and a host C compiler installed. The Office fixture simulates the stock Bluetooth client, exercises Home Assistant's action dispatch against local test entity services, and verifies saved profile compatibility, rejected room packets, and duplicate suppression. The test suite also covers disconnect and reload behavior.
