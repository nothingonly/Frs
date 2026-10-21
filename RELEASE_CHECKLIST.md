# Production release checklist

A release must not be marked production-ready until each required gate has evidence linked to the exact commit and deployed artifact.

## Software quality
- [ ] Python compile, lint and unit-test CI is green on the release commit.
- [ ] Flutter analysis, tests and Android release build are green on the release commit.
- [ ] API contract tests cover success, unknown, ambiguity, recapture/quality failure, authentication failure, upload boundaries and invalid attendance transitions.
- [ ] Dependency vulnerability review, license inventory and build reproducibility/SBOM are complete.
- [ ] Existing-database migration, backup and restore have been tested against a representative copy.

## Biometric validation
- [ ] Every exact model artifact has a recorded source, full SHA-256, license, permitted use, version and preprocessing contract.
- [ ] Rights for the intended attendance/employment context have been reviewed.
- [ ] Enrollment, known-probe and unknown-probe sets are separated and documented; no test image leaks into enrollment.
- [ ] Per-model thresholds and ambiguity margins are calibrated on representative local data.
- [ ] False-accept, false-reject, recapture and failure-to-enroll rates are reported, including subgroup analysis where lawful and appropriate.
- [ ] Liveness is tested against relevant presentation attacks, including print and screen replay; operating thresholds and failure cases are recorded.
- [ ] Camera, lighting, pose, mask/occlusion, eyewear and movement conditions are tested on the target hardware.
- [ ] An independent operator verifies that unknown, uncertain or policy-invalid cases never create attendance.

## Security and privacy
- [ ] Production device/admin credentials are distinct, rotated and never stored in source control.
- [ ] Encryption keys, TLS, reverse-proxy limits, allowed origins, CORS and network exposure are reviewed.
- [ ] Admin routes and audit access are authenticated and least-privileged.
- [ ] Data purpose, legal basis, notice/consent, retention, access/export, deletion, incident response and backup controls are approved by the deploying organization.
- [ ] Logs, traces and support bundles contain no raw face images or full embeddings.
- [ ] Penetration and abuse testing cover replay, repeated requests, rate limiting, oversized multipart uploads and administrator access.

## Deployment and operations
- [ ] Database concurrency, attendance transition policy, time handling and idempotency behavior are verified.
- [ ] Health/readiness behavior reflects actual required-model readiness.
- [ ] Monitoring, on-call ownership, backup restore, migrations and rollback procedures are documented.
- [ ] The signed APK, server image digest, SBOM, release notes and validation report are tied to the same immutable release tag.
- [ ] Stakeholders explicitly approve the operating environment and remaining known risks.
