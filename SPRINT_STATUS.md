# FRS sprint status

Last updated: 2026-10-20

## Sprint 1 — Next.js admin foundation

### Delivered
- Added the root pnpm workspace and Next.js App Router application under `admin-web/` with the requested `pnpm dev` command.
- Added responsive overview, people, attendance and model-registry screens connected to the existing FastAPI admin endpoints.
- Added people search and audited deactivate/reactivate actions.
- Added admin-web CI for TypeScript, lint and production build.
- Sprint 1 changes are in draft PR #2; they have not been merged into main.

### Validation
- Admin web: pnpm install, TypeScript type-check, ESLint and Next.js production build passed on GitHub Actions.
- Backend checks passed on the Sprint 1 pull request.
- Flutter analysis, tests and Android debug APK build have subsequently passed on the Sprint 3 branch.
- No live FastAPI/browser test was performed in the remote code-editing environment.

## Sprint 2 — College domain model and admin setup

### Delivered
- Added SQLAlchemy entities for departments, class groups, students, class enrollments and attendance sessions.
- Added the optional attendance-session foreign key on existing attendance events plus a compatibility upgrade for earlier FRS databases.
- Added protected admin endpoints for department and class-group creation/listing; student creation/listing; enroll/withdraw; attendance-session create/list/close.
- Student records are linked to the existing biometric Person record using student_number as the identity key. Creating a student does not create a face embedding.
- Added audit records for department/student/class-group creates, enrollment/withdrawal and attendance-session transitions.
- Added Supabase/PostgreSQL base and college migrations with RLS enabled and no public/anon policies.
- Added migration/setup documentation for keeping database credentials server-side and retaining PostgreSQL portability for a later AWS migration.
- Added a responsive Next.js College Setup page to manage departments, classes and student roster using the real protected API.
- Added API tests for validation, student/person linking, roster filtering, cohort-section exclusivity, withdrawal/re-enrollment and attendance-session idempotency/close behavior.
- Exposed optional session association in the attendance admin view.

### Validation and known limits
- Sprint 2's latest branch checks passed before Sprint 3 integration; Sprint 3's current checks cover the combined backend, Next.js, and Flutter state. PR #3 remains open/draft and has not been merged.
- Supabase credentials are not configured here, so no migration has been run against a live Supabase project.
- No production identity provider or institutional role model exists yet; do not expose the development bearer-key console publicly.
- Student enrollment images, Cloudinary integration, durable processing workers and class-scoped recognition are not yet implemented.
- The Next.js workspace still lacks a committed pnpm lockfile; dependency installation currently runs with lockfile generation enabled in CI. A reviewed lockfile is needed for reproducible installs.
- Attendance sessions are persisted, but the recognition endpoint/decision pipeline does not yet require a session or restrict identity matching to that class. Sprint 3 must connect these and verify class-scoped matching.
- Real, properly licensed model artifacts, threshold calibration, presentation-attack validation and real-device E2E tests remain release blockers.



## Sprint 3 — Session-scoped capture-to-attendance

### Delivered in this branch
- Added the durable PostgreSQL/SQLAlchemy capture-job table and migration 0003; input frame bursts are packed and AES-GCM encrypted while queued.
- Added device-authenticated endpoints to list OPEN sessions, enqueue a capture batch using an idempotency key, and check the status of a batch owned by the same kiosk credential.
- Added a FastAPI background worker that atomically claims queued jobs, carries claim-generation tokens through the pipeline, retries transient server failures, recovers stale PROCESSING leases and expires queued payloads after 24 hours.
- Connected the actual configured face recognition/liveness pipeline to session-aware processing. Eligible templates are limited to active students with an ACTIVE enrollment in the session's class group, including secondary-recognizer checks.
- Made the accepted attendance-event write and batch SUCCEEDED transition atomic. The attendance event contains the selected attendance-session ID; session-aware cooldown and check-in/check-out state rules are scoped to that session.
- Added admin-only queue inspection and retry endpoints; the Next.js console now has a Sessions & jobs page for creating/closing class sessions, reading job states and retrying eligible FAILED jobs.
- Updated the Android kiosk to select a persisted OPEN attendance session, enqueue its real captured frames, poll the server job, and resume the same idempotent request after network errors. Retake/session switching is blocked while local state is holding an uncertain pending batch.
- Added test coverage for encrypted queue payloads/idempotency/session closure, class-scoped template retrieval, and stale-worker attempts that must not overwrite newer claims.

### Validation and known limits
- Validation passed on code commit `478cd5dfe0916d294f2b0aaeac645e4fbc002d65`: backend compile and Ruff passed with 45 tests passed (1 dependency deprecation warning); Next.js install, TypeScript, ESLint and production build passed; Flutter analysis, Flutter tests, Android debug APK build and artifact upload passed. See [backend CI](https://github.com/nothingonly/Frs/actions/runs/39389732670), [admin web CI](https://github.com/nothingonly/Frs/actions/runs/39389732692), and [Flutter/APK CI](https://github.com/nothingonly/Frs/actions/runs/39389732655).
- The queue is stored in the PostgreSQL database and survives API process restarts; the worker currently runs inside the FastAPI process and is not a separate autoscaled GPU worker service.
- No Supabase database, Cloudinary account or target GPU worker is configured here. Migration 0003 has not been executed against a live provider.
- The kiosk queue path requires an actual open class session and active enrollment linked to real biometric templates; roster rows alone are not biometric enrollment.
- Legacy direct identify/verify routes remain for development compatibility but are rejected when `FRS_ENV=production`; production attendance must use the session-scoped batch path. Regression tests cover this policy.
- The branch does not add or fabricate model artifacts. Verified model licenses, real weights, calibration, attack evaluation and real Android/server end-to-end validation remain release blockers.
- The pnpm lockfile is still not committed, so web CI has lockfile generation enabled during dependency install.


## Next sprint candidate — Private enrollment/media and production worker separation
- Decide the institution's biometric notice, retention/deletion period, incident response, and non-biometric alternative before retaining face source images.
- Implement a private object-storage adapter (Cloudinary only if its private-access, signed URL, deletion, region, and retention semantics are approved) and an explicit enrollment image-to-real-template workflow.
- Move job execution out of FastAPI into a separately supervised worker deployment, with operational metrics, lease/queue monitoring, deployment-specific concurrency validation and restart testing.
- Reproducible workspace installs still need a reviewed/committed pnpm lockfile. Institutional authentication/roles, live provider migrations, lawful model/license attestation, calibration, liveness evaluation and real-device end-to-end trials remain release work.
