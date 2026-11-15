# GitHub contents and release checklist

English | [简体中文](RELEASING.zh-CN.md)

## Essential repository components

| Component | Location |
| --- | --- |
| Download engine, UI, worker, platform handling | `audioraven/`, `main.py` |
| Pinned runtime and build dependencies | `requirements.txt`, `requirements-dev.txt` |
| Native reproducible build entry | `build_app.py`, `assets/`, `scripts/` |
| User guide and compatibility limits | `README.md`, `docs/` |
| Original-code license and dependency notices | `LICENSE`, `THIRD_PARTY_NOTICES.md`, `licenses/` |
| Regression tests and native build validation | `tests/`, `.github/workflows/` |
| Contributor and issue guidance | `CONTRIBUTING.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/` |
| Version history | `CHANGELOG.md` |
| Privacy exclusions | `.gitignore` |

GitHub does not require every item above to create a repository; this set makes
the app usable and maintainable. Do not commit existing `dist/`, backups, a local
spec, cookies, or logs. Native ZIPs and checksums are release assets, not Git blobs.

## Publish a version

1. Update `audioraven.__version__`, the README download names, and the changelog.
2. Run tests, build and smoke checks on each target. Check the full extracted
   distribution; a successful source test alone is insufficient.
3. Run the privacy audit on staged source and extracted releases. Inspect commit
   author/committer names and addresses. Use no personal email or host username.
4. Collect dependency notices for the actual build. Preserve corresponding-source
   access for bundled LGPL/GPL components, including FFmpeg's enabled libraries
   and build scripts; retain matching sources alongside the release as required.
5. Push an annotated tag matching the version, such as `v0.3.0`. CI refuses a
   mismatching tag, builds all three packages, and creates a **draft** release
   only after all native jobs pass. Each ZIP has a SHA-256 checksum.
6. Review the draft's checks, source availability, and desktop acceptance status;
   publish it when those are satisfactory. Record unperformed manual Windows 11
   checks rather than implying they passed.

Workflow dispatch builds packages without creating a public release. Pull
requests run the same native tests/build checks with read-only repository access.
No personal account cookies are needed in CI. The release job alone receives
write permission, and only on version tags. Official actions are pinned to
commit hashes; Dependabot proposes updates.
