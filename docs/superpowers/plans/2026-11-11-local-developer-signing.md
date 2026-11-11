# Local developer signing implementation plan

> **For agentic workers:** Execute inline with superpowers:executing-plans. User explicitly selected signing both local and GitHub packages with the existing local Apple Development identity.

**Goal:** Local and GitHub macOS packages use Apple Development team 9559Z74J33 and certificate 3A92F137F2E694DFB6F4AC3E6F9A901EC6B1B7AA.

**Architecture:** Add an explicit apple-development mode alongside ad-hoc and developer-id. Configure the fork's real team consistently across package and runtime checks. GitHub imports only the selected password-protected identity from environment secrets, verifies the pinned fingerprint, and removes the temporary keychain afterward.

**Constraints:** No local product build, packaging, or test execution. Preserve the original shared checkout and installed app/configuration. Preserve update keys. Development signing never claims notarization or Developer ID. Preserve upstream trust only for explicit legacy microphone migration. New team App Group has its own namespace; do not delete or move existing data.

## Review focus
- Wrong team, wrong certificate type, and mismatching fingerprints must fail closed.
- Existing ad-hoc and formal verification paths remain explicit and distinct.
- Custom Release and feed metadata accurately identify development certificates.
- CI exports no certificate/private key material in logs and always cleans its temporary keychain.
- Runtime identity checks and App Group declarations use the fork team consistently.

### Task 1: Signing policy and package integration
- [ ] Add behavior tests for Apple Development identity selection, signature verification, explicit mode resolution, and rejection of formal credentials in development mode.
- [ ] Observe new tests fail on GitHub, then implement policy and forwarding in signing.py, package.py, macOS build/content helpers, custom release/feed validators.
- [ ] Migrate current-team pins while preserving the explicit upstream legacy driver exception.

### Task 2: GitHub certificate setup and proof
- [ ] Extend ci-keychain.py to support development credentials without requiring notary credentials.
- [ ] Configure custom-release.yml to import, use, and clean the same pinned identity; retain the historical recovery workflow for old source commits.
- [ ] Export only the uniquely identified local signing identity into password-protected PKCS#12; transmit through stdin to release environment secrets, without logging private bytes.
- [ ] Verify GitHub Python checks and real code signing against team and certificate fingerprint using a temporary executable, with no product build/publication.

### Task 3: Finish and synchronize
- [ ] Review the complete patch, document developer-certificate distribution limits, and confirm remote configuration.
- [ ] Synchronize only signing-owned changes into the original checkout; keep unrelated work and staging unchanged.
- [ ] Report exactly which configuration and checks completed; existing installed/released bundles remain unchanged until rebuilt.
