# FRS sprint status

Last updated: 2026-10-20

## Sprint 1 — Next.js admin foundation

### Delivered in this sprint

- Added a root pnpm workspace while preserving the existing Flutter and Python projects.
- Added a Next.js App Router application under admin-web/; the repository root command is pnpm dev.
- Added responsive admin navigation and an in-memory admin API connection panel.
- Connected the UI to existing FastAPI endpoints for health, people, attendance and model registry.
- Added people search and audited deactivate/reactivate actions through the existing backend.
- Added attendance-event and model-registry inspection screens.
- Added a frontend type-check/lint/build GitHub Actions workflow.
- Added documentation that distinguishes live backend records from future college-specific functionality.

### Intentionally not claimed as complete

- GitHub Actions passed install, TypeScript type-check, ESLint and Next.js production build on the latest Sprint 1 branch commit. Live backend integration has not been verified against a running instance.
- No pnpm lockfile is committed yet. The workflow currently permits lockfile generation during install; commit a reviewed lockfile before relying on reproducible dependency installation.
- No Supabase schema, migrations, Auth/RLS policies or live Supabase integration yet.
- No Cloudinary upload integration or private asset retention workflow yet.
- No college department/year/section/class/student schema yet.
- No persistent attendance-job queue/worker lifecycle yet.
- The admin console still uses the existing backend's shared bearer-key model. The key is kept in browser memory for this development console, but institutional login, role-based access and a security review are required before public deployment.
- Actual model weights, licenses, calibration and real-image recognition validation remain blockers for a biometric demo.

## Next sprint candidate

Design and implement the college domain model (departments, academic years, class groups/sections, students, enrollments and attendance sessions) with explicit migration and authorization design. Make Supabase a replaceable PostgreSQL provider rather than coupling the domain logic to Supabase-specific APIs.
