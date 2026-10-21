# Changelog

All notable project changes will be recorded here. This file follows an Unreleased-first format; entries are implementation notes, not evidence of a production release.

## [0.2.0-beta.2] - 2026-10-21

### Security & Hardening Remediation (Audit Follow-up: C-01, C-02, C-05, C-16, C-17, CI-01)
- **Offline Queue Cryptographic Framing & Tamper Detection (C-05)**: Replaced insecure repeating-XOR transformation in `lib/services/offline_queue_service.dart` with structured length-prefixed binary framing (`0x46, 0x52`), 16-byte random nonce, and 32-byte SHA-256 cryptographic digest over `[nonce + payload]`. Stored in Android Keystore `EncryptedSharedPreferences` (AES-256-GCM). Payloads with altered or corrupted bits fail closed to `OfflineSyncStatus.failed`. Added direct `crypto: ^3.0.3` dependency and tamper-detection unit test (41/41 Flutter tests passing).
- **Production Migration Fail-Closed & Integrity Checks (C-01 & C-02)**: Modified `backend/app/database.py` so `create_schema()` only suppresses schema creation errors for SQLite in non-production environments; production and PostgreSQL migration failures now raise immediately and block startup. Added `MigrationIntegrityError` in `backend/app/db/migrator.py` to abort startup in production if any previously applied migration file has been altered. Added `assert_production_schema_ready(engine)` startup checks in both capture and follow-up worker daemons.
- **SFTP Missing Dependency Fail-Closed (C-16)**: In `backend/app/services/integrations.py`, `SftpExportService.dispatch_sftp_export` now raises `RuntimeError` in production when `paramiko` is uninstalled instead of returning `STAGED_MOCK`.
- **LTI Trust Root Protection (C-17)**: In `backend/app/api/routes/integrations.py`, `/api/v1/integrations/lti/launch/validate` strictly rejects request-supplied `signing_key_or_secret` with HTTP 422 in production, binding verification exclusively to server-configured trust anchors and setting parameters.
- **Strict Blocking Dependency Audit (CI-01)**: Restored a blocking `pip-audit --desc` security gate in `.github/workflows/backend.yml`, removing the non-blocking warning fallback and passing explicit `--ignore-vuln` arguments for the 17 reviewed upstream advisories (`PYSEC-2026-1845`, cryptography x509, pillow decompression bomb).

### Validated in CI & Locally
- 169 backend unit and integration tests passed; Ruff linter clean.
- 41 Flutter tests passed (including queue tampering detection); static analysis clean.
- Next.js 16 admin console TypeScript and ESLint clean, 11 static routes generated.

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

### Security & Forensic Audit Remediation (FRS-01 to FRS-10)
- **CI Dependency Lock (FRS-01)**: Resolved editable requirement conflict in `backend/requirements.lock` allowing pip `--require-hashes` to install dependencies in backend CI without failure.
- **Truthful De-Enrollment Verification (FRS-02 & FRS-08)**: Updated `de_enroll_student_biometrics` to verify object-level cloud deletion outcomes (`CONFIRMED_DELETED`, `FAILED_OR_NOT_FOUND`, `STORAGE_NOT_CONFIGURED`) and issue qualified certificates (`FULL_DELETION_VERIFIED` vs `DELETION_INCOMPLETE`). Enforced server-configured retention purge policy in production.
- **LTI 1.3 Cryptographic Token Verification (FRS-03)**: Implemented `validate_launch_id_token` in `LtiService` to cryptographically verify OIDC/JWT ID tokens (signature, issuer, audience, expiration, nonce, deployment ID) and reject plain claim dictionaries in production.
- **SFTP Host Key Pinning (FRS-04)**: Added remote host key fingerprint verification in `SftpExportService.dispatch_sftp_export`, failing closed before data transmission if fingerprints mismatch or keys are unpinned in production.
- **Admin Web CSP Hardening (FRS-05)**: Removed `'unsafe-eval'` from Content Security Policy `script-src` in `admin-web/next.config.ts`.
- **Notification Mock Protection & Delivery Integrity (FRS-06 & FRS-07)**: Disallowed mock fallback in production for SMTP and SMS providers, reporting granular delivery counts (`sent_count`, `mocked_count`, `failed_count`), and preventing premature reconciliation on delivery failures.
- **Release Workflow Isolation (FRS-09)**: Parameterized release versions, dynamically scoped release actions to `${{ github.repository }}`, and removed cross-repository metadata modifications.
- **Pre-Release Gating (FRS-10)**: Re-enforced strict gating on real biometric calibration and model licensing before live deployment.

### Validated in CI & Locally
- 169 backend tests passed with Ruff linting clean.
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
