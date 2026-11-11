# Oink 0.3.5 custom release

This custom release is built by GitHub Actions from the exact source commit associated with its release tag.

Includes the current local input-routing changes and a per-device option for independent keyboard/mouse control while gaming; audio and clipboard sharing are unchanged.

- **macOS Apple silicon:** arm64 DMG and ZIP, macOS 14.2 or later.
- **macOS Intel:** x64 DMG and ZIP, macOS 14.2 or later.
- **Windows:** unsigned x64 MSI, Windows 10 version 1809 or later, or Windows 11.

The macOS applications use ad-hoc signatures and are not notarized by Apple. The Windows installer is not Authenticode signed.

If the arm64 package metadata records `development_cross_compile: true`, that package was cross-compiled on an Intel Mac. Its native ARM launch smoke and HAL runtime tests were not run in CI; the metadata records `not-run` with reason `cross-compilation`. Architecture, package content, and code-signature checks still run. Native Intel Mac packages continue to require their runtime checks.

The release also includes its source archive, package metadata, and SHA-256 checksums. Debug symbols remain separate GitHub Actions artifacts.
