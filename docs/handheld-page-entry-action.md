# Optional page-entry actions

The Menu Builder extension adds an optional Home Assistant-only `on_entry` to a draft page. The value is `{ "kind": "script" | "automation", "target": "…" }`. Omitting it leaves the page without an action. An automation checks its conditions. A single script can coordinate Apple TV, TV input, and AVR power. Button actions and status subscriptions keep their existing behavior. Adding or changing this binding does not change the device layout bytes, so future activation must acknowledge a new config generation even if the digest stays the same.

An explicit link selection that enters a different page is one entry. Leaving and explicitly opening the page again is another. Do not emit an entry report for boot, refresh, preview selection, redrawing, reconnect, Back, or selecting a self-link. Any future DSP capable of this feature should emit one report for each qualifying page transition, including pages with no assigned action, and must not retain a report for later delivery across a link change. Fixed-profile input reports and Climate subscriptions keep their own identities. The existing `item_activation` decoder refers to the older URM1 input protocol and supplies neither a draft generation nor an explicit opening guarantee.

## Proposed report for DSP coordination

The simulator proposes an independent notification kind `0x10` under the version-one normal stock outbound envelope. Example shape: `7e 00 00 00 55 52 01 10 pp 01 gg gg gg gg ss ss ss ss`. `pp` is the nonzero draft page ID, `01` is an explicit link selection, `gg` is the little-endian acknowledged config generation, and `ss` is a nonzero little-endian entry sequence that increases within an activation. A new activation is required before sequence wrap. Repaint, restore and reconnect have no report. The existing input, temperature OPEN and CLOSE, and firmware-operation reports keep their current format. This is proposed for firmware coordination and the isolated host fixture. It is not a deployed wire allocation.

Home Assistant binds a receiver to one verified live activation and a fully acknowledged draft generation. It discards malformed frames, reports from another activation or generation, unknown pages, and duplicate or reordered entry sequences. A queued entry rechecks the same activation when it reaches dispatch. No work starts again on reconnect. The fixture uses a disposable Home Assistant handler. The shipped binding editor neither hooks this report to stock BLE nor runs entry actions from its preview. No fixed bindings are activated by installing or opening this editor.

In **Menu builder**, select a page and use **On entry** to assign a script or automation. The preview reports the action only when a linked key opens the page. The starter draft puts TV, Lights, and Temp above soft keys A, B, and C respectively. Introductory navigation leaves D empty on Home and uses D for Back on the activity screens.

## Fixed Watch TV with stock ARM

In **Fixed bindings**, choose **Watch TV** and set **On entry** to **Run script** or **Trigger automation · check conditions**. Select an entity and save bindings. The default is **None**. The setting is stored alongside the fixed menu revision, independently of the TV keys. Older menus without this setting load with no action.

The paired offline DSP produces `7e 00 00 00 55 52 01 02 03 00 TT TT TT TT` on deliberate Activities → Watch TV selection. The receiver checks the exact report shape and active stock handheld connection, publishes `ununiversal_remote_page_entry`, and queues the configured action against that connection. Its recent-entry cache holds 128 reports per connection, independently of the key report cache. Restarting the link does not run an action. A fresh report from a new selection can run again. The only stock GATT write in the Home Assistant fixture is the existing version query. [Exact fixed-profile contract and DSP pin](../firmware/dsp-v48-native-menu/patches/handheld-watch-tv-entry.OFFLINE.patch)

The fixed-profile proof covers local DSP emission in the emulator and receipt and dispatch with fake GATT in Home Assistant. Hardware delivery from the pinned DSP, repeat suppression on the connected handset, and both sides of a physical reconnect still need bench confirmation. The editable draft still needs a device layout transfer and ACK before receiving any draft activation reports.

## Offline Home Assistant candidate

| Artifact | SHA-256 |
| --- | --- |
| 0.1.6 integration ZIP, 51,016 bytes | `5d78149095181893a58c4a484ea2606fdcbd1718f2bc42ad886e63f81fab63c9` |
| 0.1.6 source patch | `b27d30a3aff9ddf27df3e3b15e4abf22690f8d9e006f262780ae7edea629f201` |
| 0.1.5 base ZIP | `dff65f6295489330b4eadc242583488ee83525a98744f66ed64aa75f01946698` |

Applying the patch to the 0.1.5 component and its existing test fixtures reproduced the component files in the 0.1.6 ZIP. Forty tests passed against the fresh ZIP extraction with Home Assistant 2026.11.2. Fixed-profile tests cover exact-frame discrimination, an unset binding, duplicate OK reports, a second opening, message routing separate from TV keys, idle reconnect, restore and clear, and automation condition handling. The draft tests cover layout digest stability, explicit-link preview, report identity, generation replacement, and disposal of queued actions from a superseded activation.

The loopback browser fixture saved a fixed Watch TV automation and a draft TV script. Direct page previews stayed idle. The fixed Activities OK and draft Home A preview showed the configured action, while B and C opened Lights and Temp. The fixture forbids Home Assistant service calls from the preview. Neither this candidate nor the associated DSP was installed as part of these tests.
