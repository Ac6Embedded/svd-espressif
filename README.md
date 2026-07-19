# Espressif SVD collection

CMSIS SVD files for Espressif ESP32 series chips, one folder per chip at the repo root.
Folder names are the uppercase chip stem without dashes (ESP32S3, ESP32C6LP).
File names keep the upstream stem (esp32c6-lp.svd). Fetched 2026-07-19.
14 files, about 32 MB. Every file parses with Python xml.etree and has root element `device`.

## Coverage

| Family    | Files | CPU core    | Source          | Provenance |
|-----------|-------|-------------|-----------------|------------|
| ESP32     | 1     | Xtensa LX6  | espressif/svd   | pristine   |
| ESP32C2   | 1     | RV32IMC     | espressif/svd   | pristine   |
| ESP32C3   | 1     | RV32IMC     | espressif/svd   | pristine   |
| ESP32C5   | 1     | RV32IMAC    | esp-rs/esp-pacs | community  |
| ESP32C6   | 1     | RV32IMAC    | espressif/svd   | pristine   |
| ESP32C61  | 1     | RV32IMAC    | esp-rs/esp-pacs | community  |
| ESP32C6LP | 1     | RV32IMAC    | espressif/svd   | pristine   |
| ESP32H2   | 1     | RV32IMAC    | espressif/svd   | pristine   |
| ESP32P4   | 1     | RV32IMAFC   | espressif/svd   | pristine   |
| ESP32S2   | 1     | Xtensa LX7  | espressif/svd   | pristine   |
| ESP32S2ULP| 1     | RV32IMC     | espressif/svd   | pristine   |
| ESP32S3   | 1     | Xtensa LX7  | espressif/svd   | pristine   |
| ESP32S31  | 1     | RV32IMAFC   | esp-rs/esp-pacs | community  |
| ESP32S3ULP| 1     | RV32IMC     | espressif/svd   | pristine   |

Xtensa chips: ESP32, ESP32-S2, ESP32-S3. Everything else is RISC-V,
including the ULP and LP coprocessor files (ESP32S2ULP, ESP32S3ULP, ESP32C6LP),
which describe the low power RISC-V coprocessor view of those chips.

## Sources

1. espressif/svd (official Espressif repo)
   URL: https://github.com/espressif/svd
   Commit: be20aa12560889d6125d144cdb48cf615ac17628
   Files: 11, taken unchanged from `svd/*.svd`.
2. esp-rs/esp-pacs (community peripheral access crates)
   URL: https://github.com/esp-rs/esp-pacs
   Commit: 30cb7c50e0a9516a222c96b70588f8930c7d4c12
   Files: 3, only chips absent from espressif/svd: esp32c5, esp32c61, esp32s31.
   Copied from `<chip>/svd/<chip>.base.svd` and renamed to `<chip>.svd`.

## Provenance legend

- pristine: copied unchanged from the vendor's official repo.
- community: copied unchanged from a community repo. The esp-pacs repo commits
  only the unpatched vendor base SVD (`<chip>.base.svd`). Its svdtools yaml
  patches are applied when the Rust crates are built and no patched SVD is
  committed, so these files are vendor base data redistributed by esp-rs.

## LICENSE AND REDISTRIBUTION STATUS

- espressif/svd: the repo LICENSE is the Apache License, Version 2.0. The file
  opens with "Apache License, Version 2.0, January 2004" followed by the full
  terms. SPDX: Apache-2.0. Copied to `LICENSES/espressif-svd-LICENSE.txt`.
  Apache-2.0 allows redistribution provided the license text ships with the
  copies, which this repo does.
- esp-rs/esp-pacs: dual licensed. LICENSE-APACHE is the same Apache License,
  Version 2.0 text. LICENSE-MIT is the MIT license, "Copyright 2022 esp-rs".
  Cargo.toml states `license = "MIT OR Apache-2.0"`. Both texts are copied to
  `LICENSES/esp-pacs-LICENSE-APACHE.txt` and `LICENSES/esp-pacs-LICENSE-MIT.txt`.
  Redistribution is allowed under either license with the text included.

## Refresh

    python fetch.py

Needs git on PATH and network access. The script clones changed repos into
`.work/`, rebuilds their family folders, rewrites `manifest.json`, validates
every file, and deletes `.work/` when done (pass `--keep-work` to keep it).
Commit SHAs in `manifest.json` will move to the new HEADs.

The fetch is incremental: it first compares each upstream HEAD against
`manifest.json` via `git ls-remote` and downloads only sources that changed,
printing `up to date` and touching nothing when both match. A GitHub Action
(`.github/workflows/check-updates.yml`) runs it weekly on Monday 06:00 UTC
and commits any updates.

## Known gaps

- The esp-pacs yaml patches fix known errors in the vendor SVDs. They are not
  applied here, so all files carry the vendor data as published.
- No SVD exists for ESP8266 in either source.
- The task spec expected esp-pacs to fill only esp32c5 and esp32c61. The repo
  also carries esp32s31 (a RISC-V chip with its own PAC crate), included here.
