# E5 bootloader-state preflight — 2026-10-25

The E5 GUI adapter, compatible Python entry and Magisk TF worker no longer require an orange verified-boot property or prior bootloader unlocking. The shared adapter's E5 compatibility branch in the MU300 repository has the same BL policy; its MU300-specific branch is unchanged. No unlock command, AVB-disabling operation or partition write was added.

Preflight still requires working root, matching package/model/board, valid Android slots, the existing boot/firmware partitions and bundled tools. Boot-chain checks, Android slot protection, backups, hashes and readback verification remain in their existing paths. Documentation no longer declares bootloader unlocking mandatory.

Device-free validation:

- E5 installer suite: 342 tests, 280 passed, 62 environment-dependent skips.
- MU300 mirror suite: 334 tests, 268 passed, 66 environment-dependent skips.
- GUI probe tests cover six E5 profiles with orange, green, yellow, red, empty and missing boot-state values. Missing root, wrong model and invalid slot still prevent further inspection.
- Real compatible CLI preflight executes for all six profiles on Android A and B without querying the former BL gate. Missing root, wrong model/board or invalid slot stops before tool upload.
- Native Magisk preflight: one test with 63 simulated cases, including both Android slots, five boot states for each profile, missing geometry tools and wrong K1/41S boards. Valid cases reach an intercepted boot-control check; no real block device is used.
- Hybrid package tests: 8 passed. Android root-tool tests: 6 passed. Slot-role and boot-image/AVB preservation tests: 6 passed.

Logs are in out/build-logs under the e5-bl-* task labels. The first WSL slot-role run lacked the Python lz4 module; the same six tests passed using the existing Windows Python environment. A mirror-suite fixture commit initially waited for the host's GPG signing configuration; the full rerun disabled signing only in that test process and passed. No repository or global Git signing setting was changed.

No device was connected, flashed or unlocked. Locked-device hardware boot acceptance was not tested. Existing executable artifacts and firmware packages were not rebuilt; new native sidecars and compatibility executables are required before distributing this change.
