# Handheld menu draft v1

This is the shared Home Assistant, UI, and DSP contract for authoring editable handheld menus. The existing fixed Office and Watch TV profile keeps its own bindings. Home Assistant saves drafts locally. The current stock firmware cannot receive this layout or execute its draft bindings.

## Portable draft

The JSON root contains `format: "almost-universal-menu"`, integer `version: 1`, integer `entry`, integer `next_page_id`, and `pages`, an object keyed by decimal page ID. Page IDs are positive bytes from 1 to 255 and remain stable across rename, edit, and export. `next_page_id` is a high-water mark from 2 to 256 and prevents automatic recycling on deletion. There are at most 16 pages in one draft. A page contains `title`, `mode`, `controls`, and `fields`. The entry must exist. Pages can be created before being linked, and links may form cycles. Delete removes inbound links and requires a different entry before deleting the current entry.

| Member | Meaning |
| --- | --- |
| `title` | 1–24 UTF-8 bytes. |
| `mode` | `menu` enables the four soft keys. `device` also enables eligible physical controls. |
| `controls` | Object keyed by existing physical control names. Soft keys `soft_1` through `soft_4` align with A–D. Device keys use the existing TV press IDs. Power, KATA and wheel remain outside this draft. |
| `fields` | Object keyed by decimal display slot `1` through `4`. A field has `label`, `kind` and Home Assistant `target`. |

A control has a `label` (1–16 UTF-8 bytes for soft keys, optional for hard keys), and at most one of `link` (destination page ID), `back: true` (local return to the previous page), or `action` (Home Assistant-only `{ "kind": ..., "target": ... }`). A label without a behavior is valid. Physical Back returns locally when it has no explicit binding. A press navigates immediately in the preview, and subsequent presses are interpreted in the new page. A self-link does not add to the back stack. The preview caps that stack at 16 entries.

Action kinds reuse the Home Assistant binding vocabulary for lights, switches, fans, cover Open/Close/Stop, scripts, scenes, and Climate Heat/Cool Raise/Lower. The Climate target is an explicit `climate` entity in the action. The UI estimates a step from the current target and bounds. It distinguishes measured room temperature, target temperature, and the pending change. Draft preview never calls a service and never treats a proposed value as a confirmed reading. Missing, unavailable, and unsupported entities are surfaced at preview time so existing bindings can survive a temporary outage.

Each control can choose its own entity. For a Watch TV device page, set direction keys to `remote_up`, `remote_down`, `remote_left` and `remote_right` on the Apple TV remote entity, and set OK to `remote_select`. `remote_play`, `remote_pause`, `remote_menu` and `remote_home` are also available. Volume ± and Mute can use `volume_up`, `volume_down` and `mute_toggle` on a separate AVR media player. A soft key labeled **Power** can run one Home Assistant script to sequence all three devices. A control can also use `automation`, which plans one `automation.trigger` with `skip_condition: false`. Hardware On and Off remain stock controls. The preview reports one action per button, and the chosen script or automation owns any multi-device sequence. [Apple TV remote commands](https://www.home-assistant.io/integrations/apple_tv/#remote) · [Automation trigger behavior](https://www.home-assistant.io/actions/automation.trigger/)

Readout kinds are `light_power`, `fan_power`, `fan_speed`, `cover_position`, `cover_state`, `tv_power`, `tv_volume`, `tv_mute`, `tv_input`, `tv_app`, `now_playing`, `room_temperature`, `heat_target`, and `cool_target`. TV input reads `source`, TV app reads `app_name`, and Now playing reads `media_title` from its independently selected media player. Text readouts are capped at 48 characters. Artwork is a future bounded payload. Raw image URLs and Home Assistant authorization data are outside this format. The target stays in Home Assistant. Values are resolved on demand for the preview, unavailable for invalid values or capabilities. Temperature preserves the reported °C/°F unit and only Heat/Cool targets of the active mode are visible.

Draft JSON is limited to 32 KiB. Labels trim surrounding whitespace, reject control and Unicode formatting characters, and must fit the byte limits. Unknown keys or versions are rejected. Import validates completely before replacing the editable draft. Home Assistant saves an independent, private, revisioned draft per entry. A stale save fails without modifying the current draft, fixed bindings, or live firmware.

## Device composition

Composition produces compact canonical JSON using UTF-8, no insignificant whitespace, and lexicographic object key order. It retains `format`, `version`, `entry` and `pages`. Each page retains its title, mode, control IDs and labels, local `link` and `back` routes, and field IDs, kinds and labels. An action slot becomes `action: true`. `next_page_id`, entity IDs, action kinds, arguments, and current values stay in Home Assistant. The device projection is capped at 8 KiB. SHA-256 of those exact bytes identifies the layout. Reordering JSON members or changing only an entity binding leaves the layout digest unchanged.

For future sync, stage a complete revision, verify its length, digest and schema, then atomically activate it. A rejected or interrupted transfer leaves the previous layout usable. An acknowledgement identifies both the actual active digest and the config generation. A change to Home Assistant actions requires a new acknowledged generation even when the layout digest is identical. Only that generation's action table can resolve its presses. Drop packets and queued effects from the old activation when switching generations.

The existing URM1 package remains a separate profile. Its fixed-format screen records provide titles, body text, soft captions and control links, with an existing staged upload and commit. This layout adds stable positive page IDs, local Back, per-page modes, action slots and typed state slots. Stock ARM has no verified way to stage or acknowledge it. This document assigns no Bluetooth opcodes, flash addresses, or DSP RAM budget. The authoring bounds need a matching firmware capacity check. Until then, the editor displays **Draft only · Handheld sync unavailable** and offers JSON import and export. The fixed Office profile continues to use its own Room Controls grid, D-pad navigation and action reports. The draft preview follows the A–D links configured in the draft.

## Home Assistant editor and verification

The offline 0.1.5 candidate adds **Remote Menus → Menu builder** alongside **Fixed bindings**. It starts with Home A–C linking to TV, Lights and Temp. **Save draft** persists the complete menu in a separate Home Assistant storage file. **Reload saved** restores the last revision, and **Import JSON** replaces the editable contents only after validation. Import remains unsaved until confirmed with **Save draft**. If a connection interrupts Save after commit, Reload saved shows the committed revision.

The 0.1.5 candidate was derived from the tested 0.1.4 Office integration. The repository contains the later 0.1.6 implementation with the optional page-entry action. Run the integration tests from the repository root in the [Home Assistant test environment](remote-design.md#verify-the-implementation). The optional editor fixture serves the panel and draft APIs with isolated Home Assistant state and storage on loopback.

```sh
python -m unittest discover -s tests -v
PYTHONPATH=. python tests/fixtures/draft_editor_server.py
```

The Home Assistant suite exercises the real admin WebSocket handlers using a local connection shim. The activation test models a downstream receiver and checks interrupted and rejected staging, acknowledgement by generation and digest, and stale or duplicate presses. Climate preview is read-only. A separate fake-service check verifies that the existing legacy executor waits for the actual target values and does not accept a measured-temperature update as confirmation.
