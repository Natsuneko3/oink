# Fork update feeds on GitHub Releases

This checkout checks and downloads updates exclusively through
[`Natsuneko3/oink`](https://github.com/Natsuneko3/oink/releases).
It does not use the upstream update domain or discover upstream releases.
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
| macOS arm64 v2 | `mac-v2-mac-2026-01-arm64-stable-manifest.json` |
| macOS arm64 legacy Sparkle | `mac-v1-mac-2026-01-stable-appcast.xml` |
| macOS x64 v2 | `mac-v2-mac-2026-01-x64-stable-manifest.json` |
| macOS x64 legacy Sparkle | `mac-v1-mac-2026-01-x64-stable-appcast.xml` |
| Windows x64 v2 | `windows-v2-win-2026-01-x64-stable-manifest.json` |
| Windows x64 legacy | `windows-v1-win-2026-01-stable-manifest.json` |

The download prefix is
`https://github.com/Natsuneko3/oink/releases/download/update-feed/`.
Publishers retain the internal `site/mac/` and `site/windows/` layout and flatten
`/` to `-` only at the Release upload/readback boundary. Stable and retained
beta paths, heartbeat and platform catalogs follow the same mapping.

Both clients reject an initial installer URL outside
`https://github.com/Natsuneko3/oink/releases/download/<tag>/<asset>`.
GitHub redirects to its HTTPS asset CDN remain supported. There is no fallback
to upstream when a feed is absent, expired, invalid or unavailable.

Mac v2 signs DMGs and catalog envelopes with the existing Sparkle Ed25519 key;
legacy Mac clients retain signed ZIP appcasts. Windows retains
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

## Automated fork publication

`custom-release.yml` builds Windows x64 and Apple Development signed macOS
arm64/x64 packages on GitHub runners. Public versions are numeric and build
numbers encode their version plus a reserved sequence. `custom_feed.py` binds
the final public Release to its tag, source tree, commit and artifact digests;
it publishes Windows v1/v2 and Mac ZIP v1/DMG v2 feeds together.

The Mac development path requires `mac.allow_development_updates: true`,
`signing: apple-development`, and the exact team and certificate fingerprint
from `packaging/identity.json`. It verifies the DMG, mounted app and every native
binary against that identity before issuing Ed25519 package signatures. Receipts
explicitly state development signing and lack of notarization; they never claim
Developer ID qualification. Changed development records also require the exact
`OINK_PUBLISHED_BUILD` authorization at the candidate boundary. Ad-hoc packages,
other certificates and other teams are rejected. The separate Developer ID
publisher still requires notarization, a stapled ticket and qualification.

A publication reserves Windows v1/v2 sequences in `update-feed-state` before
signing its manifests, then durably reserves Mac v2 sequences before signing
those manifests. Neither reservation publishes candidate site bytes. The final
transaction merges both platform candidates, preserving the deployed other
platform, and uploads a complete snapshot. Every canonical public asset must
match before the state CAS advances. Failures restore and read back the frozen
parent, including absence of newly introduced v2 catalogs and receipts.

A retry is complete only when both v1 feeds and every active v2 architecture /
channel catalog contain this exact Release, then signature and public readback
verification pass. A v1-only deployment continues publication to add v2.

## Manual publication and channel promotion

`seed-update-feeds.yml` accepts a published tag and platform (`mac`, `windows`,
or `both`) on the trusted default branch. It calls independent platform
publishers. Tags are inspected as data; their workflow code is never executed.
The release's live GitHub prerelease flag chooses beta or stable. A beta tag
must stay a prerelease. A numeric release may first publish to beta, then be
promoted by clearing its prerelease flag and dispatching the same build again.
Promotion preserves every package byte and field except the catalog channel.

Committed `.github/update-notes.json` contains only `severity` and multilingual
`notes`, including `en` and `zh-Hans`; it does not select a channel. Beta releases
enter v2 beta catalogs only. Stable releases enter stable and beta catalogs,
and legacy v1 feeds. The automated development publisher offers stable public
fork Releases. The manual Mac publisher remains the Developer ID path.

## Feed v2 and renewal

Signed v2 envelopes use Ed25519 over the exact payload bytes with a 30-day TTL.
Their internal paths are:

- `windows/v2/<epoch>/x64/<channel>/manifest.json`
- `mac/v2/mac-2026-01/<arm64|x64>/<channel>/manifest.json`
- Mac public package receipts: `mac/releases/<build>/<architecture>.json`

All paths are flattened through `feed.asset_name` / `feed.public_url` for the
fixed GitHub Release host. `release_assets.py` uploads only allowlisted managed
paths, rejects collisions and removes stale managed assets on rollback while
preserving unrelated uploads. No GitHub Pages host or writer-token secret is
used. `packaging/update-trust.json.sources` contains the fork Release download
prefix; `deploy.py` rejects sources without a matching transaction target.

`feed_v2.py` builds catalogs from verified per-build snapshot records, not the
pending reservation lists. It reserves each sequence in
`registry.v2.<manifest path>.last_allocated`. Allocation can change expiry and
rules without changing release entries. New releases or beta-to-stable promotion
need a publication build authorization. Failed sequences are never reused, and
merges reject stale or superseded reservations.

`packaging/update-rules.json` describes installed-version ranges, compiled into
inclusive build ranges by `rules.py`. Rules end with a catch-all. Critical
notices require `en` and `zh-Hans`; explicit targets must exist in the catalog.
A rules-only change is distributed by running renewal.

`renew-windows-update-manifests.yml` runs daily at 03:17 UTC. It renews Windows
v1/v2, deploys through the existing fork Release transaction, then renews and
deploys Mac v2 serially on macOS. Windows renewal sees only the Windows key;
Mac signing sees only `SPARKLE_ED25519_PRIVATE_KEY` through the pinned official
signer on stdin, supporting both seed and legacy expanded Sparkle keys. OpenSSL
3 verifies every resulting Ed25519 signature. Mac v1 appcasts have no TTL.
Unpublished or disabled platform catalogs are skipped independently. All state
writers hold concurrency group `oink-update-feed-publish`.

The expiry monitor checks Windows v1 and every active v2 source, verifying
expiry, replay watermarks, signatures and the public heartbeat. A successful
renewal deployment updates the heartbeat even when signed bytes remain valid.

## Settings and qualification

Default policy is **stable / automatic checks / notify**. Notify is the only
production behavior, not a persisted mode: preferences contain checks_enabled
and channel only. Checking never downloads or installs a candidate. The user
explicitly downloads it, then clicks Install when its typed phase is Ready.
Manual Check is never rate-limited: concurrent requests share the queued or
active check and its status/events result; a completed check can be refreshed
immediately. Only background checks use the daily scheduling interval.
Install immediately interrupts input, audio (including silent open streams),
drag/promises, clipboard/file transfer and other sharing work; it never waits
for an idle interval, session unlock or activity completion. The backend closes
new-work admission, releases held input through an injection fence, restores
source mute while suspending audio, and temporarily suspends its provider before
replacement/relaunch. Failed cleanup/integration or another installer produces
a bounded explicit failure; no hidden retry or WaitingForIdle continuation.
Aborted preparation reopens admission and reconciles audio without changing the
user's forwarding preferences or exit selection.

There is **no production automatic-install setting, IPC command or CLI option**.
Qualification automation belongs only to the external TEST harness, which polls
normal status and explicitly sends Check, Download and Install(expected_build)
against the installed TEST build. It uses the same immediate Install path as a
click, without synthetic input, an automatic-mode preference or a safety bypass.
Stored policies with unknown fields (including a removed mode) are invalid under
the existing strict parser; there is no migration for unreleased TEST state.

Check-for-updates uses native update IPC when enabled; disabled versions open
Releases. Mac settings are per-user; Windows settings are machine-wide and normal
users see why administrator permission is needed. The package pipeline rejects
the removed idle-install phase/policy in both executable and frontend content.

Qualification uses **TEST** Ed25519 material and an isolated source export with
a compiled loopback feed. Production binaries expose no runtime key or URL
override. The external harness drives the normal Check, Download and
Install(expected_build) IPC against the installed test build. Record N→N+1
replacement and relaunch, immediate sharing interruption, rejected/corrupt
packages and recovery to a usable app separately. Legacy Sparkle installation
needs separate coverage from the v2 DMG installer. Unit tests and packaging
smoke do not establish live installation or post-install recovery qualification.
