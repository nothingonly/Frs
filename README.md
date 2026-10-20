# FRS — Face Recognition Attendance System

> Android kiosk + FastAPI service for face-based attendance, designed around the FRS V4/V5 build plan.

[![Backend checks](https://github.com/nothingonly/Frs/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/nothingonly/Frs/actions/workflows/backend.yml)
[![Flutter quality gate](https://github.com/nothingonly/Frs/actions/workflows/flutter.yml/badge.svg?branch=main)](https://github.com/nothingonly/Frs/actions/workflows/flutter.yml)

## About

FRS combines a Flutter Android kiosk with a Python/FastAPI backend for multi-frame face verification and automatic identification. The system is built to make attendance decisions from captured evidence, a roster-scoped comparison, configured policy gates, and an auditable state transition—not from client-side identity claims.

**Project status: pre-release / not approved for live attendance.** The application code and automated checks are under active development. Real, appropriately licensed model weights, site-specific threshold calibration, presentation-attack testing, deployment hardening, and an end-to-end device test are still release gates. This repository deliberately does not ship unknown or unlicensed model weights.

## Highlights

- **Multi-frame capture:** the Android kiosk captures multiple distinct camera exposures; it does not duplicate one image to imitate temporal evidence.
- **1:1 verification and 1:N identification:** both use the same frame-burst and decision pipeline.
- **Fail-closed biometric decisions:** low-quality, ambiguous, unrecognized, liveness-unavailable, or invalid attendance-transition results are not treated as success.
- **Model and preprocessing accountability:** model artifacts have explicit paths, hashes, provenance contracts, versions, and preprocessing identifiers.
- **Enrollment and administration:** separately authenticated admin enrollment, roster and attendance views, model registry, and audit evidence.
- **Protected data:** embeddings are encrypted before database storage; ordinary logs must not contain raw face imagery or embeddings.
- **Automated quality gates:** Python compilation/lint/tests and Flutter analysis/tests/Android debug build run in GitHub Actions.

## Architecture

```text
Android camera burst
        │
        ▼
Flutter kiosk ── HTTPS + device credential ──► FastAPI
                                                  │
                        frame validation + face-quality gate
                                                  │
                          SCRFD detection + alignment
                                                  │
                                  ArcFace embedding
                                                  │
                     roster-scoped exact cosine retrieval
                                                  │
                    temporal evidence + policy / liveness
                                                  │
                 ACCEPT / UNKNOWN / RECAPTURE / REVIEW
                                                  │
                   attendance transition + audit record
```

The primary path is SCRFD → alignment → ArcFace. Optional specialist paths include RetinaFace recovery, AdaFace, MobileFaceNet, FIQA, conditional enhancement, and MiniFASNet liveness. They must be explicitly provisioned and calibrated for the deployment; having a configuration option does not mean a model is bundled, licensed, or validated.

## Repository map

| Path | Purpose |
| --- | --- |
| `lib/` | Flutter Android kiosk, camera burst capture, state and API client |
| `test/` | Flutter client-contract and state tests |
| `backend/app/api/` | FastAPI attendance, enrollment and admin routes |
| `backend/app/vision/` | Model loading, ONNX adapters and image-quality measurements |
| `backend/app/services/pipeline.py` | Recognition, temporal decision, enrollment and attendance policy |
| `backend/app/db/` | SQLAlchemy entities and database schema support |
| `backend/app/web/` | Browser admin console |
| `backend/app/benchmark.py` | Real-data benchmark and threshold evaluation |
| `backend/tests/` | Backend unit tests |
| `.github/workflows/` | CI quality gates |
| `backend/model-artifacts/` | Artifact provenance and model-contract documentation |

## Getting started

### Prerequisites

- Docker Engine with the Docker Compose plugin for the containerized backend.
- Flutter and the Android SDK for local kiosk development; the CI workflow is the canonical source for a tested toolchain.
- Separately sourced and properly licensed model artifacts compatible with the documented inference contracts.
- A secure deployment configuration and a validation data set representative of the intended users, cameras, lighting and unknown-person population.

### Backend configuration

1. From the repository root, enter `backend/`.
2. Run `python3 scripts/generate_secrets.py`. This creates a private `.env` file and refuses to overwrite an existing one by default.
3. Configure the remaining environment values and provision the model artifacts described in [backend/model-artifacts/README.md](backend/model-artifacts/README.md).
4. Review the model license, source, checksum, preprocessing contract and permitted-use statement for every artifact.
5. Start with `docker compose up --build -d` and inspect `docker compose logs -f api`.
6. Verify `/health`, `/health/live`, and `/health/ready`. A process responding to health requests is not evidence of biometric readiness.

See [backend/README.md](backend/README.md) for configuration, API, testing and operations.

### Flutter kiosk

From the repository root:

```bash
flutter pub get
flutter analyze --fatal-infos
flutter test --reporter expanded
flutter build apk --debug
```

Configure the backend URL and a **device** bearer credential in the kiosk settings. Administrator enrollment requires a separate server-validated admin credential. Use HTTPS on any non-loopback network; HTTP is intended only for explicitly enabled local development.

## API overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health` | Operational health snapshot |
| `GET` | `/health/ready` | Readiness gate |
| `POST` | `/api/v1/attendance/identify` | Automatic 1:N identification |
| `POST` | `/api/v1/attendance/verify` | Employee-scoped 1:1 verification |
| `POST` | `/api/v1/biometrics/enroll/admin` | Admin-authenticated multi-frame enrollment |
| `GET` | `/api/v1/admin/people` | Protected roster query |
| `GET` | `/api/v1/admin/attendance` | Protected attendance query |
| `GET` | `/api/v1/admin/audit/{audit_id}` | Protected audit evidence |
| `GET` | `/api/v1/admin/models` | Runtime model/registry status |

API documentation is available at `/docs` when the backend is running. The current routes and schema remain the source of truth.

## Testing and release gates

GitHub Actions checks Python compilation, lint and tests, and runs Flutter analysis, tests and an Android debug build. These automated checks verify software behavior and integration contracts; they do **not** establish recognition accuracy, demographic performance, presentation-attack resistance, real-device reliability, or production readiness.

Before a live deployment, complete the [release checklist](RELEASE_CHECKLIST.md): provision lawful model assets; calibrate model-specific thresholds on separated enrollment/known/unknown data; measure false-accept and false-reject rates; test attack-specific liveness performance; validate migrations, backups, retention and access controls; then run an end-to-end test on the target Android device and server.

## Next.js admin console (Sprint 1)

A Next.js App Router admin console now lives in `admin-web/`. The root pnpm workspace provides the requested development command:

```bash
pnpm install
cp admin-web/.env.example admin-web/.env.local
pnpm dev
```

Open `http://localhost:3000`, set the FastAPI base URL and enter the existing administrator bearer key in the sidebar. The console reads live backend health, people, attendance and model-registry data. The key remains in browser memory and is not configured as a `NEXT_PUBLIC_*` variable. For local browser-to-API requests, allow `http://localhost:3000` in `FRS_ALLOWED_ORIGINS`.

This is a development foundation, not a production admin portal. Institutional login/roles and private media storage (including any Cloudinary integration) are not implemented. The college domain API and database-backed session capture queue exist, but provider migrations and real-device/model validation remain outstanding. Do not expose the console publicly before authentication and authorization are strengthened.

## College domain (Sprint 2)

The protected college administration API and Next.js `/college` screen support departments, year-of-study class groups, sections, student profiles, class enrollments and attendance sessions. New student records are linked to the existing biometric identity record, but creating a student does not create a face embedding.

For Supabase or another PostgreSQL deployment, apply [the ordered migrations](backend/migrations/README.md) and keep the database URL server-side in FastAPI. The migration enables RLS without public/anon policies; the admin UI calls FastAPI and does not connect directly to the database. The same schema is PostgreSQL-portable for a later AWS RDS migration.

All college admin endpoints use the existing administrator bearer guard and write audit events for creation/enrollment/session changes. This is still a development administration model, not institutional SSO or role-based production access. The session-batch recognition path restricts matching to active enrollments in the session's class group. Legacy unscoped `/identify` and `/verify` routes are retained for development compatibility but rejected when `FRS_ENV=production`.

## Release status

**Latest prerelease:** [FRS v0.1.0 Alpha 1](https://github.com/nothingonly/Frs/releases/tag/v0.1.0-alpha.1). It includes an Android **debug APK** for development and integration evaluation, not a production-signed build.

There is **no production release**. Real, properly licensed model artifacts, deployment-specific threshold calibration, liveness/presentation-attack testing, and end-to-end validation on the target hardware remain release gates. See [RELEASE_NOTES.md](RELEASE_NOTES.md), [releases/v0.1.0-alpha.1.md](releases/v0.1.0-alpha.1.md), and [CHANGELOG.md](CHANGELOG.md) for scope and limitations.

## Security, privacy and licensing

Face data is sensitive. Deploy only with an appropriate legal basis, notice/consent process, access control, retention schedule, deletion workflow and incident plan. Keep `.env`, production keys, raw captures and biometric records out of version control and logs. See [SECURITY.md](SECURITY.md).

No software license has been granted by this repository unless a separate license file is added by the project owner. Model code and model weights can have different licenses; verify rights for the exact artifact and intended employment/attendance use before deployment. Public pretrained face-recognition weights are not automatically cleared for commercial attendance use.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes affecting recognition, security, persistence, audit or attendance state transitions must include tests and preserve fail-closed behavior.


## Session-based college attendance (Sprint 3)

The Next.js admin console includes a Sessions & jobs page for creating an open subject session for a configured class group, closing sessions, inspecting capture-job outcomes and retrying eligible failed jobs. The Android kiosk lists open sessions from the authenticated FastAPI server. Attendance capture is queued with an idempotency key; the server encrypts frames at rest while queued and processes the submitted burst through the configured biometric pipeline using only active enrollments in that class.

Kiosk session flow: GET /api/v1/attendance/sessions/open, POST /api/v1/attendance/sessions/{session_id}/batches, then GET /api/v1/attendance/batches/{batch_id}. The administrative queue endpoints require the administrator bearer credential. Apply backend/migrations/0003_capture_batches.sql after migrations 0001 and 0002 on a fresh PostgreSQL/Supabase database.

This implementation has not been tested against a live Supabase project or with target-device camera frames/model assets. The worker currently polls inside FastAPI; deployment-specific multi-instance and GPU-worker supervision still need implementation/review. See backend/migrations/README.md and SPRINT_STATUS.md for scope and validation boundaries.
