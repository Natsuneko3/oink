# Oink signed release

This release is automatically built by GitHub Actions from the main-branch commit associated with its release tag. The plain version number and numeric build are reserved automatically.

Includes upstream 0.3.6: redesigned automatic updates, group-wide device ordering with drag-to-reorder, more pointer event rate limits, an optional switch-pointer-position shortcut, and fixes for microphone capture, Windows service responsiveness, display policy and installer restarts. The fork retains its per-device option for independent local keyboard/mouse control while gaming and its input-routing changes.

- **macOS Apple silicon:** arm64 DMG and ZIP, macOS 14.2 or later.
- **macOS Intel:** x64 DMG and ZIP, macOS 14.2 or later.
- **Windows:** unsigned x64 MSI, Windows 10 version 1809 or later, or Windows 11.

The macOS applications use the owner’s Apple Development certificate (Team ID `D765989V7S`) and are not notarized by Apple. Both local and GitHub builds use the same signing certificate and update verification key. Only GitHub-built artifacts are published in this Release. A later GitHub release with a higher build can update a local installation through the app’s normal update flow. The Windows installer is not Authenticode signed.

The new updater uses signed v2 catalogs and macOS DMG packages from this fork’s GitHub Releases. Signed v1 ZIP appcasts and Windows manifests remain available for older clients. Numeric builds now encode the selected release version while preserving ordering above historical fork releases.

If the arm64 package metadata records `development_cross_compile: true`, that package was cross-compiled on an Intel Mac. Its native ARM launch smoke and HAL runtime tests were not run in CI; the metadata records `not-run` with reason `cross-compilation`. Architecture, package content, and code-signature checks still run. Native Intel Mac packages continue to require their runtime checks.

The release also includes its source archive, package metadata, and SHA-256 checksums. Debug symbols remain separate GitHub Actions artifacts.
