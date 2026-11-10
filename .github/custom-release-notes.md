# Oink 0.3.5 custom release

This custom release is built by GitHub Actions from the exact source commit associated with its release tag.

- **macOS Apple silicon:** arm64 DMG and ZIP, macOS 14.2 or later.
- **macOS Intel:** x64 DMG and ZIP, macOS 14.2 or later.
- **Windows:** unsigned x64 MSI, Windows 10 version 1809 or later, or Windows 11.

The macOS applications use ad-hoc signatures and are not notarized by Apple. The Windows installer is not Authenticode signed.

The release also includes its source archive, package metadata, and SHA-256 checksums. Debug symbols remain separate GitHub Actions artifacts.
