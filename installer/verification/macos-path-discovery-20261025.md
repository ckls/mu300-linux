## macOS package discovery regression (2026-10-25)

The original report did not include its exact error or launch step, so its specific cause remains unconfirmed. Source inspection found that the macOS startup folder picker accepted an unchecked selection once, cancellation became a startup error, and every backend spawn failure was reported as a missing Windows backend. These defects are corrected in the shared native host.

Startup validates the selected distribution and the macOS backend before launch. An invalid selection can be retried; cancellation exits normally. Folder resolution handles the APP/Contents, files/desktop, spaces, Unicode and one explicitly selected archive wrapper. Multiple releases require an explicit choice. No working-directory or unrelated-folder search is used, and a damaged package never silently switches to a nested release. Backend verification normalizes the same user selections before applying the existing payload hashes and model checks. The child process uses the selected root as its working directory. Spawn failures show the actual platform-specific executable and OS error. The new Rust module is included in artifact source fingerprints.

Validation used disposable host files and simulated package structures, without ADB/SSH or device writes:

- E5 Windows installer suite: 339 tests, 277 passed and 62 environment-dependent skips.
- MU300 Windows installer suite: 330 tests, 266 passed and 64 environment-dependent skips.
- Linux package-path suite: 7 passed, including real directory symlinks.
- The native resolver is compiled and executed directly by test_distribution_paths.py: 7 Rust tests passed on Windows, including invalid-selection retry and cancellation.
- Windows cargo check --offline --tests -j 2 passed for the complete Tauri host; Rustfmt parsing and scoped whitespace checks passed.

Logs are under out/build-logs in each repository, tasks macos-package-regression, macos-path-posix, macos-path-native-check and macos-path-final-native. Native macOS Finder/Gatekeeper launch and the users' original failures have not been reproduced. Existing APP/EXE artifacts and firmware archives were not rebuilt or repackaged; changed source fingerprints require fresh native artifacts before a future release.
