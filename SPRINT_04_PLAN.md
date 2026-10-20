# Sprint 4 — Verified vertical slice and release evidence

Status: planned / in progress
Base: Sprint 3 branch `sprint/03-capture-to-attendance`
Goal: prove the session-scoped attendance workflow end to end and make any unverified dependencies explicit. This sprint does not declare the system production-ready.

## Why this sprint changed

The original V4/V5 plan describes the target architecture and implementation contract. The Sprint 1–3 branches have added the admin console, college domain model, and persistent session-scoped capture queue. The next critical uncertainty is no longer another screen or queue feature: it is whether the integrated path works against a real database, real licensed model artifacts, and a real Android device.

Do not treat architecture documentation, mocked/unit tests, CI green status, or a debug APK as proof of biometric accuracy or production readiness.

## Scope

1. Preserve the existing fail-closed decision policy and session-scoped active-enrollment matching. Disable legacy unscoped `/identify` and `/verify` attendance routes in production so session/class scoping cannot be bypassed.
2. Add/strengthen deterministic automated regression coverage for the complete API contract: open session, authenticated batch enqueue, idempotent retry, status polling, closed-session rejection, unknown/ambiguous recognition, and no attendance event on non-accept decisions.
3. Add a repeatable test-environment runbook for applying migrations 0001–0003, creating a test department/class/student/session, provisioning authorized model artifacts, running the backend and worker, and collecting evidence.
4. Define a signed-off end-to-end evidence report format tied to commit, database migration version, model artifact hashes, preprocessing IDs, configuration, device/build, test-set split, metrics, latency, and failure cases.
5. Record blockers separately from passing software tests. Do not fabricate model assets, biometric scores, provider credentials, or test results.
6. Make reproducible web installs a release requirement; add a reviewed pnpm lockfile only when it can be generated and validated from the actual workspace/toolchain.

## Acceptance criteria

- [ ] Backend, admin web and Flutter checks pass on the integrated sprint head.
- [ ] Tests prove duplicate submissions cannot create duplicate attendance, and retries/restarts cannot let stale worker claims overwrite newer results.
- [ ] Tests prove matching is restricted to active students enrolled in the session's class group.
- [ ] Unknown, ambiguous, low-quality, liveness-unavailable (when policy requires liveness), closed-session, and invalid-transition cases fail closed and do not create attendance.
- [ ] Migration 0001–0003 upgrade and rollback/recovery behavior is exercised against a disposable PostgreSQL database; provider-specific Supabase behavior is separately recorded if Supabase is selected.
- [ ] A real Android device completes capture → enqueue → worker processing → persisted attendance decision → admin inspection using approved real model artifacts.
- [ ] The evidence report includes false-accept/false-reject and recapture/failure-to-enroll measurements on disjoint enrollment, known-probe and unknown-probe sets, plus latency and tested operating conditions.
- [ ] No release-readiness claim is made unless every required checklist gate has attached evidence tied to the exact commit and artifact.

## Out of scope until prerequisites are approved

- Selecting Cloudinary or another object store before institutional privacy, region, access, signed-URL, retention and deletion requirements are approved.
- Storing enrollment source images without a documented lawful basis, notice/consent process, retention/deletion policy and access controls.
- Claiming liveness or anti-spoof effectiveness without attack-specific evaluation.
- Moving inference to a separate GPU worker before deployment requirements, GPU availability, queue ownership, concurrency and operations are specified. Keep the current in-process worker documented as a limitation meanwhile.
- Merging the stacked Sprint 1–3 pull requests automatically. Integrate in dependency order after review and combined CI.

## External prerequisites / blockers

- Authorized, compatible model artifacts with full SHA-256, source, license and permitted-use attestation.
- Approved test data and institutional authorization to process biometric data.
- Disposable PostgreSQL/Supabase test environment and credentials configured outside source control.
- Target Android device, reachable test backend, TLS for non-loopback traffic, and separate device/admin credentials.
- Operator responsible for reviewing biometric results and approving retention/deletion behavior.

## Evidence to attach before calling the sprint complete

1. Exact integrated commit SHA and CI run links.
2. Migration logs and schema/constraint verification.
3. End-to-end test steps, device/build details and sanitized API/job/audit outcomes.
4. Model manifest, hashes, license/provenance review and preprocessing versions.
5. Dataset composition/split protocol and measured recognition/liveness metrics.
6. Known failures, residual risks, rollback instructions and explicit go/no-go decision.

## Immediate execution order

1. Review and integrate PR #2, then PR #3, then PR #4; do not merge around failed checks.
2. Run automated regression tests on the integrated head and fix failures before provider testing.
3. Apply migrations in a disposable PostgreSQL environment and exercise retry/restart/duplicate scenarios.
4. Run the authorized Android-to-admin vertical slice with real artifacts and record evidence.
5. Update the release checklist only with evidence that actually exists; keep all untested gates open.
