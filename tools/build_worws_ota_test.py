#!/usr/bin/env python3
"""Build the offline DSP-only test candidate for a stock W4600000 v4.8."""

import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


STOCK_DSP_SHA256 = "72ff3017d07537e000925babafc5f27ed1b9c0e0fe9d52cdac819e1b677adb45"
LABEL_OFFSET = 0x5EBC0
STOCK_LABEL = b"Charging"
TEST_LABEL = b"OTA TEST"


def build(stock_zip: Path, output: Path) -> None:
    with ZipFile(stock_zip) as source:
        stock = source.read("DSP.bin")
    if sha256(stock).hexdigest() != STOCK_DSP_SHA256:
        raise ValueError("DSP.bin does not match the stock W4600000 v4.8 image")

    label_end = LABEL_OFFSET + len(STOCK_LABEL)
    if stock[LABEL_OFFSET : label_end + 1] != STOCK_LABEL + b"\0":
        raise ValueError("Expected English charging label is missing")
    if len(TEST_LABEL) != len(STOCK_LABEL):
        raise ValueError("Test label must fit the stock string exactly")
    candidate = stock[:LABEL_OFFSET] + TEST_LABEL + stock[label_end:]

    with ZipFile(output, "x") as archive:
        archive.writestr(ZipInfo("DSP.bin"), candidate, compress_type=ZIP_DEFLATED)
    with ZipFile(output) as archive:
        if archive.namelist() != ["DSP.bin"] or archive.read("DSP.bin") != candidate:
            raise ValueError("Candidate archive did not verify")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_zip", type=Path)
    parser.add_argument("candidate_zip", type=Path)
    args = parser.parse_args()
    try:
        build(args.stock_zip, args.candidate_zip)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")
