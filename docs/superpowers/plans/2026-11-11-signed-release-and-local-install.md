# Signed GitHub release and local installation

User explicitly requests GitHub packaging and Release publication with the current Apple Development identity; simultaneously build a native arm64 package locally and replace the local application. Only GitHub-built artifacts may be uploaded to Release. This supersedes the previous no-local-build restriction. Preserve existing app and settings with recoverable backups, including the previous App Group namespace.

Target: v0.3.5-custom.2, numeric build116 (previous installed/released build114; cancelled earlier build115 is skipped). Source: main after this notes update. Signature: Apple Development, actual Team D765989V7S, certificate SHA1 3A92F137F2E694DFB6F4AC3E6F9A901EC6B1B7AA. Keep the existing Sparkle/Windows update keys unchanged.

- [ ] Dispatch custom-release.yml on main for build116/tagv0.3.5-custom.2, arm_cross_compile=true to avoid the known hosted ARM allocation problem. Native local ARM packaging performs its own runtime checks; CI truthfully records cross-compilation checks not run.
- [ ] Prepare isolated pinned Node24.14.1/npm11.11.0/cargo-about0.9.2 tools on NekoSSD, then run local public-version Apple Development arm64 packaging for build116. Local artifacts remain local and are never uploaded to Release.
- [ ] Follow both builds, fix actual failures from source evidence, and ensure any source fix is used consistently by both candidates.
- [ ] Verify the GitHub-published Release assets, source/identity/build metadata, signed update feeds and public readback.
- [ ] After packages are ready, normally stop the installed Oink; back up app and config data, preserving xattrs and permissions. Never traverse/materialize/delete the CloudStorage domain. Preserve the old 893V37X2CW App Group and copy its data into D765989V7S namespace if needed without removing the old copy.
- [ ] Replace /Applications/Oink.app using only the local package, preserve all pairing/settings, verify exact signer/build and running process, then check the published update source. Same-build local/GitHub packages do not replace one another; future higher GitHub build numbers are eligible for the normal update flow.

Workspace/logs/output: /Volumes/NekoSSD/codex/2026-11-11/oink-signed-release . Main checkout: /Volumes/NekoSSD/Github/oink . Retained protected task checkout is detached and must not be removed forcibly.
