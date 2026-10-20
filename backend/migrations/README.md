# PostgreSQL / Supabase migrations

Run these scripts in order against a fresh PostgreSQL database, including a fresh Supabase project. Apply them as a trusted database administrator, not from the browser or Android app.

1. `0001_base_schema.sql` creates the existing FRS biometric base tables: people, encrypted embeddings, attendance events, audit events and model registry.
2. `0002_college_domain.sql` creates departments, class groups, students, class enrollments and attendance sessions, then adds the optional attendance-session link to legacy attendance events.
3. `0003_capture_batches.sql` creates the encrypted attendance capture queue and enables RLS without adding public policies.

These scripts are idempotent for the current schema shape and intentionally insert no sample records. For a database already created by an earlier FRS version, back up first and apply the scripts in a staging copy before production.

## Backend configuration

Set `FRS_DATABASE_URL` only in the FastAPI backend's private environment. SQLAlchemy in this project uses psycopg 3, so normalize the connection scheme to `postgresql+psycopg://` if your provider's URI starts with `postgresql://`. Use a secure, server-side PostgreSQL connection with the required table permissions. Do not place a database URI, database password or Supabase service-role key in any `NEXT_PUBLIC_*` variable, Next.js client component, or Flutter setting.

The Next.js console calls the FastAPI admin API; it does not connect to Supabase directly. The database connection can later point at AWS RDS PostgreSQL or another PostgreSQL service without changing the college domain API.

## Row-level security

RLS is enabled on the tables. These scripts intentionally create no policies for the Supabase `anon` or `authenticated` roles. End-user access must go through the protected FastAPI routes until the college's real user/role model and least-privilege policies have been designed and tested. The backend connection itself must be treated as privileged and must never be shipped to a client.

RLS on its own is not a complete authorization design. Review grants, database roles, backups, transport encryption, key rotation and application authorization for the target project.

## College model

- `departments`: canonical department code and display name.
- `class_groups`: department, year of study 1–4, section and academic year (e.g. 2026-2027).
- `students`: student number/profile, linked to the current biometric `persons` record by nullable unique `person_id`.
- `class_enrollments`: active/withdrawn history between a student and a class group.
- `attendance_sessions`: a class-specific subject attendance event with open/closed state and optional idempotency key.
- `attendance_events.attendance_session_id`: optional reference for new class-scoped attendance; old events remain unassigned.

Creating a student through `POST /api/v1/admin/college/students` creates or links a `persons` identity record but does not make an embedding. Existing biometric enrollment remains a separate operation. The session-aware kiosk queue invokes the configured recognition pipeline with the selected session and class group. The gallery is filtered to active students with active enrollments in that class, and accepted attendance events retain the session ID. Legacy identify/verify endpoints remain for existing non-session clients; new college kiosk deployments should use the session batch endpoint.

## API endpoints

All routes below require the configured administrator bearer credential.

- `GET/POST /api/v1/admin/college/departments`
- `GET/POST /api/v1/admin/college/class-groups`
- `GET/POST /api/v1/admin/college/students`
- `POST/DELETE /api/v1/admin/college/class-groups/{class_group_id}/students/{student_id}`
- `GET/POST /api/v1/admin/college/attendance-sessions`
- `POST /api/v1/admin/college/attendance-sessions/{session_id}/close`

Administrative creates, enrollment changes, withdrawals and session transitions write audit events. Withdrawals are soft status changes rather than destructive deletes.


## Capture-to-attendance flow (Sprint 3)

Authenticated kiosk clients call GET /api/v1/attendance/sessions/open, submit a burst to POST /api/v1/attendance/sessions/{session_id}/batches with a 12–120 character idempotency key, then poll GET /api/v1/attendance/batches/{batch_id}. The server stores only an AES-GCM-encrypted packed frame burst while work is pending; FRS_DATA_ENCRYPTION_KEY must be present on every API worker instance. The worker calls the same real AttendancePipeline used by direct attendance APIs; it does not generate model scores or synthesize accepted responses.

A successful recognition and the capture-job transition to SUCCEEDED are committed in the same SQL transaction. This prevents two competing workers from creating two accepted events for one batch. Accepted/rejected payload bytes are cleared. Retries of transient server failures are limited to three attempts and payload retention is capped at 24 hours. Failed jobs can be inspected/retried by administrators while their payload is still retained and the source session remains open.

The included worker polls from the FastAPI application process. For production GPU/scale deployments, separate the worker into a supervised worker service and validate lease, shutdown, concurrency, and metrics on the selected PostgreSQL deployment. The current code does not imply a Cloudinary integration or live database deployment.
