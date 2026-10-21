# FRS — Face Recognition Attendance System

> Secure, multi-frame biometric attendance verification and identification system combining a Flutter Android kiosk, a high-performance FastAPI vision backend, and a Next.js 16 administrative console.

[![Backend checks](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/backend.yml)
[![Admin web checks](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/admin-web.yml/badge.svg?branch=main)](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/admin-web.yml)
[![Flutter quality gate](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/flutter.yml/badge.svg?branch=main)](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/flutter.yml)
[![Staging vision CI](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/staging-vision-ci.yml/badge.svg?branch=main)](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/actions/workflows/staging-vision-ci.yml)

---

## About

FRS is an enterprise-grade attendance management system engineered around multi-frame computer vision, fail-closed security contracts, and institutional hierarchy modeling. 

Unlike naive face recognition setups that accept single webcam snapshots or trust client-side identification assertions, FRS enforces:
1. **Multi-frame temporal capture bursts** (minimum 3 distinct camera frames).
2. **Server-side cryptographic identity resolution** evaluated strictly against active cohort rosters.
3. **Pure ONNX Runtime inference** executing SCRFD face detection and ArcFace feature extraction without native C++ compilation toolchains.
4. **Vectorized SIMD retrieval optimization** with burst-level gallery memoization (delivering a **3.35x algorithmic retrieval speedup** in synthetic in-memory SQLite microbenchmarks).
5. **Session-scoped production attendance** preventing cross-class identity leakage and false acceptances.
6. **Encrypted biometric records at rest** (AES-256-GCM) with authenticated, short-lived private audit storage via Cloudinary.

> [!WARNING]
> **Project Status: Alpha / Technical Evaluation Only — Not Approved for Unsupervised Live Attendance.**
> Automated test suites (135 passed / 6 skipped on hosted CI due to unbundled binary weights; 141/141 passed locally in provisioned environments with Buffalo_L models, 29/29 Flutter tests, clean Next.js 16 build across 11 static routes) verify functional and integration contracts. However, real-world deployment requires site-specific threshold calibration, legal notice/consent execution, and commercial licensing clearance for model weights (Buffalo_L is released under DeepInsight's non-commercial research license).

---

## System Architecture

```text
       ┌────────────────────────────────────────────────────────┐
       │             Flutter Android Kiosk (Tablet)             │
       │  - Native camera burst capture (3-8 real exposures)    │
       │  - Android Keystore secured device credentials         │
       │  - Network Security Config (Strict HTTPS enforcement)  │
       └──────────────────────────┬─────────────────────────────┘
                                  │ HTTPS (Device Bearer Token)
                                  ▼
       ┌────────────────────────────────────────────────────────┐
       │             FastAPI Backend (Control Plane)            │
       │  - Idempotent capture queue (SHA-256 burst hash)       │
       │  - Frame quality & geometric integrity guards          │
       │  - Request size limiters & fail-closed error handling  │
       └──────────────────────────┬─────────────────────────────┘
                                  │
       ┌──────────────────────────▼─────────────────────────────┐
       │                Biometric Vision Engine                 │
       │  - SCRFD ONNX Detector (NMS xywh box geometry)         │
       │  - 5-point landmark affine normalization (norm_crop)   │
       │  - ArcFace ONNX Recognizer (512-d L2-normalized vector)│
       └──────────────────────────┬─────────────────────────────┘
                                  │
       ┌──────────────────────────▼─────────────────────────────┐
       │        Vectorized SIMD Retrieval & Session Policy      │
       │  - Burst-level gallery memoization (1 DB query/burst)  │
       │  - Vectorized matrix-vector dot product (G · q)        │
       │  - Class-group roster bounding (zero cross-class leak) │
       └──────────────────────────┬─────────────────────────────┘
                                  │
                 ┌────────────────┴────────────────┐
                 ▼                                 ▼
┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│     PostgreSQL / Supabase       │ │   Next.js 16 Admin Web Console  │
│ - AES-256-GCM encrypted vectors │ │ - Institutional hierarchy setup │
│ - Strict Row Level Security     │ │ - Multi-frame face enrollment   │
│ - Immutable audit trail records │ │ - Review queue & manual punches │
│ - Class sessions & batch queue  │ │ - Authenticated media previews  │
└─────────────────────────────────┘ └─────────────────────────────────┘
```

---

## Core Capabilities & Engineering Highlights

### 1. Robust Vision & Pure ONNX Runtime Engine
- **Zero C++ Build Tool Dependencies:** Custom native ONNX Runtime adapters ([`backend/app/vision/onnx_models.py`](backend/app/vision/onnx_models.py)) load and execute official InsightFace Buffalo_L graphs (`det_10g.onnx`, `w600k_r50.onnx`) without requiring Microsoft Visual C++ 14.0+ Build Tools or Cython compilation.
- **Fixed SCRFD NMS Box Distortion:** Converted bounding coordinates $[x_1, y_1, x_2, y_2] \to [x_1, y_1, w, h]$ prior to `cv2.dnn.NMSBoxes`, preventing false suppression of adjacent faces and guaranteeing `MULTIPLE_FACES` safety gating.
- **Affine Landmark Normalization:** Scales reference 5-point anchor coordinates proportionally to arbitrary input dimensions, ensuring sub-millimeter eye/nose/mouth alignment before ArcFace embedding extraction.

### 2. High-Performance Vectorized SIMD Retrieval
- **Burst-Level Gallery Memoization:** Active cohort biometric embeddings are fetched from the database and decrypted via AES-256-GCM **once** per burst, eliminating 66.7% of redundant DB queries and cryptographic operations during multi-frame capture.
- **BLAS Matrix-Vector Dot Product:** Replaces nested Python comparison loops with vectorized NumPy/BLAS SIMD matrix-vector multiplication ($\mathbf{s} = \text{clip}(\mathbf{G} \mathbf{q}, -1.0, 1.0)$).
- **Algorithmic Benchmark Evidence ([`backend/scripts/benchmark_retrieval_comparison.py`](backend/scripts/benchmark_retrieval_comparison.py)):**
  - **Workload & Setup:** Evaluated on an in-memory SQLite database seeded with 60 enrolled students, 512-D L2-normalized vectors, and 3-frame capture bursts across 100 iterations.
  - **Median Burst Retrieval Latency:** Reduced from **33.39 ms** (unoptimized per-frame DB fetch + Python loop) to **9.96 ms** (**3.35x speedup**).
  - **Single Frame Retrieval Latency:** Reduced from **11.23 ms** to **3.31 ms** (**3.39x speedup**).
  - **Scope & Applicability:** Measures database query reduction and SIMD vector dot-product efficiency. It does not measure physical camera sensor latency or campus Wi-Fi network transmission.

### 3. Session-Scoped Production Attendance Policy
- **Roster-Scoped Matching:** Attendance captures are strictly scoped to the active class session's enrolled students.
- **Production Safety Gate:** Legacy unscoped identification (`/api/v1/attendance/identify`) and verification (`/api/v1/attendance/verify`) endpoints are automatically rejected when running in `FRS_ENV=production` (`HTTP 403 Forbidden`). Clients must submit attendance via idempotent session capture batches (`/api/v1/attendance/sessions/{session_id}/batches`).

### 4. Next.js 16 Modern Administrative Console
- **Next.js 16 (App Router) + Turbopack + React 19:** High-performance, fully static prerendered admin UI with zero flash of unstyled content.
- **Interactive Multi-Frame Biometric Enrollment (`/enrollment`):** Live webcam preview with automated quality feedback (lighting, bounding size, centering) and multi-angle capture.
- **Exception & Review Queue (`/reviews`):** Human-in-the-loop workflow allowing administrators to review ambiguous, low-confidence, or flagged recognition attempts side-by-side with enrolled reference images.
- **Attendance Corrections & Manual Entries (`/attendance`):** Authorized audit-logged manual punches, punch status corrections (PRESENT, LATE, EXCUSED), and real-time roster filtering.
- **Secure Media Storage Integration:** Cloudinary authenticated image storage generating short-lived (5-minute) HMAC-signed access URLs. Raw images are never publicly readable.

### 5. Flutter Android Kiosk
- **Physical Multi-Frame Burst:** Captures 3 to 8 distinct camera exposures across a temporal window to verify motion and prevent single-frame photo replays.
- **Dedicated Lock Task Mode (Kiosk Pinning):** Supports Android Device Owner pinning ([`android/.../KioskDeviceAdminReceiver.kt`](android/app/src/main/kotlin/com/frs/kiosk/KioskDeviceAdminReceiver.kt)) to prevent students from exiting the application or accessing device controls.
- **Android Network Security Config:** Hard-blocks cleartext HTTP communication over public interfaces, permitting HTTP only on local development loopback (`10.0.2.2`, `127.0.0.1`).
- **Hardware-Backed Keystore:** Device bearer credentials are encrypted and stored via `flutter_secure_storage`.

### 6. Decoupled Worker Daemon & Dead-Letter Queue (DLQ)
- **Asynchronous Batch Processor ([`backend/app/worker.py`](backend/app/worker.py)):** Kiosk burst uploads are accepted idempotently and queued in the database, decoupling camera UI response times from neural network inference latency.
- **Crash Recovery & Concurrency Failsafes:** Unfinished or stalled batches (`PROCESSING` with heartbeat timeouts) are reclaimed gracefully, while poison-pill payloads are safely quarantined to dead-letter queue (`DLQ`) status with full error diagnostics after exceeding max retry budgets.

### 7. Scheduled Data Retention & Audit Purge
- **Automated Lifecycle Enforcement ([`backend/app/retention_worker.py`](backend/app/retention_worker.py)):** Independent maintenance worker purges expired biometric probe frames and archived attendance audits based on configurable retention limits (default 30 days).
- **Systemd Integration ([`deploy/systemd/`](deploy/systemd/)):** Hardened Linux systemd service and calendar timer (`frs-retention-purge.timer`) for unattended, scheduled execution in enterprise deployments.

### 8. Enterprise Observability & End-to-End Rehearsal
- **Prometheus & Grafana Dashboards ([`deploy/monitoring/`](deploy/monitoring/)):** Pre-configured metric scrapers and dashboards tracking queue depths, DLQ rates, burst inference latencies, and device status.
- **Automated Principal Rehearsal Runner ([`scripts/rehearse_principal_demo.py`](scripts/rehearse_principal_demo.py)):** 8-stage automated rehearsal runner verifying the complete live lifecycle (seeding hierarchy, opening session, burst capture, asynchronous worker inference, audit logging, and admin verification).

---

## Repository Map

| Directory / File | Description |
|---|---|
| [`lib/`](lib/) | Flutter kiosk application: camera capture, state machine, and API client |
| [`test/`](test/) | Flutter unit, widget, and client-contract test suites (29 tests) |
| [`admin-web/`](admin-web/) | Next.js 16 admin console (App Router, Turbopack, Tailwind CSS) |
| ├── [`app/attendance/`](admin-web/app/attendance/) | Attendance monitoring, status corrections, and manual punch entry |
| ├── [`app/enrollment/`](admin-web/app/enrollment/) | Multi-frame biometric student enrollment workflow |
| ├── [`app/reviews/`](admin-web/app/reviews/) | Human-in-the-loop review queue for flagged attendance captures |
| ├── [`app/audit/`](admin-web/app/audit/) | Cryptographic audit trail explorer with signed evidence previews |
| └── [`app/college/`](admin-web/app/college/) | Departments, class groups, sections, and student profile administration |
| [`backend/app/`](backend/app/) | FastAPI core: routes, security middleware, schemas, and lifecycle |
| ├── [`api/routes/`](backend/app/api/routes/) | Endpoints: attendance, sessions, college hierarchy, admin, audit |
| ├── [`vision/`](backend/app/vision/) | Pure ONNX Runtime engine, affine normalization, quality filters |
| ├── [`services/`](backend/app/services/) | Biometric pipeline, SIMD gallery retrieval, Cloudinary storage |
| ├── [`worker.py`](backend/app/worker.py) | Decoupled background capture batch processor with DLQ triage |
| ├── [`retention_worker.py`](backend/app/retention_worker.py) | Automated retention and audit lifecycle purge worker |
| └── [`db/`](backend/app/db/) | SQLAlchemy database models and migration definitions |
| [`backend/migrations/`](backend/migrations/) | Ordered PostgreSQL / Supabase SQL schema migrations (0001–0003) |
| [`backend/scripts/`](backend/scripts/) | Operational scripts: secret generation, model provisioning, benchmarks |
| [`backend/tests/`](backend/tests/) | Comprehensive pytest suite: security, math, worker, domain (141 tests) |
| [`deploy/`](deploy/) | Production deployment assets: systemd units, Prometheus and Grafana configs |
| [`scripts/`](scripts/) | Operational & rehearsal tooling: demo rehearsal, Android kiosk provisioning |
| [`docs/`](docs/) | Architecture specifications, ADRs, database recovery runbooks, reports |
| └── [`docs/adr/`](docs/adr/) | Architecture Decision Records (ADRs 0001–0006) |

---

## API Specification

All administrative endpoints require `Authorization: Bearer <FRS_ADMIN_API_KEY>`. Kiosk endpoints require `Authorization: Bearer <FRS_DEVICE_API_KEY>`.

### 1. System & Health
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `GET` | `/health/live` | Public | Process liveness probe |
| `GET` | `/health` | Public | Operational health snapshot and dependency checks |
| `GET` | `/health/ready` | Public | Biometric readiness gate (models, DB, storage) |

### 2. Session Attendance & Capture Queues
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/attendance/sessions/open` | Device / Admin | List currently active attendance sessions |
| `POST` | `/api/v1/attendance/sessions/{id}/batches` | Device | Submit idempotent multi-frame burst capture |
| `GET` | `/api/v1/attendance/batches/{batch_id}` | Device / Admin | Poll status and resolution of a queued capture batch |
| `POST` | `/api/v1/attendance/identify` | Device | *Dev-only* unscoped 1:N identification (Blocked in prod) |
| `POST` | `/api/v1/attendance/verify` | Device | *Dev-only* unscoped 1:1 verification (Blocked in prod) |

### 3. Biometric Enrollment & Management
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/biometrics/enroll/admin` | Admin | Multi-frame biometric enrollment with quality validation |
| `GET` | `/api/v1/admin/people` | Admin | List registered biometric identities and enrollment status |
| `POST` | `/api/v1/admin/people/{person_id}/deactivate` | Admin | Revoke biometric identity and purge cached embeddings |

### 4. Administrative Operations & Review
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/admin/attendance` | Admin | Filter attendance events by date, session, or status |
| `POST` | `/api/v1/admin/attendance/manual` | Admin | Authorized manual attendance punch |
| `PATCH` | `/api/v1/admin/attendance/{event_id}` | Admin | Correct attendance status (PRESENT, LATE, ABSENT) |
| `GET` | `/api/v1/admin/reviews` | Admin | Query unreviewed, flagged, or rejected capture attempts |
| `POST` | `/api/v1/admin/reviews/{id}/resolve` | Admin | Approve or reject flagged attendance submission |
| `GET` | `/api/v1/admin/audit` | Admin | Query immutable audit log events |
| `GET` | `/api/v1/admin/audit/{audit_id}` | Admin | Inspect detailed audit evidence payload & signed URLs |
| `GET` | `/api/v1/admin/models` | Admin | Query model registry, provenance, and active versions |

### 5. Institutional College Hierarchy
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `GET/POST`| `/api/v1/college/departments` | Admin | Manage academic departments |
| `GET/POST`| `/api/v1/college/class-groups` | Admin | Manage cohort class groups (year, program, term) |
| `GET/POST`| `/api/v1/college/sections` | Admin | Manage class sections (Section A, B, etc.) |
| `GET/POST`| `/api/v1/college/students` | Admin | Manage students and associate with biometric identities |
| `GET/POST`| `/api/v1/college/enrollments` | Admin | Enroll students into specific class groups |
| `GET/POST`| `/api/v1/college/sessions` | Admin | Create, open, and close classroom attendance sessions |

---

## Verification & Test Results
 
| Test Suite / Tool | Scope | GitHub Actions CI Status | Local Verified (with Provisioned Weights) |
|---|---|:---:|:---:|
| **Backend Pytest** | Unit, integration, security, worker & ONNX inference | **135 PASSED / 6 SKIPPED**¹ | **141 / 141 PASSED** |
| **Backend Ruff** | Linting and code style rules across Python code | **CLEAN (0 errors)** | **CLEAN (0 errors)** |
| **Admin Web ESLint** | TypeScript and React code conventions | **CLEAN (0 errors)** | **CLEAN (0 errors)** |
| **Admin Web TypeScript** | Strict typecheck (`tsc --noEmit`) | **CLEAN (0 errors)** | **CLEAN (0 errors)** |
| **Admin Web Production Build**| Next.js 16 prerendering (11 static routes) | **SUCCESS** | **SUCCESS** |
| **Flutter Static Analysis** | Dart static analyzer (`--fatal-infos`) | **CLEAN (0 warnings)** | **CLEAN (0 warnings)** |
| **Flutter Test Suite** | State management, widget, and contract tests | **29 / 29 PASSED** | **29 / 29 PASSED** |
| **Android Debug APK** | Full debug package build | **BUILT (Artifact)** | **BUILT (157.8 MB)** |

*¹ CI Note: The 6 skipped tests in GitHub Actions CI are in `tests/test_real_vision_inference.py`. They are automatically skipped on the hosted runner because real 200MB Buffalo_L binary model weights (`det_10g.onnx`, `w600k_r50.onnx`) are not checked into Git. Real ONNX model inference is verified in local and controlled staging environments where weights are provisioned.*

---

## Quickstart & Local Setup

### 1. Prerequisites
- **Python:** 3.11 or 3.12 with `venv` or `uv`
- **Node.js:** v20+ with `pnpm`
- **Flutter:** 3.x+ with Android toolchain
- **Database:** PostgreSQL 15+ (or Supabase local/cloud project)

### 2. Backend Setup
```bash
cd backend

# Create virtual environment & install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"

# Generate cryptographically secure keys (never commit .env)
python scripts/generate_secrets.py

# Provision and verify official Buffalo_L model artifacts
python scripts/provision_models.py

# Run test suite & verify
pytest -v
ruff check app tests scripts

# Start development API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Start background capture batch worker (in separate terminal)
python -m app.worker

# Optional: Run end-to-end principal rehearsal verification
python ../scripts/rehearse_principal_demo.py
```

### 3. Admin Web Setup
```bash
cd admin-web

# Install workspace dependencies
pnpm install

# Configure environment
cp .env.example .env.local

# Run development server with Turbopack
pnpm dev
# Open http://localhost:3000
```

### 4. Flutter Kiosk Setup
```bash
# From repository root
flutter pub get
flutter analyze --fatal-infos
flutter test
flutter run -d <device_id_or_emulator>
```

---

## Security, Privacy & Compliance Guidelines

1. **Biometric Data Protection:**
   - Facial embeddings are encrypted at rest using AES-256-GCM prior to database persistence.
   - Raw probe images are never logged or stored in plaintext. In-flight capture frames in the batch queue are encrypted and scrubbed immediately after processing.
2. **Zero-Trust Access Control:**
   - Device keys and Administrator keys are separate high-entropy credentials.
   - Kiosks can only submit attendance captures and poll batch results; they cannot access student rosters, audit logs, or administration endpoints.
3. **Audit Trail Immutability:**
   - Every administrative override, attendance correction, and biometric enrollment writes an immutable audit record containing actor identity, client IP, timestamp, and cryptographic event hash.
4. **Android Network Isolation:**
   - Android Network Security Config strictly disables cleartext HTTP across physical network interfaces. Plaintext HTTP is permitted only for local loopback addresses (`127.0.0.1`, `10.0.2.2`).

---

## Release Gates & Outstanding Blockers

Before deploying FRS into a live production environment, the following non-negotiable gates must be completed:
- [ ] **Model Weight Licensing Clearance:** Replace or obtain commercial licensing for DeepInsight Buffalo_L weights, which are currently limited to non-commercial academic research under the WebFace600K license.
- [ ] **Empirical Threshold Calibration:** Execute `backend/app/benchmark.py` on an on-premise dataset representing target camera optics, lighting variability, and demographic diversity to calibrate FAR/FRR thresholds.
- [ ] **Presentation Attack Testing:** Benchmark against physical presentation attack datasets (printed photos, 2D screens, 3D masks) before enabling unattended kiosk operations.
- [ ] **Regulatory Notice & Consent:** Implement institutional compliance procedures under applicable data protection regulations (GDPR, FERPA, BIPA) including student consent and biometric deletion workflows.

---

## Contributing, Security & Licensing

- **Contributing Guidelines:** We welcome contributions that adhere to the project's strict fail-closed security, biometric privacy, and testing policies. Please review [`CONTRIBUTING.md`](CONTRIBUTING.md) for development environment workflows, CI quality gates, and pull request guidelines.
- **Security Policy:** For vulnerability disclosure procedures, supported versions, and cryptographic trust boundaries, consult [`SECURITY.md`](SECURITY.md).
- **Release Checklist:** Review [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) for production operational gates, pre-flight verifications, and compliance controls.
- **Model Licensing Notice:** Official Buffalo_L weights are subject to DeepInsight non-commercial academic research terms. Commercial live deployments require licensing clearance or substitute model weights.
