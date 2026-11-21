# Stock ARM and DSP bench protocol

This milestone uses the W4600000 REV V06 stock v4.8 ARM and its normal-mode SwitchBot BLE service. Home Assistant owns action bindings. The versioned DSP candidate starts with a local fallback menu and keeps menu state in RAM. The separate DSP A-marker candidate has passed the physical transport check.

## BLE transport and first bench marker

- Normal service `cba20d00-224d-11e6-9fb8-0002a5d5c51b`. The Mac verifier also accepts `0000fd3d-0000-1000-8000-00805f9b34fb` when it exposes the same characteristics.
- Host writes use `cba20002-224d-11e6-9fb8-0002a5d5c51b`. Subscribe to `cba20003-224d-11e6-9fb8-0002a5d5c51b` first. The established stock baseline query is `57 00 00 00 02`. A normal response is 20 bytes, starts with `01 00 00 00`, and stores decimal 48 in byte 5 for v4.8. Use the observed characteristic write properties when choosing write-with-response.
- The first DSP bench image uses the exact ten-byte notification `7e 00 00 00 55 52 2d 41 2d 31` for A's initial press. The app-origin retry on the spare delivered two exact notifications for two fresh presses, with zero extra notifications on hold and release. [Bench outcome](README.md#bench-handoff)
- The stock DSP uses IPC tag 19 and a `0x302`-byte buffer. Its initial little-endian 16-bit length specifies the bytes to forward. The stock ARM's tag-19 handler copies the full buffer and passes the indicated length to its normal BLE sender. The unencrypted sender retains the first forwarded byte, inserts three zero bytes after it, and appends the remaining forwarded bytes. This is the envelope used below. Decode only exact matching frames from the configured remote's current connection. Discard other stock notifications.

## Version 1 key press notification

| Byte offset on air | Size | Value |
|---|---:|---|
| 0 | 4 | `7e 00 00 00` |
| 4 | 2 | ASCII `UR` |
| 6 | 1 | `01` protocol version |
| 7 | 1 | `01` key press |
| 8 | 1 | Source screen before any navigation. `01` Home, `02` Controls. |
| 9 | 1 | Control ID in the table below |
| 10 | 4 | Little-endian stock input-report timestamp. Its unit is unspecified. |

Home Assistant can deduplicate an exact `(screen, control, timestamp)` observed on the same connection. Reset that deduplication state on disconnect. The DSP only emits a press from a live stock companion initial-press report and holds no event for later retransmission. The two-screen action binding is **Controls, A, key press**. Keep Home A and Controls D free of action bindings because they navigate locally. Soft B and C remain labeled on the screen and have no local destination. Hard navigation keys generate messages and never navigate this fallback menu. The wheel is out of scope for this milestone.

| Control ID | Key | Control ID | Key |
|---:|---|---:|---|
| 1 | A | 11 | OK |
| 2 | B | 12 | Back |
| 3 | C | 13 | Home |
| 4 | D | 14 | KATA, reserved for stock behavior |
| 5 | On, reserved for stock power | 15 | Mute |
| 6 | Off, reserved for stock power | 16 | Volume up |
| 7 | Left | 17 | Volume down |
| 8 | Right | 18 | Channel up |
| 9 | Up | 19 | Channel down |
| 10 | Down | | |

Example Controls A press with stock timestamp `0x12345678` is `7e 00 00 00 55 52 01 01 02 01 78 56 34 12`.

### Almost Universal handheld staging contract

The separately staged handheld DSP uses the same 14-byte v1 envelope and stock tag-19 relay. It proposes source screen byte `03` for `tv` in a separate Home Assistant profile. It emits controls `01`–`03`, `07`–`0d`, and `0f`–`13` (hex). Hard Back and Home are TV IDs `0c` and `0d`. D is local and never produces a notification. On, Off and KATA retain stock handling. Wheel input and menu navigation have no custom reports in this stage.

For example, TV Back with timestamp `0x12345678` is `7e 00 00 00 55 52 01 01 03 0c 78 56 34 12`. The deployed Home/Controls profile accepts only screens 1 and 2. Menu action IDs, settings, editable captions and inbound state are outside this staged contract. [Approved menu behavior](../../docs/handheld-menu-spec.md)

### Proposed screen snapshots and state updates

Home Assistant owns live entity state. The handheld keeps only the active screen's fields in RAM. The first read-only proof uses **Room controls → Climate** and the `current_temperature` attribute of `climate.home`. Opening Climate asks for a snapshot. Subsequent state changes use deltas. The same framing can later carry light power, blind position, fan speed and other screen-scoped fields once their bindings are defined. TV press reports retain their existing layout.

| Direction | Layout | Use |
|---|---|---|
| DSP → Home Assistant, on air | `7e 00 00 00 55 52 01 kk ss 00 tt tt tt tt` | Kind `20` requests a new snapshot and starts state updates. Kind `23` closes the subscription. `ss` is the screen ID and `tt` is a four-byte little-endian subscription ID. Use the existing tag-19 relay with forwarded length 11. |
| Home Assistant → DSP, logical payload | `55 52 01 kk ss nn tt tt tt tt qq qq` followed by `nn` field records | Kind `21` replaces the snapshot. Kind `22` updates the fields listed. `nn` is the record count, `tt` matches the subscription ID and `qq` is the little-endian sequence. |

The logical message is capped at 64 bytes and contains one to eight records. A field record is `field_id type length value…`, and field IDs `01`–`08` are unique within a message. A verified carrier can impose a smaller limit. The sequence starts at zero for the snapshot. Deltas increase by one per message and do not wrap. Reject duplicate or malformed messages without applying any fields. A skipped sequence marks the active view stale and calls for a new snapshot. Missing fields in a snapshot are unavailable. Missing fields in a delta keep their previous values.

| Type | Payload |
|---|---|
| `00` unavailable | Length zero. Clears the field value. |
| `01` boolean | One byte, `00` or `01`. |
| `02` signed numeric | Two-byte little-endian signed integer. The field schema specifies its scale and unit. |
| `03` enumeration | One byte. The field schema specifies the allowed values. |
| `04` temperature | Three bytes. Unit `01` for Celsius or `02` for Fahrenheit, then signed little-endian tenths of a degree in the range −999.9 to 999.9. |

Climate uses screen ID `04`, field ID `01`, type `04`. For subscription `0x12345678`, the request is `7e 00 00 00 55 52 01 20 04 00 78 56 34 12`. The logical snapshot for **21.5 °C** is `55 52 01 21 04 01 78 56 34 12 00 00 01 04 03 01 d7 00`. If the attribute is unavailable or invalid, the snapshot is `55 52 01 21 04 01 78 56 34 12 00 00 01 00 00`. Home Assistant reads the state registry and uses the corresponding temperature unit. The read-only binding needs no climate service call.

Home Assistant scopes its listener and replies to the active paired connection, screen and subscription ID. Switching screens, closing the subscription or disconnecting releases its state listener. The DSP drops messages for another screen, an old subscription or an inactive connection. On disconnect or invalidation it labels any retained value **Last known**. On reconnect it requests a fresh snapshot with a new subscription ID for the visible screen. It uses a sequence of subscription IDs in RAM, which can start from the entering key's timestamp. The previous connection's events never satisfy the new subscription. Leaving the screen discards its fields. Only a fresh snapshot can restore current status after reconnect or a sequence gap.

**Transport and space blockers.** The inbound row describes a logical payload. A verified carrier and a reliable connection-generation boundary are required before using it on the spare. The normal status command replies from stock ARM, while stock sync, settings and update commands can write persistent state. The polished image has 204 bytes of DSP flash headroom, and its four-byte startup word already holds navigation state. An on-device implementation needs measured code size and a verified volatile allocation for a single snapshot. The [host-only fixture](../dsp-v48-native-menu/climate_smoke.c) simulates opening Climate, receiving a snapshot and deltas, losing the session, resubscribing, and rejecting stale or malformed fields. It is outside the build paths for the polished ZIP and physical TV benchmark. Run from the firmware checkout:

```sh
climate_check=$(mktemp -d)
cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
  firmware/dsp-v48-native-menu/climate_smoke.c -o "$climate_check/climate"
"$climate_check/climate"
```

## Configuration capability

The fallback menu uses fixed captions. Home Assistant stores the action binding for Controls A. The client sends the verified version query to set up the plaintext connection. Menu upload capability is unavailable in this candidate.

The stock v4.6 ARM code export shows the normal write parser at `0x0100673c`, with a dispatcher at `0x01005504` for opcode `0x0f`. These routes interpret stock commands. The explicit setup command calls the settings writer through `0x0100695c` and `0x0100fde8`. The sync/profile path at `0x01005e28` sends typed stock IPC structures under tags 6, 7, 10, 16 and 17. The tag-5 path at `0x01013eb4` also wraps its input as a stock transfer with a subtype, metadata and chunk lengths. Separately, one branch of `0x01014c78` erases and rewrites flash. Those observations give no verified path that forwards a custom payload to a bounded RAM-only DSP handler. They come from static inspection of the v4.6 ARM member. The v4.8 normal-mode version query was separately observed on the spare, and the v4.8 tag-19 forwarder matches the relevant v4.6 dispatch and buffer-copy structure. See the workspace ARM export at `analysis/universal-remote/v46-custom-fw/arm-res/arm/pseudocode.c`.

The tag-19 plaintext send at `0x01022ba0` checks for a usable connection before allocating and transmitting the frame. The fixture models this check and confirms the DSP has no pending-event buffer. Actual delivery and timing across a physical disconnect remain bench checks.

### Stock v4.8 return path for live entity state

Offline inspection of the stock v4.8 ARM member (SHA-256 `71a2b1e4a022df90f8ea4202150d8f41b20bb75d8cc879b0ce74c50f7becb7fe`) accounts for all six attributes of the normal vendor service. Addresses below are byte offsets in that member. Normal initialization calls the service registrar at `+0x1f348`. Its table starts at `+0x2d908`, with 28 bytes per entry and one callback at `+0x20268`. The stock Android UUID constants agree with the binary.

| Index | Attribute | Application behavior |
|---|---|---|
| 0 | Primary service declaration for `cba20d00…` | Readable service identity |
| 1, 4 | Characteristic declarations | Readable metadata |
| 2 | `cba20003…` | Notifications from the remote |
| 3 | `0x2902` client configuration | Two-byte subscription descriptor. The application callback ignores writes to this index. |
| 5 | `cba20002…` | Sole application command input. The callback copies up to 512 bytes to ARM RAM and queues ARM event 9. |

Event 9 feeds the normal reassembler at `+0x11380`. Event 8 delivers the assembled command to the stock parser at `+0x373c`, including the timer completion path at `+0x119ec`. The intermediate ARM buffer is consumed by that parser. The status query builds its reply on ARM. The short DSP-directed sync message carries a count and phase, and scene-list forwarding commits data to flash. Neither supplies independent display-state updates. `FD3D` is emitted as advertising service data at `+0x20648`; the registered normal table has no second service or write characteristic under that UUID.

The remote also has a GATT **client** registration at `+0x20048` for working with peer devices. Its peer-notification callback at `+0x1d898` uses the active transaction handler. The traced handler at `+0x11404` posts event `0x16` to the ARM response processor at `+0x10fd4`. That route handles a stock peer transaction. The other direct call to the GATT server registrar belongs to the separate update service.

For this image, the registered normal interfaces are exhausted for the proposed feature. There is no verified recurring HA-to-DSP channel for independent entity values. Live updates require a bounded inbound message that the ARM forwards to a DSP RAM consumer with defined queue or replacement behavior as updates arrive. The logical Climate snapshot has a 12-byte header and a six-byte temperature record. There is no assigned stock wire command or supported update rate for it.

#### What the stock DSP does with changing values

The stock sync command is a positive control for the direction of travel. ARM dispatch at member offset `+0x2e28`, case 12, stores the count in ARM state at offset `0x3b` (cleared on phase 3). It sends tag 11 with three bytes, subtype 5 followed by count and phase. In the archived DSP, tag 11 enters `0x20004ed4`, which posts internal event 13. Its handler at `0x20005a3c` requires three bytes, resets the display idle timer and dispatches subtype 5 through the pointer at `0x20042cd4`. Two ordinary sync states distinguish this path from an independent display value. These results come from the shipping instructions, without a hardware replay.

| Count and phase | ARM count after command | Stock DSP effect |
|---|---|---|
| 1, phase 1 | 1 | Resets idle and enters the sync page through `0x20030314` (page index 4). |
| 1, phase 3 | 0 | Resets idle and runs the phase-completion routine at `0x200302f4`. |

The sync handler acknowledges the BLE command without checking DSP delivery. The shared ARM sender at `+0x202ec` transmits when ready and can also trigger a power-state transition. When deferred, it can enqueue a payload copy if allocation succeeds and the resulting queued payload total is below 8192 bytes. The queue tracks neither the active HA view nor the newest value for an entity. A BLE success or queue capacity therefore gives no supported update cadence or freshness guarantee.

#### Could a custom DSP read just the completion count?

The shared echo-token, capacity and artwork report tests a 16-message stock-ARM response, records the reboot and vendor-sync counterexamples, and traces the larger configuration paths.

**Yes for a diagnostic that displays the last sync count. The same byte cannot reliably identify a fresh Home Assistant reading.** The stock ARM forwards the caller's original count on phase 3, even while clearing its own count. A DSP handler can observe that byte while Climate is visible. A genuine SwitchBot sync finishing with count 2 and a proposed HA response carrying the value 2 present identical DSP input. Even a one-shot listener armed on Climate entry can accept the wrong completion first. The message carries no peer, connection generation, view request, sequence, availability or unit. A fixed unit could be configured for a single field, but that leaves the source and freshness ambiguity.

| Boundary | Exact behavior and limits |
|---|---|
| Stock ARM sync handler | The normal collector and original parser, case 12, IPC wrapper and shared sender ran in Cortex-M3 QEMU. With count preloaded to 7, phase 3 cleared it for input counts 0, 1, 2, 127, 128 and 255. Each reached the direct IPC boundary unchanged on an awake/ready fixture. Phase 1 with count 2 retained 2. The extreme counts test byte handling only. A zero or a high count has no established private meaning in the phone protocol. |
| Fixed ARM effects | Every tested completion set activity byte `state+0x38` to 1 and cleared `+0x39`. The sender initializes/starts its shared timer as needed. With a pending power transition it can also run power/backlight helpers. The unavailable-DSP branch calls the wake helper before checking queue capacity. In replay, that branch requested wake and copied the 3 bytes when the prior payload total was 8,188. At 8,189 it requested wake and dropped them. Simulated failure to allocate the payload also dropped them. Direct, queued and dropped cases returned the same success. The stock queue stores tag, data, length and next pointer. The helpers controlling real power and the downstream IPC delivery were modeled. |
| Scope of the storage result | The count lives in ARM RAM at `0x2000a3e3`. Phase 3 actively clears any previous value, including one belonging to an in-progress vendor sync. A stock button path consults this byte. Two flanking RAM sentinels survived. The exercised paths never entered the four instrumented internal/U6 erase/write wrappers. The fixture contains no persistent store. This establishes the local RAM operation, with whole-device persistence, deferred wake callbacks and actual delivery outside the test. |
| DSP effects under project control | Stock event 13 checks for a three-byte payload and resets DSP display idle before the subtype switch. On subtype 5 the target at `0x20005b55` reads the phase. Phase 3 calls `0x200302f4` without consuming the count. These instructions match the installed compact-header DSP archive. An observer before the idle reset could read the count in RAM and update only the visible Climate label. An observer inside the subtype branch arrives after the idle reset. Suppressing stock completion can swallow a real vendor completion, while preserving it permits the stock UI effect. A DSP change also cannot undo ARM-side count clearing, wake requests or queue admission. |

Use vendor profile and scene writes for their defined configuration objects at configuration time. Some existing paths commit profile or scene data. For downloadable custom menus, a complete package still needs explicit version, validation and activation semantics. Repeating profile writes or issuing synthetic sync completions for changing entity state would mix these purposes. A rate limit reduces traffic but leaves the origin ambiguity even for a single snapshot.

**One-value display proof.** An isolated HA state registry supplied 68 whole degrees Fahrenheit. The normal parser passed the count through the original ARM sender. The simulator copied the captured three bytes across the processor boundary into the compact-header DSP's exact 41-byte tag-11 receiver at `0x20004ed4`. It allocated event 13, copied the bytes and posted the event through modeled services. A simulator-only observer read the posted event on an open Climate view, assumed whole degrees Fahrenheit, and the original compact-header label routine set **68.0°F**. With Climate closed the observer made zero label writes. HA made zero service calls. No physical IPC, BLE transfer or panel was exercised.

**The same proof produced two false readings.** A prior 67 passed through the retail deferred sender and into its queue. The test delivered that copy to a reopened Climate view while HA still held 68. The observer rendered **67.0°F**. Delayed delivery across a reopen is a simulated ordering, not a captured device event. A separate ordinary two-item completion rendered **2.0°F**. Listening only once on entry could still accept either of those first. An ACK proves neither receipt nor ownership.

**Bench decision.** Keep stock ARM on this spare. Wired ARM restoration is unavailable on this bench. The one-byte observer is suitable for offline diagnostics. A DSP-only bench image that labels it as live HA state is a **no-go** on current evidence. A system restricted to one HA owner might support a read-on-opening if it could independently establish all three conditions below.

1. Attribute the reply to this HA connection and this opening. Prove that an already queued completion cannot win after Back, reopen, disconnect, reconnect or wake. A fresh UI object or short timeout alone does not identify queued work.
2. Keep vendor sync correct. Establish exclusive ownership for the entire request and delivery window or a stock distinction the DSP can actually observe. Demonstrate that a real sync in progress keeps its count and its completion UI, including during transitions back to the vendor app.
3. Show the DSP is already awake and ready through delivery, bound the effect on ARM timers/power and normal input, and handle dropped sends. An observer before the DSP idle reset can avoid its own UI side effects, but the stock ARM can still request wake even when it drops a frame.

The replay's connection and view labels are test metadata, absent from the retail tag. A capture of legitimate vendor sync could establish the phone's count semantics. An independent stock-session signal or different typed operation would be needed to settle the request identity. The affirmative result here is that an ARM firmware change is unnecessary to move one sync byte into a custom DSP label.

Reproduce the five stock-only checks with `python3 -B analysis/universal-remote/v48/climate-proof/test_sync_completion.py -v` from the Switchbot workspace root. The test builds temporary simulator ELFs, captures the IPC boundary and uses a fixed allocator. The added cases compare a longer completion against the ordinary reply and exercise cancellation of a pending idle countdown while the DSP is ready. It requires Clang, an ARM ELF linker and Cortex-M3 QEMU.

Two other variable-data paths have different endpoints:

| Candidate | What the stock code consumes |
|---|---|
| Profile operation, tag 9 | ARM case 4, subcase 2 requires an existing record with matching identifier and 11 matching bytes. It builds a typed 124-byte object. DSP internal event 10 at `0x20005344` resets idle before and after `0x20020700`. The opcode-2 branch resolves the profile, references the stock `/remote` path and returns a typed result. It is a profile operation with display and storage dependencies. |
| Eight-byte BLE echo | ARM handler `+0x11028`, case 8, echoes eight caller bytes in its reply. Before replying it commits the binding table, including on a lookup miss. The commit erases a sector and writes `0xa28` bytes. Case 10 updates a matched ARM record with 16 bytes. Neither branch forwards the supplied value to the DSP. |

The office-light acceptance test can use the outbound button event and observe the actual switch state in HA. Displaying that state on the remote requires an inbound endpoint with an independent value, a fresh snapshot after reconnect or view change, and a policy for discarding stale queued updates. A Bluetooth proxy reaches the same stock ARM parser.

#### Offline result for Climate

The Office Controls DSP initializes Climate with **Current temperature**, **--** and **No reading yet**. Its 88-byte `climate_render_value` function at `0x2002afc4` matches the linked Office build in the archived DSP (SHA-256 `a114b96b245cd891562b7a6fb0956d62cedeb2231722ad3a7bfc270636517293`). Its direct callers in the Office source tree are in the smoke test. That test supplies formatted temperatures to the display itself. Separately, the HA provider fixture supplies logical state frames to the host receiver, which checks the subscription, sequence, value and unit. The recorded HA value of 68 °F and the remote's placeholder are consistent with both fixtures passing. The deployed path would need a sender and a DSP receiver connected across the ARM. [Climate drawing code and fixture](../dsp-v48-native-menu/patches/handheld-full-splash-cut.OFFLINE.patch) · [Recorded HA state](../../docs/handheld-state-plan.md)

The Cortex-M3 replay executes the archived ARM extension dispatcher, sync handler, state getter and IPC wrapper. It substitutes the ROM copy primitive and captures calls at the IPC boundary with the sender returning zero (deferred). Three cases passed: counts 1 and 2 at phase 1 and count 2 at phase 3. The outgoing payloads were `[5,1,1]`, `[5,2,1]` and `[5,2,3]` on tag 11. ARM retained counts 1, 2 and 0 respectively, and returned a one-byte success for each. The DSP-side effects in the table above come from the separate static trace.

To repeat the ARM test from the Switchbot workspace root with Clang, LLVM's ELF linker and QEMU installed:

```sh
out=$(mktemp -d)
clang --target=arm-none-eabi -mcpu=cortex-m3 -c analysis/universal-remote/v48/arm/sync_status_qemu.S -o "$out/sync.o"
printf 'SECTIONS { .text 0 : { *(.text) } }\n' > "$out/sync.ld"
linker=$(python3 -c 'import runpy; print(runpy.run_path("analysis/universal-remote/v46-custom-fw/prototype/arm-board/build.py")["find_linker"]())')
"$linker" -T "$out/sync.ld" -e reset "$out/sync.o" -o "$out/sync.elf"
qemu-system-arm -M mps2-an385 -cpu cortex-m3 -nographic -semihosting -kernel "$out/sync.elf"
```

**Smallest proof that would change the transport decision.** Identify one ordinary stock operation whose defined purpose includes independent application data. With the same active Climate view and binding, replay two distinct valid temperatures through that operation's original ARM handler. Observe both values and the unit at the intended DSP receive handler, with no settings/profile writes or sync-page transition. A new view or connection must reject the previous subscription's reply before either reading can be considered current. The existing sync operation fails the independent-value requirement, so repeating it on the spare would not establish Climate transport.
