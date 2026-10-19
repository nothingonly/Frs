# Changelog

All notable project changes will be recorded here. This file follows an Unreleased-first format; entries are implementation notes, not evidence of a production release.

## [Unreleased]

### Added
- Multi-frame Android camera capture and multipart transport for verification, identification and admin enrollment.
- Separate kiosk-device and administrator bearer credentials, with encrypted secure storage on Android.
- Python backend for real SCRFD/ArcFace inference, policy-driven recognition, roster-scoped retrieval, enrollment, attendance state transitions, audit events and model registry.
- Explicit model provenance, SHA-256 and ONNX input/output contract validation.
- Runtime registry state now deactivates superseded versions for model roles that have been reloaded.
- Refreshed and committed the resolved Flutter dependency lockfile; dependency changes trigger lockfile synchronization.
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
