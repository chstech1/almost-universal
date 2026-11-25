# Distinguishing a DSP restart from a cold start

With stock Raise to Wake enabled, pickup from idle-dark Controls on the Controls A v1 image woke the spare and displayed the splash. The 115200 trace captured an ordinary Reset `DSP:E` at 14:38:28.607 Eastern on November 20. During the later key-free pickup it captured the identical resident startup banner, beginning at 14:41:14.480, and a new `DSP:E` at 14:41:15.111. Pickup therefore re-entered the DSP loader and application. This trace leaves ARM reset and pre-relocation DSP RAM unmeasured. The Controls A image stays installed for the action and timeout trials.

## Stock evidence

Stock ARM’s idle countdown at member offset `+0x7b90` can post event 1. The idle path at `+0xb5bc` calls `+0xc168 → +0x13e98 → +0x1c9ec`. It isolates the DSP and gates the master clock, then clears the ARM-side loader and ready flags. The corresponding FreqChip SDK routine writes PMU isolation register `0xaa` and `0xc0` to `0x500210f1`. The examined stock stop routine does not clear the DSP LDO enable in register `0x13`. This makes RAM retention plausible across a DSP restart. It leaves deeper SoC sleep and resident-loader writes unmeasured.

When normal ARM event 0 permits startup, `+0xcdac → +0x14018 → +0x13f48` runs the DSP loader. Its request sets the reboot byte. `+0x190d8` releases and pulses the DSP reset using `+0x1e06c` and `+0x1e054`. At `+0x13fbc → +0x19138`, the ARM sends IPC format 2 with four bytes holding `0x20000000`, the DSP image pointer. This common loader handoff carries no wake-reason field. The ARM-side ready flags describe loader state, and the Raise to Wake setting describes configuration. The examined paths do not identify a DSP-readable flag that distinguishes pickup from an intentional reset. The stock application calls its copy/clear routine immediately after DSP entry. The splash build extends that clear through its splash-shown byte, so a DSP software restart is sufficient to replay the splash even if the RAM rail stays up. The detailed ARM trace is recorded alongside the physical observations in `analysis/universal-remote/v46-custom-fw/office-light-test/bench-2026-11-20/pickup-wake-v48.md`.

## Minimal retention diagnostic

The separate diagnostic builds on the working stock display checkpoint and shows **WAKE TEST. Please add devices via app.** It seeds volatile DSP RAM word `0x0018342c` with `0x57363852` when the stock setup page completes. The word lies between the stock initialized-data end and BSS start. The native splash already used this same padding word. This diagnostic leaves both stock relocation bounds unchanged. It samples the word at app entry, before the relocation call. At **115200 8N1** it emits `DSP:R` for a full cookie match or `DSP:E` for a miss. The original relocation call, page and flush paths still run. The probe never writes ARM RAM, persistent settings or flash during wake. The UART helper skips a busy FIFO.

| Item | Value |
| --- | --- |
| ZIP | `WoRWS-v4.8-DSP-WAKE-RETENTION.CANDIDATE.zip`, 251,419 bytes |
| ZIP SHA-256 | `22f3c50c86e82b448d59177a849cfca14d69e87123c572f5f43abd78f258e40d` |
| Sole member | `DSP.bin`, 457,000 bytes |
| DSP SHA-256 | `c0d6061ea17d642b2a002aa269ae1217db21899afa84dfc5458a4e9c9ce02aca` |
| FreqChip CRC | `83713712` |

The member ends at `0x6f928`, within the stock 112 erase sectors. Two offline builds matched. The Xtensa fixture verified initial miss, the page write, retained hit, corrupted-cookie miss, original call-through, and busy/unsafe UART cases. HiFi3 disassembly confirmed the pre-relocation read. The fixture does not model physical SRAM retention. [Assembly](checkpoints.S) · [Fixture](smoke.S)

```sh
wake_build=$(mktemp -d)
python3 -B almost-universal/firmware/dsp-v48-display-check/build.py \
  artifacts/universal-remote/WoRWS_freq_app_V48.zip "$wake_build/wake.zip" \
  --retention --smoke \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$wake_build/wake.zip" artifacts/universal-remote/WoRWS-v4.8-DSP-WAKE-RETENTION.CANDIDATE.zip
```

## Bench sequence after the Controls A trial

1. The Controls A capture already verified fresh DSP entry after a key-free pickup and recorded an ordinary Reset control at 115200. The retention image is for the remaining RAM comparison. [Existing receiver and wiring](README.md#receive-only-capture-on-the-bench-mac)
2. After the action and timeout trials, pin the separate diagnostic and use the same checked app-origin DSP-only route. Verify the normal handoff reply, destination zero and CRC ACK. Once **WAKE TEST** is visible, capture pickup after confirmed idle, Down after a separate idle interval, and a separately timestamped ordinary recessed Reset with KATA released. Let **WAKE TEST** return to seed the cookie between cases. A confirmed power-loss boot, if already available, provides a separate cold control. These observations use the existing DSP_TX lead.

| Results | Meaning |
| --- | --- |
| Pickup `DSP:R`, deliberate reset `DSP:E` | Supports a DSP-only retained cookie as a discriminator between the tested wake and reset paths. Repeat the observations before using it to skip the splash. |
| Pickup `DSP:R`, deliberate reset `DSP:R` | The cookie survives both paths. It cannot preserve a splash on deliberate reset without a second signal. A true power-loss control remains distinct. |
| Pickup `DSP:E` after a visible, seeded page | The word did not reach app entry intact. It cannot distinguish this pickup from an entry without a prior cookie. |
| Loader banner only or no capture at pickup | The scratch state and entry marker are unobserved. Compare timestamps and the positive reset control. |

The diagnostic always takes the stock display path regardless of the result. Gating the splash on the cookie requires a physical result that separates the desired boot and wake cases.
