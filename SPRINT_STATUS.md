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
- Flutter analysis and tests passed; the Android debug build was still running at the latest check.
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
- GitHub Actions on the latest code revision: Python compile and Ruff passed; all 41 backend tests passed; Next.js dependency install, TypeScript, ESLint and production build passed. Flutter analysis and tests passed; the Android debug APK build was still running at the last check.
- Supabase credentials are not configured here, so no migration has been run against a live Supabase project.
- No production identity provider or institutional role model exists yet; do not expose the development bearer-key console publicly.
- Student enrollment images, Cloudinary integration, durable processing workers and class-scoped recognition are not yet implemented.
- The Next.js workspace still lacks a committed pnpm lockfile; dependency installation currently runs with lockfile generation enabled in CI. A reviewed lockfile is needed for reproducible installs.
- Attendance sessions are persisted, but the recognition endpoint/decision pipeline does not yet require a session or restrict identity matching to that class. Sprint 3 must connect these and verify class-scoped matching.
- Real, properly licensed model artifacts, threshold calibration, presentation-attack validation and real-device E2E tests remain release blockers.

## Next sprint candidate — Capture-to-attendance integration

Connect an attendance session to the Android batch, persist an upload/job record, scope the eligible identity set to the session's class, run the actual configured model pipeline, store session-linked attendance decisions and ensure jobs recover safely when the GPU worker disconnects. Implement Cloudinary upload/retention only after authorized private-access rules are agreed.
