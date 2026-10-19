# Release notes

## Current state — development pre-release

**No production release is available yet.** The current repository represents an implementation and validation stage, not a certified attendance product. The Flutter package version is development metadata; it is not a release tag.

### Scope represented in this codebase
- Flutter Android kiosk with multi-frame camera capture.
- Device-authenticated 1:N identification and employee-scoped 1:1 verification APIs.
- Separately authenticated admin enrollment.
- FastAPI vision service and database-backed attendance/audit records.
- SCRFD/ArcFace primary path, optional specialist model adapters, artifact contracts and readiness checks.
- CI workflows for code quality, tests and Android debug APK compilation.

### What is not included / not yet certified
- Compatible production model weights or a grant of rights to use them for attendance.
- Validated thresholds, false-accept/false-reject estimates, population-specific evaluations, or attack-specific liveness results.
- A signed Android release APK, deployment credentials, production secrets or a production database.
- A completed site-specific end-to-end test report.

### Before a release can be labelled production-ready
Complete every item in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), require passing CI on the release candidate commit, publish a reproducible build and SBOM, verify licenses and privacy obligations, and review operational rollback/backup procedures.

### Versioning
Use semantic versioning for future tagged releases. Pre-release identifiers should be used until the release gates are completed (for example, `0.2.0-rc.1`). Do not create a production tag merely because CI turns green.
