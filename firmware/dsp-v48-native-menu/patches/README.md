# Rebuild the tested Office firmware offline

These are incremental DSP source changes for the SwitchBot W4600000 REV V06 on stock v4.8. The Office and compact Activities header builds ran on the spare. The shared header, visible wake diagnostic, and Watch TV entry build are separate offline candidates based on the compact header. The stock ARM and resource images stay in place.

Run from the repository root. Install Pillow 12.1.1 and put `qemu-system-xtensa` and the Espressif Xtensa tools on your path. Set `XTENSA_TOOL_PREFIX` to the executable prefix for Espressif esp-x32 2507 if it is outside your path. Supply your own exact `WoRWS_freq_app_V48.zip` and compare it with the [reference SHA-256](../../../docs/SHA256SUMS). This sequence builds into a temporary directory and runs the QEMU fixtures without contacting a remote.

```sh
set -e
stock=/absolute/path/to/WoRWS_freq_app_V48.zip
tools=${XTENSA_TOOL_PREFIX:-xtensa-esp32-elf}
source="$PWD/firmware/dsp-v48-native-menu"
patches="$source/patches"
splash="$PWD/images/handheld-splash-240-four-color.png"
build=$(mktemp -d)

python3 -B firmware/dsp-v48-display-check/build.py "$stock" "$build/display.zip" \
  --smoke --tool-prefix "$tools"
python3 -B "$source/build.py" "$build/display.zip" "$build/color.zip" \
  --handheld-color --smoke --tool-prefix "$tools"

mkdir -p "$build/base/firmware"
cp -R "$source" "$build/base/firmware/"
patch -p1 -d "$build/base" -i "$patches/handheld-factory-slot.QEMU-ONLY.patch"
patch -p1 -d "$build/base" -i "$patches/handheld-full-splash-cut.OFFLINE.patch"

cp -R "$build/base" "$build/stockops"
patch -p1 -d "$build/stockops" -i "$patches/handheld-splash-bypass-control.OFFLINE.patch"
patch -p1 -d "$build/stockops" -i "$patches/handheld-stock-ops-control.OFFLINE.patch"
python3 -B "$build/stockops/firmware/dsp-v48-native-menu/build.py" \
  "$build/color.zip" "$stock" "$splash" --stock-ops-control \
  --tool-prefix "$tools" --output "$build/stockops.OFFLINE.zip"

office="$build/base/firmware/dsp-v48-native-menu/build.py"
patch -p1 -d "$build/base" -i "$patches/handheld-office-controls.OFFLINE.patch"
python3 -B "$office" "$build/color.zip" "$stock" "$build/stockops.OFFLINE.zip" \
  "$splash" --tool-prefix "$tools" --output "$build/office.OFFLINE.zip"

patch -p1 -d "$build/base" -i "$patches/handheld-activities-header.OFFLINE.patch"
python3 -B "$office" "$build/color.zip" "$stock" "$build/stockops.OFFLINE.zip" \
  "$build/office.OFFLINE.zip" "$splash" --tool-prefix "$tools" --output "$build/header.OFFLINE.zip"

for variant in shared-header visible-wake watch-tv-entry; do
  cp -R "$build/base" "$build/$variant"
  patch -p1 -d "$build/$variant" -i "$patches/handheld-$variant.OFFLINE.patch"
  python3 -B "$build/$variant/firmware/dsp-v48-native-menu/build.py" \
    "$build/color.zip" "$stock" "$build/stockops.OFFLINE.zip" \
    "$build/office.OFFLINE.zip" "$build/header.OFFLINE.zip" "$splash" \
    --tool-prefix "$tools" --output "$build/$variant.OFFLINE.zip"
done

shasum -a 256 "$build/"*.zip
```

| Output | SHA-256 |
| --- | --- |
| `display.zip` | `2b67114a10c922ea7b2dccd2ed2173cb21c64d613b795b7bc067e19f2def09ad` |
| `color.zip` | `c48f06501cc8e3d317fe3c8ae56c580558b39e5b7c826fd59eb5dd16fc7a01ab` |
| `stockops.OFFLINE.zip` | `9e2c5dfd15a6376a1d2b16754db5942615dd838d366fdcf23e472b91846407a4` |
| `office.OFFLINE.zip` | `b887ffddbef82a7ff78b23ee867b2424d2ce530754de32ffa82d76d3d9d3263c` |
| `header.OFFLINE.zip` | `0ab181911b1982c0b8791ef1518977f652a67fade37f2f41bbd2923d38a4fbe2` |
| `shared-header.OFFLINE.zip` | `885ab69118a0570b8aea0232f724f7b2d355bef175aa99e3ab5fba44e9f5d256` |
| `visible-wake.OFFLINE.zip` | `a552534b627c0e4f4f0e6cda7138e15be527ba2207df14d848778e6f6440bbf0` |
| `watch-tv-entry.OFFLINE.zip` | `0ad5d40397479253b5b116001cf649117e169e90692ccb6a620dae0890c9f68d` |

For the earlier combined splash, build the base immediately after applying the factory and splash patches. For the splash-off and First-Activities diagnostic builds, apply their incremental patches to a separate copy. [Combined cut and trade-offs](../../../docs/handheld-combined-cut.md) · [Hardware results and rollback](../../../docs/first-hardware-milestone.md#current-evidence)
