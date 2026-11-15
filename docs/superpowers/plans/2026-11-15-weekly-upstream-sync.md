# Weekly upstream synchronization implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge upstream main into this fork, preserving its input policies, signing and automatic releases.

**Architecture:** Merge the recorded upstream snapshot on a branch based on origin/main. Resolve integration differences semantically, validate locally and in three-platform PR CI, then merge and follow the automatic signed release and feed publication.

**Tech Stack:** Rust, React/TypeScript, Python packaging, GitHub Actions.

**Spec:** User-authorized weekly synchronization in this chat and the `oink` automation. Starting fork: `f0b6e64a5dd8f7f63411b0586abdb79abbd3effa`; upstream: `c15f2754f0469a25920eb389c97eacbe9b2c529a`.

## Global Constraints

- Preserve current fork behavior, signing identity, trusted keys, update channels, automatic version reservation, and release concurrency/freshness protections.
- Preserve user changes and published history; no forced updates or bypassing failing checks.
- User has authorized conflict fixes, commits, PRs, main integration and resulting releases without repeated confirmation.

## Review Focus

- Upstream update protocol changes must still receive updates signed by this fork.
- Source/build version floors must not collide with previous automatic release reservations.
- macOS signing and microphone migration must retain this fork's current identity.
- Game-mode local input and other input-routing customizations must survive upstream changes.
- Concurrent main changes or release writers must not publish stale or mixed artifacts.

### Task 1: Integrate upstream and preserve fork contracts

**Files:** Files changed by the merge, especially `build-support/update/`, `packaging/`, `.github/workflows/`, update UI/Rust, and fork input policy.

- [x] Establish a baseline with packaging tests; record any existing failure before fixing it.
- [x] Merge the pinned upstream snapshot, inspect every conflict and upstream/fork overlap, and resolve according to the constraints above.
- [x] Run the packaging suite, frontend checks/build, Rust formatting and affected Rust tests; reproduce each integration failure before fixing it.
- [x] Review the complete integration and commit the resolved merge.

### Task 2: Verify on all supported platforms and integrate main

**Files:** PR integration branch; CI only if a verified integration defect requires correction.

- [ ] Push the branch, create a PR against fork main, and follow all three platform CI jobs.
- [ ] Diagnose and fix failures, re-run required checks, and perform a fresh review.
- [ ] Recheck latest main and merge using ordinary non-forced Git updates after critical checks pass.

### Task 3: Verify automatic release and signed feeds

**Files:** Existing automatic release/feed pipelines and their public outputs.

- [ ] Follow final main SHA build/test and signed-release jobs through completion.
- [ ] Verify public release asset identities/hashes and signed feed readback for the exact source commit.
- [ ] Safely fast-forward the original clean main checkout and report evidence, including any external blocker.

Local validation: frontend 1,553 tests and production build; updater 71 tests (1 ignored); agent 1,224 tests (39 ignored), routing 464 tests (3 ignored); packaging 337 tests (4 skipped); build-support 14 tests (3 skipped, including 3 genuine-reference native signature tests passed); rustfmt, actionlint and attribution for 651 components passed. Independent review found a preexisting stale-source gap; added and verified fresh-main guards around Release/feed publication with rollback during upload.
