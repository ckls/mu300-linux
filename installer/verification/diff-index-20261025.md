# Diff Studio version indexes — 2026-10-25

Implemented in the shared installer and mirrored into MU300. Native Windows/macOS file dialogs accept an old full ZIP or version-index JSON, retain full-package input for the new release, and provide index-folder/export actions. Successful compatible analysis saves the generated target baseline automatically under application data/release-indexes. There is no automatic claim that the device has installed that version.

The version-1 index stores release identity, boot hash, full file descriptors and APK version/dependency records, with a SHA-256 over canonical data. It carries no file payloads or device identifiers. Generated updater overlays are included before snapshotting. Import checks format/version, integrity, duplicate keys, path safety, descriptors, bounded file size and metadata. Content-addressed version files are retained separately. Atomic writes flush the file; POSIX also flushes the directory. Existing export files are not overwritten. Invalid/blocked analyses clear the current export binding and do not save a new target.

Validation used only temporary releases, regular-file filesystems, fake UI transports and local browser servers:

- Full Windows installer suites: E5 351 cases, 288 passed/63 skipped; MU300 343 cases, 276 passed/67 skipped.
- Final focused index suite: Linux 11 passed; Windows 10 passed/1 Linux-engine case skipped, in each repository's host tests.
- Complete old-package and saved-index generation produced identical patch manifests and payload bytes after deleting the old releases. Repeated caching, moved/renamed indexes, boot hashes, package records, permissions, links and xattrs were checked.
- The real E5 ext4 reader fixture creates three small ext4 files with mke2fs in WSL. It deletes the middle release, generates the next patch using its index, and verifies the exported payload with Patch.
- Two real Engine transactions were applied to a temporary Linux root using injected updater/runtime files. The second patch used the saved target index after its full package was deleted, preserved updater descriptors correctly and reached the third release.
- Service reopening/custom application data and the real portable CLI analyze/generate commands were exercised without the old package.
- Corruption, unsupported versions, duplicate JSON fields, traversal, invalid descriptors, missing new payloads, blocked/incompatible analysis, existing export targets and interrupted publication were rejected.
- Both production frontend builds and Windows Tauri cargo check --offline --tests -j 2 passed.
- Both Diff Studio/Patch Updater browser suites passed, including JSON drag/drop, export/cancel, folder actions, stale-state clearing, bilingual UI, themes, minimum-size bounded scrolling, HiDPI drops, existing patch export, update checks and restart/status flows.

Build/test logs are under out/build-logs with diff-index-* task labels. Browser logs are diff-index-browser-20261025.log in each repository; screenshots are work/diff-index-preview.png and work/ota-ui-preview.png. Windows test fixture Git signing was disabled only in the test process, without changing Git configuration.

No ADB/SSH connection, device mutation, native installer release build or firmware packaging was performed. Native macOS dialog/runtime behavior remains untested on actual macOS. Existing APP/EXE and release archives are unchanged; future distribution must rebuild the matching native artifacts through the existing build workflow.
