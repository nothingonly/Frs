# Changelog

All notable project changes will be recorded here. This file follows an Unreleased-first format; entries are implementation notes, not evidence of a production release.

## [Unreleased]

### Added
- Multi-frame Android camera capture and multipart transport for verification, identification and admin enrollment.
- Separate kiosk-device and administrator bearer credentials, with encrypted secure storage on Android.
- Python backend for real SCRFD/ArcFace inference, policy-driven recognition, roster-scoped retrieval, enrollment, attendance state transitions, audit events and model registry.
- Explicit model provenance, SHA-256 and ONNX input/output contract validation.
- Runtime registry state now deactivates superseded versions for model roles that have been reloaded.
- Refreshed and committed the resolved Flutter dependency lockfile. Dependency changes should be resolved with `flutter pub get` and the updated lockfile committed with the code change.
- Browser-based administration views for roster, attendance, audit and model status.
- CI workflows for Python and Flutter quality gates.
- Documentation for backend setup, security, contributions and release readiness.

### Changed
- Clarified that the project is pre-release and must not be used for live attendance until every release gate is passed.
- Updated the main README to distinguish software tests from real-data biometric validation.

### Fixed
- Camera capture cleanup now uses the supported filesystem API rather than a nonexistent `XFile.delete()` method.
- Removed an incompatible hand-written test runner; Flutter's native test discovery runs the independent test files.
- Corrected Python lint findings and clarified the lint policy.

### Known limitations / release blockers
- The repository does not contain model weights. Exact artifacts, licenses, hashes, preprocessing contracts and permitted-use terms must be supplied.
- Recognition thresholds and liveness performance have not been certified on deployment-specific data.
- Real camera/device and end-to-end acceptance testing remains required.
- Verify existing database upgrades and backup/restore procedures before any persistent deployment.
- No signed production APK, production tag or production approval is claimed by this changelog.

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
