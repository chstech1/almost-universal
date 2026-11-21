# V06 handheld firmware for Home Assistant

This ARM application reads the W4600000 V06 controls, displays a menu from Home Assistant and sends each input to Home Assistant over Bluetooth Low Energy. The first test uses soft key A to toggle a switch chosen during setup. The same firmware works for different switch entities. Home Assistant stores the bindings and calls the switch service.

## First test

A user with compatible firmware would install the integration, accept the discovered handheld in Home Assistant and choose a switch. An existing local Bluetooth adapter or active ESPHome Bluetooth proxy can supply the connection. A new setup then shows **Toggle** over the first physical key. Press A once to toggle and again to toggle back. On an existing setup, bind soft key A on a test screen to **Toggle switch** for the **Press** event. [Integration setup](../../docs/remote-design.md)

This is a development ARM image. Physical boot, radio discovery, the screen, key timing, board power and independent recovery of the replacement ARM firmware on V06 still require verification. The successful stock rollback used the original ARM updater. This application provides a Home Assistant service and omits the retail OTA recovery service. The deliverable is a raw ARM member and debug ELF for development. The current bench path uses the stock v4.8 ARM and an edited DSP. [Tested firmware and recovery path](../../docs/firmware.md#replacement-arm-prototype)

## Rebuild and test offline

Use Python 3.11+, Clang supporting arm-none-eabi, LLVM objcopy, LLD, and QEMU system ARM for the emulator check. On the development Mac, the script also locates Homebrew LLVM and the LLVM linker shipped with Rust. Run this command from the project root:

```sh
python3 firmware/v06/build.py --sdk /path/to/fr5080-6b8777c.tar.gz --out /tmp/v06-test --smoke
```

Use FR5080 MCU SDK revision `6b8777ce2aae695cac7374e73e5a0583f8618487`. Pass an extracted checkout to `--sdk`, or use the workspace archive with SHA-256 `84e8063b7516163554afca611167fc311dbdb9fcf1f951e965cadb1a1a72ccac`. The SDK is a separate dependency. The build links its MCU library, ROM symbol definitions and startup layout with the board drivers and the project’s UI and BLE service. It emits `ARM.bin`, a debug ELF, and a linker map offline. [FR5080 SDK mirror](https://gitee.com/magicedward/fr5080)

The Cortex-M3 smoke test uses the same compiled application, key and GATT service objects with simulated board sampling and radio calls. It exercises advertising the discovery UUID, a chunked menu write, commit, revision activation, notification enablement, two presses of A, hold/release and disconnection. The separate Home Assistant tests compile the C key/menu code, feed its frames through the HA integration and assert exact service calls.

```sh
python -m unittest discover -s tests -v
```

## Runtime scope

- The ARM uses its SSP panel path, holds the display DSP in reset while owning the shared pins, and polls the companion on PC0/PC1. The LCD updates in eight-row slices so input and radio service can run between transfers. Key changes must appear in two consecutive valid samples. Wheel scaling and sign are provisional until a physical capture.
- Menu updates are staged and validated before switching the displayed menu. Disconnection disarms outgoing events. Displayed menu data survives a Bluetooth disconnect in RAM. After a power cycle Home Assistant resends it. Persistent storage on the retail board awaits a verified writable allocation. A hold or release retains its original screen identity across local navigation.
- The formatted status and menu are editable on the HA side. The small built-in font supports Latin letters, digits and basic punctuation, with a fallback outline for other characters. The test firmware runs awake. Battery sleep/wake, authenticated device association, retail installation and recovery, and distribution rights for the linked vendor components are outstanding before general release.
