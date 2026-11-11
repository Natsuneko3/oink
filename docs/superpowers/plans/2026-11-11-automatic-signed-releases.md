# Automatic Signed Releases Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation and one independent whole-branch review.

**Goal:** Main pushes automatically publish only GitHub-built packages with the current signer and advancing build/tag identifiers.

**Architecture:** A serialized preparation job reserves an annotated version tag and publishes validated outputs to existing package/publish/feed jobs. Trusted main push and manual events are accepted; package and feed provenance checks remain enforced.

**Tech Stack:** GitHub Actions, Python standard library/unittest, gh REST API.

**Spec:** `docs/superpowers/specs/2026-11-11-automatic-signed-releases-design.md`

## Global Constraints

- Existing macOS Team/certificate and Sparkle/Windows update keys remain unchanged.
- Local packages are never uploaded; the publish job assembles only this run's GitHub artifacts.
- Build numbers remain positive 31-bit integers and advance above published/reserved builds; tag suffixes advance for the current product version.
- Reruns reuse their original allocation. Failed runs may consume numbers. Never overwrite a conflicting tag or Release.
- Main is never modified by version allocation. Superseded commits cannot replace the latest Release.

## Review Focus

- Two queued runs and failed reservations cannot receive the same number/tag.
- A retry with a different source cannot reuse a run's reservation.
- Fork/PR/tag events cannot gain access to signing or publication.
- An already public Release must be checked rather than overwritten on retry.
- Repeated feed publication cannot regress builds or duplicate a committed publication.

### Task 1: Reserve release identities

**Files:** Create `build-support/custom_release_versions.py`; create `packaging/tests/test_custom_release_versions.py`.

**Interfaces:** `reserve(commit, source, version, run_id, request)` returns a validated reservation dict containing `build` and `tag`; the CLI writes validated job outputs.

- [ ] Write failing tests for next build117/tagcustom.3 from published116/custom.2, failed reservations, run retry/source mismatch, new version, bounds, and rejected event contexts.
- [ ] Run the focused test file and confirm the missing behavior fails.
- [ ] Implement allocation from public releases and annotated tag reservations; create a tag reference without force updates.
- [ ] Run focused tests and commit the completed allocator.

### Task 2: Wire automatic publication and recovery

**Files:** Modify `.github/workflows/custom-release.yml`, `build-support/custom_release.py`, `build-support/update/custom_feed.py`; add focused publication tests.

**Interfaces:** Workflow preparation outputs supply `build`/`release_tag` to all downstream jobs. `publish` reports whether a current Release exists/was created, gating the feed job.

- [ ] Write failing tests for trusted push publication, source/tag mismatches, existing Release retries, superseded source, and committed-feed retry.
- [ ] Enable main pushes and keep manual dispatch with automatic identifiers; wire preparation outputs and the current signer.
- [ ] Extend trusted event checks, verify reserved tags and current main, and make completed publication safe to retry.
- [ ] Run focused tests, the existing packaging suite, and workflow validation; commit the complete change.

### Task 3: Review and verify the deployed workflow

**Files:** This plan/spec and external evidence under `/Volumes/NekoSSD/codex/2026-11-11/oink-auto-release`.

- [ ] Independently review the immutable patch and fix material findings with tests.
- [ ] Merge/push main as authorized, observing the push-triggered build without a manual dispatch.
- [ ] Verify automatic identifiers, signer, GitHub artifact provenance, Release assets, and signed public feeds; record results.
