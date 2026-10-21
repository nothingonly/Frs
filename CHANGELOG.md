# Changelog

All notable project changes will be recorded here. This file follows an Unreleased-first format; entries are implementation notes, not evidence of a production release.

## [0.2.0-beta.1] - 2026-10-21

### Added
- Hardware-backed Android Keystore / SQLCipher encrypted offline burst buffer (`lib/services/offline_queue_service.dart`) with 24-hour fail-closed retention and reconnection auto-drain.
- Route-wide RBAC and scoping matrix (`backend/app/api/routes/admin.py`) restricting Deans to department and Faculty to class cohorts.
- Atomic database migrator (`backend/app/db/migrator.py`) with single-transaction execution and automatic rollback on error.
- Presentation Attack Detection (PAD) liveness calibration aligned to ISO/IEC 30107-3 reporting APCER, BPCER, and ACER.
- Automated attendance follow-up daemon (`backend/app/services/followup_worker.py`) reconciling closed sessions and dispatching absentee SMS/Email notifications.
- Android kiosk Lock Task service integration and ADB hardware readiness probe (`scripts/verify_kiosk_hardware_readiness.ps1`).
- Prometheus `/metrics` endpoint with request latency histograms and Grafana operational dashboard.
- Comprehensive production readiness checklist and sign-off framework across Gates 0 through 5 (`docs/CAMPUS_ACCEPTANCE_CHECKLIST.md`).

### Validated in CI & Locally
- 161 backend tests passed with Ruff linting clean.
- 40 Flutter tests passed with static analysis clean.
- Next.js 16 admin console TypeScript and ESLint clean, 11 static routes generated.

## [0.1.0-alpha.1] - 2026-10-19

### Added
- Published [FRS v0.1.0 Alpha 1](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/releases/tag/v0.1.0-alpha.1) with an Android debug APK for technical evaluation.
- Automated prerelease workflow that runs backend and Flutter quality gates before attaching the APK.

### Validated in CI
- Backend Python compilation and Ruff lint checks passed.
- Backend unit tests passed.
- Flutter dependency resolution, static analysis and Flutter tests passed.
- Android debug APK build and artifact upload passed.

### Limitations
- This is a debug prerelease, not a production-signed build.
- Real model weights are not bundled; biometric calibration and liveness/presentation-attack validation are not certified.
- Do not use this prerelease for live employment, payroll, access-control or attendance decisions.
