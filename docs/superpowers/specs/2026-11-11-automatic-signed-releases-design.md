# Automatic signed main releases

The user requests that pushes to `main` automatically build and publish GitHub Release packages with the existing macOS Apple Development identity. Build numbers and `v<product-version>-custom.N` tags advance automatically. Local packages must never enter the publication path.

Keep the existing three-platform custom-release workflow, package validation, GitHub artifact transfer, release environment, and update signing keys. Add a preparation job that reserves an annotated release tag containing its numeric build, source commit/hash, and workflow run identity. Allocate above both published custom builds and earlier reservations; failed builds may leave gaps, and retries of the same run reuse their reservation. Serialize release runs, and skip a superseded source before publishing so a delayed build cannot become the latest release. A manual run remains available without requiring number/tag inputs.

The annotation records allocations without modifying main or introducing a version-bump commit loop. Using only published releases would recycle failed allocations; using workflow run numbers would couple product ordering to an arbitrary workflow counter. The existing annotated Git tag API and current workflow token provide the needed persistent reservation without another state branch.

macOS keeps Team `D765989V7S`, certificate `3A92F137F2E694DFB6F4AC3E6F9A901EC6B1B7AA`, and the existing Sparkle key. Automatic ARM builds use the previously successful Intel cross-compilation route; metadata continues to disclose that native ARM runtime checks are not run in CI. Only this run's three GitHub package artifacts are assembled and uploaded. Local packaging receives no uploader or automatic trigger.

Verify number/tag advancement, failed reservations, retry identity, version changes, malformed records, event/repository/ref restrictions, stale source rejection, and existing-release recovery with focused Python tests. Validate workflow syntax and the existing packaging suite. Review the whole patch, merge into main, and verify the first push-triggered workflow through public Release and signed feed readback.
