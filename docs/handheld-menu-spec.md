# Almost Universal handheld design guide

This guide defines the handheld menu and button behavior for the SwitchBot W4600000 V06. Use it for the DSP display, Home Assistant configuration, and preview. The handheld has two screen modes. **Menu mode** uses a cursor to browse and select. **Device mode** routes the remote's controls to one active device. The screen identifies its mode below the title.

Open the [offline handheld draft](../tools/handheld-menu-preview.html) to try both modes. The same draft is available from **Handheld draft** in supported development copies of [Home Assistant Remote Menus](remote-design.md#preview-the-approved-handheld-menu).

## Controls by mode

| Physical control | Menu mode | Device mode |
| --- | --- | --- |
| ↑ ↓ ← → | Move the cursor to an adjacent tile. | Navigate on the active device. |
| OK | Open the focused tile or invoke its action. | Select on the active device. |
| Back | Return one screen and restore the previous cursor position. Inactive on Activities. | Send Back to the active device. |
| A–C | Inactive. | Run the labeled device shortcuts. TV starts with **Input**, **Guide**, and **Menu**. |
| D | Inactive. | **Back** returns one screen on the handheld, even offline. |
| Channel, volume, mute, Home | Inactive. | Send the corresponding command to the active device. |
| Wheel | Inactive. | Route to the active device when a wheel binding is supported. |
| On, Off | Retain stock power behavior on the v4.8 bench path. | Route to the active device where supported. Retain stock handling on the current bench path. |
| KATA, Reset | Retain stock handling. | Retain stock handling. |

Device mode's D leaves the device state as it was. The TV's own Back, Home, and Menu remain accessible during TV mode. Leave an unsupported A–C shortcut slot blank. Keep D available wherever a Device screen has a previous screen.

## Screens and navigation

**Activities** is the root. Fill the two-column grid left to right, then top to bottom. Focus the first tile when entering a screen for the first time. An arrow moves to an occupied adjacent tile. At an edge or an empty cell, the cursor stays put. Returning restores the cursor to the tile that led to the next screen.

| Screen | Mode | Tiles or controls |
| --- | --- | --- |
| **Activities** | Menu | **Watch TV** opens TV mode. **Room controls** and **Scenes** open their menus. |
| **Room controls** | Menu | **Lights**, **Climate**, and **Blinds** open their screens. |
| **Scenes** | Menu | **Movie night** and **Evening** invoke their assigned scenes. |
| **Lights** | Menu | Show the last reported power state and dimmed status when available. **Turn on** or **Turn off** changes the light. |
| **Climate** | Menu | For the first two-way test, show a read-only current temperature from `climate.home`. Physical **Back** restores focus to Climate in Room controls. |
| **Blinds** | Menu | Show the last reported position or state. **Open**, **Close**, and **Stop** invoke their assigned actions. |
| **Watch TV** | Device | Show TV mode and the four soft-key captions. The hard keys control the TV. |

**OK on Watch TV** enters TV mode locally. It sends no TV Select or power command. The next fresh press uses the TV mapping. **D** returns to Activities with **Watch TV** focused. In cursor menus, physical **Back** handles return navigation. Keep Back tiles and footer navigation tips out of the grid and display.

The room, scenes, and television mappings are sample configuration. The first Climate test reads `current_temperature` with its unit. Show **No reading yet** before the first valid reading and **Last known** when a retained value is stale. This screen has no setpoint, mode, or power controls. For an unconfigured action menu, show **Set up in Home Assistant** and keep physical Back available when the screen has a parent. [Climate layout and state examples](handheld-native-polish.md#read-only-climate-for-the-first-two-way-test)

## 240 × 320 display

Use charcoal for a dim-room display, matte lime for the focused tile, and warm amber for link errors. Keep the title and content aligned across modes. The soft-key strip appears in Device mode.

| Region | Native pixels | Layout |
| --- | --- | --- |
| Status | y 0–32 | Link status on the left. Battery on the right when available. |
| Title and content | y 33–252 | 14 px side insets, 29 px semibold title, 12 px mode and context, and 13 px tile labels. Use two equal columns with a 6 px gutter. Give browse tiles room for an icon and label. Use compact tiles below a readout. |
| Feedback | y 253–273 | One 11 px line for progress, confirmation, or failure. Reserve the space so feedback leaves tiles and captions in place. |
| Soft keys | y 274–319 | Blank in Menu mode. Device mode has four 60 px slots, centered at x 30, 90, 150, and 210. Use one-line captions and keep **D Back** at the right. |

| Role | Color |
| --- | --- |
| Panel | `#121716` |
| Primary text | `#F2F3EB` |
| Secondary text | `#ACB5AD` |
| Focus fill and focus text | `#D6EF95` and `#1A2415` |
| Dividers | `#353E39` |
| Offline or error | `#FFD098` |

Use a legible sans in the native renderer. Keep labels short enough for the native font and allow longer tile labels to wrap without moving the feedback line. Verify the RGB565 colors, labels, and focus indicator on the actual panel at normal and dim backlight.

The [native display release baseline](handheld-native-polish.md) gives the stock-font dimensions, the read-only Climate layout, and the checks that need physical screen photos.

The [Activities and Watch TV visual target](handheld-native-visual-slice.md) records the approved icon, focus, panel, and caption treatment for the higher-fidelity native layout.

The [combined native menu checklist](handheld-combined-cut.md) specifies the stock fonts, palette, nested layouts, read-only Climate, and approved splash for firmware integration.

The [compact Activities header](handheld-combined-cut.md#compact-activities-header) brings the Office controls grid up and puts a battery icon beside the title when a verified reading is available.

The [Office display and Watch TV activity guide](handheld-office-display.md) extends that header to every page. It specifies device status, Climate targets and controls, Watch TV media fallbacks, and separate navigation, volume, and Power targets.

The [handheld artwork budget](handheld-asset-budget.md) compares the full approved splash, reusable icons, and menu illustrations at 64 KiB of assets and under a 1 MiB combined DSP plan.

## Firmware and Home Assistant

The handheld owns cursor movement, the current screen, and the history needed for local Back. Home Assistant owns device and action bindings, scene execution, and confirmed entity state. A menu tile has a label and a destination or a Home Assistant action. A Device screen has an active device and bindings for its eligible controls. Preview each draft with the same routing rules the firmware will use.

- Resolve each press against its source screen. Consume cursor movement, local navigation, and mode transitions on the handheld. Send an action when OK selects a bound action tile or when a mapped control is pressed in Device mode. Require a fresh press after a mode change so a held or released key cannot act in both modes.
- In the editor, show destinations and actions for Menu tiles. For Device screens, show eligible hard keys and editable A–C bindings. Reserve physical Back in Menu mode and soft D in Device mode for local navigation. Unassigned commands remain inert.
- The offline preview uses sample state and shows the action that would be sent. **Download draft** exports `handheld-draft-v1` for review and handoff. The current saved-menu and bench transport profiles retain their respective formats. [Home Assistant editor and transport](remote-design.md#preview-the-approved-handheld-menu)
- The stock-ARM handheld staging profile has fixed captions and outbound TV key reports. Editable captions and inbound state on that firmware need a verified transport path. Keep screen and control identities stable within their profile. [DSP staging protocol](../firmware/dsp-v48/PROTOCOL.md#almost-universal-handheld-staging-contract)

## Feedback, disconnects, and wake

- Update local focus as soon as the key registers. For linked actions, distinguish **Sending…**, **Command sent**, and confirmed device state. Use a result such as **Lights turned off** after the entity reports the change.
- Menu navigation and both modes' local Back behavior work offline. Mark cached values **Last known** and omit readings the handheld has never received. If a link drops during an action, show **Link lost · action unconfirmed**. Refresh eligible state after reconnect and discard old presses.
- A cold boot can show the existing Almost Universal splash before Activities. The wake goal is to restore the last screen and its focus. Wake retention is deferred in the current bench plan. [Hardware milestone and recovery evidence](first-hardware-milestone.md)

## Acceptance checks

| Check | Expected result |
| --- | --- |
| Browse Activities and Room controls | Each arrow moves one occupied cell at most. OK selects. The soft-key strip stays hidden. |
| Enter and exit a nested cursor menu | Physical Back restores the previous screen and focus. D has no action. |
| Enter Watch TV with OK held | TV mode opens. No TV Select is emitted until the next fresh OK press. |
| Compare physical Back and D in TV mode | Physical Back invokes the TV mapping. D exits locally and restores the parent focus. |
| View Room controls → Climate | The current temperature and unit are read-only. Missing and stale readings are labeled. Physical Back restores focus in Room controls. |
| Disconnect and reconnect | Both local Back paths still work. Linked commands indicate the missing link. Reconnect sends no stale press. |
| Run one configured action on the bench | One fresh press produces one matching Home Assistant action. The preview only simulates it. |
| Inspect LCD and soft-key alignment | The footer fits four captions above A–D in Device mode. Tile labels and status stay readable at both backlight settings. |

Use the verified stock renderer and Bluetooth-only bench path for staging. The legacy **Home → Controls** bench screen remains useful for checking one-button delivery independently of the new menu. Use the hardware milestone for the current upload and recovery sequence. [Native display checkpoint](../firmware/dsp-v48-native-menu/README.md) · [Bench sequence](first-hardware-milestone.md#bench-sequence)
