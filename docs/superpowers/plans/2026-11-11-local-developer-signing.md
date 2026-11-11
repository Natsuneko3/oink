# Local developer signing implementation plan

> **For agentic workers:** Execute inline with superpowers:executing-plans. User explicitly selected signing both local and GitHub packages with the existing local Apple Development identity.

**Goal:** Local and GitHub macOS packages use Apple Development team D765989V7S and certificate 3A92F137F2E694DFB6F4AC3E6F9A901EC6B1B7AA.

**Architecture:** Add an explicit apple-development mode alongside ad-hoc and developer-id. Configure the fork's real team consistently across package and runtime checks. GitHub imports only the selected password-protected identity from environment secrets, verifies the pinned fingerprint, and removes the temporary keychain afterward.

**Constraints:** No local product build, packaging, or test execution. Preserve the original shared checkout and installed app/configuration. Preserve update keys. Development signing never claims notarization or Developer ID. Preserve upstream trust only for explicit legacy microphone migration. New team App Group has its own namespace; do not delete or move existing data.

## Review focus
- Wrong team, wrong certificate type, and mismatching fingerprints must fail closed.
- Existing ad-hoc and formal verification paths remain explicit and distinct.
- Custom Release and feed metadata accurately identify development certificates.
- CI exports no certificate/private key material in logs and always cleans its temporary keychain.
- Runtime identity checks and App Group declarations use the fork team consistently.

### Task 1: Signing policy and package integration
- [x] Add behavior tests for Apple Development identity selection, signature verification, explicit mode resolution, and rejection of formal credentials in development mode.
- [x] Observe new tests fail on GitHub, then implement policy and forwarding in signing.py, package.py, macOS build/content helpers, custom release/feed validators.
- [x] Migrate current-team pins while preserving the explicit upstream legacy driver exception.

### Task 2: GitHub certificate setup and proof
- [x] Extend ci-keychain.py to support development credentials without requiring notary credentials.
- [x] Configure custom-release.yml to import, use, and clean the same pinned identity; retain the historical recovery workflow for old source commits.
- [x] Export only the uniquely identified local signing identity into password-protected PKCS#12; transmit through stdin to release environment secrets, without logging private bytes.
- [x] Verify GitHub Python checks and real code signing against team and certificate fingerprint using a temporary executable, with no product build/publication.

### Task 3: Finish and synchronize
- [x] Review the complete patch, document developer-certificate distribution limits, and confirm remote configuration.
- [x] Synchronize only signing-owned changes into the original checkout; keep unrelated work and staging unchanged.
- [x] Report exactly which configuration and checks completed; existing installed/released bundles remain unchanged until rebuilt.

## Verification evidence and rulings

- Original implementation base: d7d8c1a66b66826bcb8daf18c8f77fff4bdd0125. Shared checkout and staging remain untouched until the final guarded synchronization.
- Initial GitHub run 43027057924 demonstrated the new signing behavior was absent.
- Run 43028813152 passed the full Python packaging suite and imported the exact selected development identity; its real-signature probe stopped before signing because copying protected system file flags with shutil.copy2 is prohibited. The probe now copies data and sets executable mode without protected flags.
- The only full-suite failure encountered earlier was a new dynamic lookup under a deliberately substituted feed-state test directory. Reading the team from the existing shared product-identity module resolves that ownership error without weakening validation.
- Independent review found and verified the fix for existing upstream-signed Oink microphone migration. Both known teams are accepted only for existing Oink destinations; new payloads require this fork team.
- Certificate export uses SecItemExport on the single identity matching the configured SHA1. Aggregate export was refused when other identities were detected. The encrypted PKCS#12 and password reached GitHub secrets only through stdin; private bytes were never saved to the repository or logs.
- Full Oink compilation, File Provider/container runtime checks, product update qualification, and local installation are outside this configuration task and have not been performed.

- Corrected an identity interpretation error exposed by the real GitHub signature probe: the certificate CN suffix 9559Z74J33 is an account label; its actual signing Team ID is D765989V7S from the fingerprint-matched certificate subject OU. Apple Development selection now reads that authenticated public certificate field rather than interpreting the display name as a team. A synthetic public certificate regression fixture deliberately uses different CN suffix and OU values. The production certificate fingerprint and private key are unchanged.

- Run 43030844417 passed the full packaging suite, imported the pinned identity, and verified the actual Apple Development authority/team. It exposed an optional-argument CLI error in certificate extraction: codesign requires --extract-certificates=<prefix>, not a separate prefix argument. Read-only extraction of an existing system signature confirmed exit 1 versus exit 0 for those forms. Both the shared verifier and probe now use the corrected production verifier; a regression checks accepting only the exact embedded leaf certificate. The probe compiles its own trivial executable remotely rather than copying a protected system program.

- Final code verification succeeded on GitHub run 43031748480, commit 6f5815c5032e2dfb4aa8b59c96ad3f27b223d42f. Full packaging checks, development identity import, strict code signature/actual Team ID/leaf fingerprint verification, executable launch with the host App Group/audio entitlements, and ephemeral-keychain cleanup all passed. URL: https://github.com/Natsuneko3/oink/actions/runs/43031748480 . No full product package or installed app was changed.
- User explicitly requested main integration and deletion of both codex/local-developer-signing and origin/codex/local-developer-signing. Preserve all commits in main before deleting either branch.

## Completed integration and cleanup

- The user-requested signing changes and verification record were fast-forwarded into the original main checkout and pushed to origin/main as 3e3f3e63916ca2b472420b5c24412d1ac842a2ce. The existing game/input commits remain ancestors.
- Both codex/local-developer-signing and origin/codex/local-developer-signing were deleted only after confirming their commits are reachable from main. Remote deletion used an exact expected-ref lease. No source commits were discarded.
- The app refused to archive the task's protected primary checkout, and the original project directory is not a managed worktree that can be attached. The task worktree is therefore retained detached at main; the original project checkout /Volumes/NekoSSD/Github/oink remains on main. No filesystem removal was forced.
- GitHub verification run 43031748480 passed 7 focused signing tests, the full packaging suite (256 tests, 3 platform skips), actual signing/Team ID/leaf fingerprint checks and executable launch, and keychain cleanup. The actual signing Team ID is D765989V7S; certificate SHA1 is 3A92F137F2E694DFB6F4AC3E6F9A901EC6B1B7AA.
