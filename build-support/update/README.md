# Fork update feeds on GitHub Releases

This checkout checks and downloads updates exclusively through
[`Natsuneko3/oink`](https://github.com/Natsuneko3/oink/releases).
It does not use the upstream update domain or discover releases in `oinkvm/oink`.
The XML namespace ending in `/xml-namespaces/update` is a schema identifier,
not a network request or fallback source.

## Hosting and client policy

Signed update metadata lives in a fixed **prerelease** tagged `update-feed`.
Installers remain on their corresponding published version Releases (`vX.Y.Z`).
The feed Release is independent of the latest product Release, so a newly
published version cannot temporarily remove the feed and Windows metadata can
be renewed without editing product Release assets.

| Client | Asset on the `update-feed` Release |
| --- | --- |
| macOS arm64 | `mac-v1-mac-2026-01-stable-appcast.xml` |
| macOS x64 | `mac-v1-mac-2026-01-x64-stable-appcast.xml` |
| Windows x64 | `windows-v1-win-2026-01-stable-manifest.json` |

The download prefix is
`https://github.com/Natsuneko3/oink/releases/download/update-feed/`.
Publishers retain the internal `site/mac/` and `site/windows/` layout and flatten
`/` to `-` only at the Release upload/readback boundary. Stable and retained
beta paths, heartbeat and platform catalogs follow the same mapping.

Both clients reject an initial installer URL outside
`https://github.com/Natsuneko3/oink/releases/download/<tag>/<asset>`.
GitHub redirects to its HTTPS asset CDN remain supported. There is no fallback
to upstream when a feed is absent, expired, invalid or unavailable.

macOS retains Sparkle archive/feed signature verification. Windows retains
Ed25519 metadata and package signatures, exact SHA-256/length, expiry, replay
watermarks, compatible OS/architecture selection and build/version checks.
The user chooses when to download and install an offered update.
The automatic-check switch controls checks only.

## First-time signing setup (owner-run)

Independent macOS and Windows update-signing keys are now configured in
`packaging/update-trust.json` and both client update gates are enabled. Private
keys are backed up in the login Keychain; the corresponding GitHub secrets live
in this fork's `release` environment. The owner explicitly authorized setup and
enablement without packaging or test runs on 2026-11-10. Real N→N+1 and failure/
rollback qualification remain pending; a newly configured gate does not change
already installed binaries. Do not replace these public roots with upstream or
test keys.

The following commands document first-time provisioning and have already been
performed for this fork. Do not rerun them to rotate or overwrite these keys.
The setup scripts are normally owner-run; this setup was performed with the
owner's explicit authorization. CI must never provision production keys.
They retain private bytes in the login Keychain and send GitHub secrets via
stdin. Only public keys are written to the checkout.

Prerequisites: authenticated `gh`, OpenSSL 3 on `PATH`, and access to this fork.
Create the `release` GitHub environment before running the scripts:

```sh
gh api --method PUT repos/Natsuneko3/oink/environments/release
export PATH="/opt/homebrew/opt/openssl@3/bin:$PATH"
python3 build-support/update/setup-macos-key.py
python3 build-support/update/setup-windows-key.py
```

The keys are independent of the upstream Keychain entries:

| Platform | Keychain account | Secret in the `release` environment |
| --- | --- | --- |
| macOS | `Natsuneko3-oink-mac-2026-01` | `SPARKLE_ED25519_PRIVATE_KEY` |
| Windows | `Natsuneko3-oink-win-2026-01` | `WINDOWS_UPDATE_ED25519_PEM_WIN_2026_01` |

Do not overwrite or rotate an existing key to recover from a failed upload.
Inspect the backup and configuration first; existing installed clients require
a deliberate trust-root migration if a key is rotated.

Publishers use the built-in `github.token` with explicit `contents: write` for
both `update-feed-state` fast-forward writes and Release asset uploads. No
personal access token or `UPDATE_FEED_WRITER_TOKEN` secret is needed. Signing
jobs read secrets directly from their `release` environment rather than passing
them through reusable-workflow callers. Protect the data branch from force
pushes and deletion, while allowing ordinary fast-forward writes. No GitHub
Pages configuration, DNS record or custom domain is required.

Initialize the empty data branch and fixed feed Release using the manual
**Bootstrap fork update Release** workflow (`bootstrap-update-site.yml`).
The workflow refuses to overwrite an existing initialized/live state.

Keys have been backed up and the owner requested both `enabled` fields be set
to `true` before any packaging or testing. Complete the platform's N→N+1,
failure and rollback qualification later, before offering real production
updates. Keep the public configuration committed **before building the first
update-capable release**. Enabling the feed on the server cannot retroactively enable an
already-installed manual-only build; install that first capable build manually.
Mac and Windows gates are independent.

## Publish a product Release and offer it to clients

1. Build the customized code and create the draft with the manual `release.yml`
   workflow on the default branch. Retain the package provenance, source archive,
   native inspections and license audits. Use a build number greater than any
   already installed build; a `+custom` version suffix alone does not advance
   update precedence.
2. Inspect and publish the version Release in this fork. Merely publishing the
   Release does not offer it to clients. Draft/prerelease product Releases are
   rejected by the feed publisher.
3. Set the desired stable update notes in `.github/update-notes.json` on the
   trusted default branch. The publisher takes notes and executable code from
   that dispatch commit; release tags are inspected as data, never executed.
4. Run the manual **Seed published stable release feeds** workflow. For example:

   ```sh
   gh workflow run seed-update-feeds.yml --repo Natsuneko3/oink --ref main \
     -f release_tag=v0.3.6 -f platform=windows
   ```

   Select `mac`, `windows` or `both` for the platforms actually built and
   qualified. The Windows signer binds the published MSI to its tag, source tree
   and final asset bytes; the macOS signer verifies the notarized app and archive
   before generating signed Sparkle metadata.
5. The deployment job merges the candidate into the latest protected snapshot,
   uploads its feed assets to `update-feed`, reads back the exact public bytes,
   and commits the state with CAS. Failure restores the frozen prior hosted
   snapshot and verifies rollback rather than marking the candidate deployed.

The fixed feed Release must stay a prerelease so it does not become the latest
stable product Release. Do not manually replace signed feed assets or installer
bytes. Updating a version's GitHub Release description does not rewrite signed
client update notes.

Windows manifests expire within 30 days. **Renew Windows update manifests** runs
daily using the unchanged verified catalog, durably reserves increasing
sequences, signs fresh exact bytes, and republishes to the same feed Release.
Its release-environment signing key and workflow token write permission must remain available.

## Automated custom development Releases

`custom-release.yml` builds Windows x64 plus macOS arm64/x64 entirely on GitHub
hosted runners. It publishes the custom Release and then signs and deploys both
update feeds using the keys in the `release` environment:

```sh
gh workflow run custom-release.yml --repo Natsuneko3/oink --ref main \
  -f build=114 -f release_tag=v0.3.5-custom.1
```

This fork defaults to `--signing-mode apple-development` for local and GitHub Mac
packages, using the pinned certificate and team in `packaging/identity.json`, without
notarization. GitHub imports the password-protected identity from
`MACOS_DEVELOPMENT_CERTIFICATE_P12` and `MACOS_DEVELOPMENT_CERTIFICATE_PASSWORD`
in the `release` environment, verifies `MACOS_DEVELOPMENT_SIGNING_FINGERPRINT`,
and always removes its temporary keychain. Private certificate material never
belongs in source control. The explicit `--development-signing` flag retains the
ad-hoc path for local diagnostics; current custom releases require the configured
Apple Development identity. Windows MSI is unsigned by Authenticode. The distribution metadata
explicitly records those facts, while Ed25519/Sparkle signatures still authenticate
the exact update packages. It does not depend on an upstream Sentry project.
The source archive comes from the exact Git commit built by the runners.

`mac.allow_development_updates: true` is the explicit opt-in for this fork's
unnotarized update catalog. Development publication records have no claimed
Developer ID or N→N+1 qualification; their code-signature integrity, architecture,
bundle/build identity, source and release hashes are checked before update signing.
The original `release.yml` and formal feed publisher retain their original stricter
Developer ID/notarization requirements.

macOS Gatekeeper may require manual approval for the first installation. File
Provider/App Groups, virtual microphone installation, Keychain auto-unlock and
local DMG upgrades still have native signing/team requirements and are not
promised to work like the notarized distribution. No app is installed by this
workflow. A failed build cannot publish a partial product Release; a feed failure
restores the prior hosted snapshot and retains consumed sequence reservations.

## Existing package-signing prerequisites

Changing the update source does not provision native code-signing credentials.
The existing production Mac pipeline requires Developer ID signing,
notarization and signed native launch checks. Some existing package-verification
checks use this fork's team `D765989V7S`. The previous upstream App Group directory
is preserved: changing signing teams does not migrate or delete existing local data.
Apple Development does not satisfy Developer ID or notarization requirements. Never remove those checks to make an unsigned package pass.
Windows Authenticode pins are additionally enforced if configured; the mandatory
Ed25519 feed/package signatures remain required even without Authenticode pins.

The signing environment, keys, fixed feed Release and data branch have been
initialized. Update-related source/configuration is synchronized using a
`[skip ci]` configuration commit, without packaging, test runs, or app replacement.
Installed binaries retain their compiled source and trust roots until rebuilt
and manually replaced. The feed does not offer a product update until a
versioned installer Release has been published and signed into its catalog.

## Validation

Use OpenSSL 3 on `PATH` for Python signature tests. The relevant checks are:

```sh
python3 -m unittest discover -s packaging/tests
cargo test -p oink-update
npm test --workspace apps/oink
npm run typecheck --workspace apps/oink
```

The native Sparkle continuation tests are compiled by `build-support/ci.py`
using the pinned Sparkle framework. Local tests do not replace real Windows
service/MSI qualification or a signed, notarized macOS N→N+1 installation.
