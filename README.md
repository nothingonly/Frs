# FRS — Face Recognition Attendance System

> High-throughput multi-photo group attendance verification and identification system engineered for collegiate engineering environments. Combines a Flutter Android mobile/tablet camera interface, a high-performance FastAPI multi-face vision backend, and a Next.js 16 administrative console.

[![Backend checks](https://github.com/nothingonly/Frs/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/nothingonly/Frs/actions/workflows/backend.yml)
[![Admin web checks](https://github.com/nothingonly/Frs/actions/workflows/admin-web.yml/badge.svg?branch=main)](https://github.com/nothingonly/Frs/actions/workflows/admin-web.yml)
[![Flutter quality gate](https://github.com/nothingonly/Frs/actions/workflows/flutter.yml/badge.svg?branch=main)](https://github.com/nothingonly/Frs/actions/workflows/flutter.yml)
[![Staging vision CI](https://github.com/nothingonly/Frs/actions/workflows/staging-vision-ci.yml/badge.svg?branch=main)](https://github.com/nothingonly/Frs/actions/workflows/staging-vision-ci.yml)

---

## About

FRS is an enterprise-grade attendance management system specifically redesigned around a realistic **engineering-college group-photo attendance workflow**. Rather than forcing 60–70 students to line up one-by-one in front of a kiosk, faculty members capture several wide-angle group photos covering classroom rows and wings. The system automatically detects all student faces, matches them against the active session roster, ignores cross-photo duplicates, flags borderline similarities for review, and enables idempotent attendance finalization.

### Key Pillars & Engineering Standards:
1. **Collegiate Academic Hierarchy**: Out-of-the-box support for 7 engineering departments (`CSE`, `CSD`, `MECH`, `CIVIL`, `IT`, `ECE`, `EEE`), B.Tech academic years (1–4), semesters (1–8), sections (A–D), laboratory sessions, and combined elective classes.
2. **Multi-Photo Classroom Capture Loop**: Faculty can take multiple group photos covering different rows, left wings, and right wings. All captures aggregate into a single session provisional state with automatic cross-photo deduplication.
3. **Multi-Face SCRFD & ArcFace Pipeline**: Detects all faces in unconstrained classroom imagery, aligns facial landmarks via affine similarity transformation (`norm_crop`), and extracts 512-d ArcFace feature embeddings.
4. **Session-Scoped Roster Gallery**: Attendance matching is bounded strictly to enrolled students in the active session, preventing cross-cohort identity leakage.
5. **Interactive Faculty Review & Manual Overrides**: Real-time provisional roster table with confidence scores, search filters (`All`, `Present`, `Pending Review`, `Absent`), and 1-tap faculty overrides.
6. **Idempotent Finalization**: Durable `AttendanceEvent` records are only committed upon explicit authorized confirmation, marking the session permanently `CLOSED`.
7. **Bulk Ingestion & Biometric Onboarding**: Administrative bulk CSV/Excel import with dry-run validation preview and bulk student biometric photo enrollment with roll-number filename mapping.
8. **Dual-Mode Operation**: Seamlessly supports both the primary **Classroom Group Photo Mode** and the legacy **Individual 1:N Kiosk Mode**.

> [!WARNING]
> **Project Status: Beta / Technical Evaluation Only — Not Approved for Unsupervised Live Attendance.**
> Automated test suites (168 passed / 7 skipped on hosted CI due to unbundled binary weights; 175 total backend tests, 41/41 Flutter tests, clean Next.js 16 build across 10 static routes with hardened CSP) verify functional, cryptographic, and integration contracts. Forensic security audit remediations (FRS-01 through FRS-10, C-01, C-02, C-05, C-16, C-17, CI-01) enforce truthful biometric deletion certificates, cryptographic LTI 1.3 OIDC token verification, pinned SFTP host keys, fail-closed production database migration integrity, binary framing with SHA-256 tamper detection and Android Keystore AES-256-GCM offline queue storage. Real-world deployment requires site-specific threshold calibration, legal notice/consent execution, and commercial licensing clearance for model weights.

---

## System Architecture

```text
       ┌────────────────────────────────────────────────────────┐
       │             Flutter Android Interface                  │
       │  - Classroom Group Mode (Rear-camera default, wide     │
       │    framing brackets, lens switcher, multi-photo loop)  │
       │  - Live session metrics & provisional roster review    │
       │  - Optional 1:N Kiosk Punch mode with offline buffer   │
       └──────────────────────────┬─────────────────────────────┘
                                  │ HTTPS (Device / Faculty Bearer Token)
                                  ▼
       ┌────────────────────────────────────────────────────────┐
       │             FastAPI Backend (Control Plane)            │
       │  - Multi-photo group capture orchestrator              │
       │  - Session deduplication & provisional attendance DB   │
       │  - Bulk CSV import & bulk photo enrollment endpoints   │
       │  - Fail-closed auth & institutional scoping matrix     │
       └──────────────────────────┬─────────────────────────────┘
                                  │
       ┌──────────────────────────▼─────────────────────────────┐
       │                Biometric Vision Engine                 │
       │  - SCRFD Multi-Face Detector (NMS xywh box geometry)   │
       │  - 5-point landmark affine normalization (norm_crop)   │
       │  - ArcFace ONNX Recognizer (512-d L2-normalized vector)│
       │  - Laplacian variance sharpness quality gating         │
       └──────────────────────────┬─────────────────────────────┘
                                  │
       ┌──────────────────────────▼─────────────────────────────┐
       │        Vectorized SIMD Retrieval & Session Policy      │
       │  - Deduplicated session gallery memoization            │
       │  - Vectorized matrix-vector dot product (G · q)        │
       │  - Cross-photo duplicate suppression by student ID     │
       │  - Flagged match queuing (0.40 <= score < 0.50)        │
       └──────────────────────────┬─────────────────────────────┘
                                  │
                 ┌────────────────┴────────────────┐
                 ▼                                 ▼
┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│     PostgreSQL / Supabase       │ │   Next.js 16 Admin Web Console  │
│ - AES-256-GCM encrypted vectors │ │ - 7-department hierarchy setup  │
│ - Class groups, labs & sessions │ │ - Bulk CSV student onboarding   │
│ - Session provisional attendance│ │ - Bulk biometric photo mapper   │
│ - Immutable audit trail records │ │ - Web group capture & review    │
└─────────────────────────────────┘ └─────────────────────────────────┘
```

---

## Core Capabilities & Engineering Highlights

### 1. Multi-Photo Group Attendance Workflow
- **Classroom Row & Wing Photography**: Faculty members can take several photos of different sections of a classroom (front rows, back rows, side wings) during the same class hour.
- **Cross-Photo Deduplication**: If a student is captured in both Photo #1 and Photo #2, the pipeline identifies the match, counts Photo #2 as a duplicate ignored, and ensures exactly one attendance record is tracked.
- **Three-Tier Similarity Classification**:
  - **Match Confirmed ($\ge 0.50$)**: Automatically marked `PRESENT`.
  - **Borderline / Review ($0.40 \le \text{score} < 0.50$)**: Marked `PENDING_REVIEW` with match confidence score displayed for faculty review.
  - **Unknown / Non-Roster ($< 0.40$)**: Reported as an unrecognized attendee (e.g. visiting student or auditor) without corrupting class records.

### 2. Robust Vision & Pure ONNX Runtime Engine
- **Zero C++ Build Tool Dependencies**: Custom native ONNX Runtime adapters ([`backend/app/vision/onnx_models.py`](backend/app/vision/onnx_models.py)) load and execute official InsightFace Buffalo_L graphs (`det_10g.onnx`, `w600k_r50.onnx`) without requiring Microsoft Visual C++ Build Tools or Cython compilation.
- **Fixed SCRFD NMS Box Distortion**: Converted bounding coordinates $[x_1, y_1, x_2, y_2] \to [x_1, y_1, w, h]$ prior to `cv2.dnn.NMSBoxes`, preventing false suppression of adjacent faces in dense seating.
- **Affine Landmark Normalization**: Scales reference 5-point anchor coordinates proportionally to arbitrary input dimensions, ensuring sub-millimeter eye/nose/mouth alignment before ArcFace embedding extraction.

### 3. High-Performance Vectorized SIMD Retrieval
- **Burst-Level Gallery Memoization**: Active cohort biometric embeddings are fetched from the database and decrypted via AES-256-GCM once per group capture, eliminating redundant DB queries and cryptographic operations.
- **BLAS Matrix-Vector Dot Product**: Replaces nested comparison loops with vectorized NumPy/BLAS SIMD matrix-vector multiplication ($\mathbf{s} = \text{clip}(\mathbf{G} \mathbf{q}, -1.0, 1.0)$), yielding a **3.35x speedup**.

### 4. Next.js 16 Modern Administrative Console
- **Next.js 16 (App Router) + Turbopack + React 19**: High-performance, fully static prerendered admin UI across 10 static routes.
- **Bulk CSV / Excel Student Import (`/college`)**: Drag-and-drop file upload with dry-run validation preview table, error report badges, and bulk cohort enrollment.
- **Bulk Biometric Photo Enrollment (`/college`)**: Multi-photo upload with automatic roll-number filename parsing, single-face SCRFD validation, and encrypted embedding creation.
- **Web-Based Group Attendance (`/sessions`)**: Upload classroom group photos directly from browser file picker for any open session, see the multi-face recognition results, inspect the provisional roster, toggle student attendance, and finalize the session.

### 5. Flutter Android Interface
- **Rear Camera Default**: Automatically opens the rear-facing camera to photograph classroom rows, with an active lens badge and camera switcher button.
- **Classroom Framing Guide**: Replaced oval reticle with wide classroom corner brackets and rule-of-thirds grid guides.
- **Interactive Roster Review**: Search bar, status filter tabs (`All`, `Present`, `Pending Review`, `Absent`), confidence scores, and manual toggle overrides.
- **Idempotent Finalization**: Confirmation dialog summarizing total present, absent, and flagged resolution before committing durable records.
- **Secure Offline Queue**: Device credentials and offline bursts stored through `flutter_secure_storage` using Android encrypted SharedPreferences, with frame-format corruption checks, 24-hour expiry, and server idempotency on retries. The current queue does not use SQLCipher; target-device key protection and crash/reconnect behavior still require physical-device validation.

---

## Repository Map

| Directory / File | Description |
|---|---|
| [`lib/`](lib/) | Flutter kiosk & group photo app: camera viewport, state management, and API client |
| ├── [`lib/ui/widgets/camera_viewport.dart`](lib/ui/widgets/camera_viewport.dart) | Rear-camera default viewport with classroom framing brackets and lens switcher |
| ├── [`lib/ui/screens/kiosk_screen.dart`](lib/ui/screens/kiosk_screen.dart) | Redesigned group photo attendance screen with multi-photo capture and roster review |
| └── [`lib/models/group_attendance_models.dart`](lib/models/group_attendance_models.dart) | Data models for group captures, provisional state, and finalization |
| [`test/`](test/) | Flutter unit, widget, and client-contract test suites (41 tests) |
| [`admin-web/`](admin-web/) | Next.js 16 admin console (App Router, Turbopack) |
| ├── [`app/college/page.tsx`](admin-web/app/college/page.tsx) | 7-department hierarchy, bulk CSV import, and bulk photo enrollment |
| ├── [`app/sessions/page.tsx`](admin-web/app/sessions/page.tsx) | Specific/Lab/Mixed session setup, web group capture upload, and provisional review |
| ├── [`app/enrollment/`](admin-web/app/enrollment/) | Individual student biometric enrollment workflow |
| ├── [`app/reviews/`](admin-web/app/reviews/) | Human-in-the-loop review queue for flagged attendance captures |
| └── [`app/audit/`](admin-web/app/audit/) | Cryptographic audit trail explorer with signed evidence previews |
| [`backend/app/`](backend/app/) | FastAPI core: routes, security middleware, schemas, and lifecycle |
| ├── [`api/routes/attendance.py`](backend/app/api/routes/attendance.py) | Group capture, provisional roster, manual toggle, and finalization endpoints |
| ├── [`api/routes/college.py`](backend/app/api/routes/college.py) | Department seeding, bulk CSV import, bulk photo enrollment endpoints |
| ├── [`vision/engine.py`](backend/app/vision/engine.py) | Pure ONNX Runtime engine, multi-face SCRFD detection, ArcFace embeddings |
| ├── [`services/pipeline.py`](backend/app/services/pipeline.py) | Multi-photo group capture processor, gallery matching, and deduplication |
| └── [`db/entities.py`](backend/app/db/entities.py) | Database entities: class groups, labs, mixed sessions, provisional records |
| [`backend/migrations/`](backend/migrations/) | Ordered PostgreSQL / Supabase SQL schema migrations (0001–0005) |
| [`backend/tests/`](backend/tests/) | Comprehensive pytest suite: security, math, group workflow (175 tests) |
| [`deploy/`](deploy/) | Production deployment assets: systemd units, Prometheus and Grafana configs |
| [`docs/`](docs/) | Architecture specifications, ADRs, database recovery runbooks, reports |

---

## API Specification

All administrative endpoints require `Authorization: Bearer <FRS_ADMIN_API_KEY>`. Kiosk/device endpoints require `Authorization: Bearer <FRS_DEVICE_API_KEY>`.

### 1. Group Attendance & Capture Workflows
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/attendance/sessions/open` | Device / Admin | List active sessions with type, semester, lab name, and roster count |
| `GET` | `/api/v1/attendance/sessions/{id}/roster` | Device / Admin | Fetch unified, deduplicated student roster for a session |
| `POST` | `/api/v1/attendance/sessions/{id}/group-captures` | Device / Admin | Upload classroom group photo; detect all faces, match, and deduplicate |
| `GET` | `/api/v1/attendance/sessions/{id}/provisional` | Device / Admin | Fetch cumulative provisional attendance state and capture metrics |
| `POST` | `/api/v1/attendance/sessions/{id}/provisional/{student_id}/toggle` | Device / Admin | Manually toggle/override student status (`PRESENT`, `MARKED_ABSENT`) |
| `POST` | `/api/v1/attendance/sessions/{id}/finalize` | Device / Admin | Finalize session: persist durable `AttendanceEvent`s and close session |

### 2. Institutional College Hierarchy & Bulk Onboarding
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/admin/college/departments/seed-defaults` | Admin | Seed default 7 B.Tech departments (`CSE`, `CSD`, `MECH`, `CIVIL`, `IT`, `ECE`, `EEE`) |
| `POST` | `/api/v1/admin/college/students/bulk-import` | Admin | High-volume CSV/Excel student import with dry-run validation preview |
| `POST` | `/api/v1/admin/college/students/bulk-enroll-photos` | Admin | Bulk student biometric photo upload with roll-number mapping |
| `GET/POST`| `/api/v1/admin/college/departments` | Admin | Manage academic departments |
| `GET/POST`| `/api/v1/admin/college/class-groups` | Admin | Manage class groups and lab cohorts (semester 1–8, lab name) |
| `GET/POST`| `/api/v1/admin/college/students` | Admin | Manage students and associate with biometric identities |
| `GET/POST`| `/api/v1/admin/college/attendance-sessions` | Admin | Open theory, lab, or mixed multi-cohort attendance sessions |

### 3. Legacy Kiosk Batches & Biometrics
| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/attendance/sessions/{id}/batches` | Device | Submit idempotent multi-frame burst capture for 1:N kiosk |
| `GET` | `/api/v1/attendance/batches/{batch_id}` | Device / Admin | Poll status and resolution of a queued capture batch |
| `POST` | `/api/v1/biometrics/enroll/admin` | Admin | Single student biometric enrollment with quality validation |
| `GET` | `/api/v1/admin/reviews` | Admin | Query unreviewed, flagged, or rejected capture attempts |
| `POST` | `/api/v1/admin/reviews/{id}/resolve` | Admin | Approve or reject flagged attendance submission |
| `GET` | `/api/v1/admin/audit` | Admin | Query immutable audit log events |

---

## Verification & Test Results

| Test Suite / Tool | Scope | Status | Notes |
|---|---|:---:|:---:|
| **Backend Pytest** | Unit, integration, security, worker & group workflow | **168 PASSED / 7 SKIPPED**¹ | 7.17s total execution |
| **Backend Ruff** | Linting and code style rules across Python code | **CLEAN (0 errors)** | All rules passed |
| **Admin Web ESLint** | TypeScript and React code conventions | **CLEAN (0 errors)** | ESLint 9 clean |
| **Admin Web TypeScript** | Strict typecheck (`tsc --noEmit`) | **CLEAN (0 errors)** | 0 type errors |
| **Admin Web Production Build**| Next.js 16 prerendering (10 static routes) | **SUCCESS** | Prerendered with Turbopack |
| **Flutter Static Analysis** | Dart static analyzer (`flutter analyze`) | **CLEAN (0 issues)** | No warnings or errors |
| **Flutter Test Suite** | Group capture, state management, widget & contracts | **41 / 41 PASSED** | All tests passed |

*¹ CI Note: The 7 skipped tests in `tests/test_real_vision_inference.py` are automatically skipped when real Buffalo_L binary weights (`det_10g.onnx`, `w600k_r50.onnx`) are not checked into Git.*

---

## Releases & Version History

- **[`v0.3.0-beta.1`](https://github.com/nothingonly/Frs/releases/tag/v0.3.0-beta.1)** *(Latest)*
  - **Collegiate Group-Photo Attendance Redesign**: Replaced front-camera kiosk reticle with rear-camera multi-photo classroom group capture covering 60–70+ students.
  - **7 B.Tech Departments Seeding**: Built-in support for `CSE`, `CSD`, `MECH`, `CIVIL`, `IT`, `ECE`, `EEE`, B.Tech years (1–4), semesters (1–8), sections (A–D), and labs.
  - **Cross-Photo Deduplication**: Multi-angle group capture aggregation preventing duplicate attendance records.
  - **Interactive Faculty Review**: Searchable roster with filter tabs (`All`, `Present`, `Review Required`, `Absent`), similarity match scores, and manual toggle overrides.
  - **Admin Web Bulk Onboarding**: Added bulk CSV/Excel student import with dry-run preview and bulk student biometric photo enrollment with roll-number mapping.
  - **Dual Mode Support**: Seamless toggle between Group Photo Attendance and Individual 1:N Kiosk Punch modes.
- **[`v0.2.0-beta.2`](https://github.com/nothingonly/Frs/releases/tag/v0.2.0-beta.2)**
  - Hardened offline queue cryptographic framing & SHA-256 tamper detection in Android Keystore.
  - Database migration fail-closed integrity & startup assertions.
  - Production fail-closed guards for SFTP exports and LTI trust root validation.
- **[`v0.2.0-beta.1`](https://github.com/nothingonly/Frs/releases/tag/v0.2.0-beta.1)**
  - Hardware-encrypted offline burst buffer in Flutter with 24h fail-closed TTL.
  - Route-wide RBAC & scoping matrix restricting Deans to department and Faculty to class cohorts.
- **[`v0.1.0-alpha.1`](https://github.com/nothingonly/Frs/releases/tag/v0.1.0-alpha.1)**
  - Initial foundation release with FastAPI vision engine, Next.js 16 admin console, and Flutter kiosk.

---

## Quickstart & Local Setup

### 1. Prerequisites
- **Python**: 3.11 or 3.12 with `venv`
- **Node.js**: v20+ with `npm` or `pnpm`
- **Flutter**: 3.x+ with Android toolchain
- **Database**: PostgreSQL 15+ (or SQLite for development)

### 2. Backend Setup
```bash
cd backend

# Create virtual environment & install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"

# Generate cryptographically secure keys (never commit .env)
python scripts/generate_secrets.py

# Run test suite & verify
pytest backend/tests
ruff check backend

# Start development API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Admin Web Setup
```bash
cd admin-web

# Install dependencies
npm install

# Run typecheck and production build
npm run typecheck
npm run build

# Start development server
npm run dev
# Open http://localhost:3000
```

### 4. Flutter App Setup
```bash
# From repository root
flutter pub get
flutter analyze
flutter test
flutter run -d <device_id_or_emulator>
```

---

## Security, Privacy & Compliance Guidelines

1. **Biometric Data Protection**:
   - Facial embeddings are encrypted at rest using AES-256-GCM prior to database persistence.
   - Raw probe images are never logged or stored in plaintext. In-flight capture frames are scrubbed immediately after processing.
2. **Zero-Trust Access Control**:
   - Device keys, Faculty keys, Dean tokens, and Super Administrator tokens are strictly separated.
   - Kiosks and camera interfaces can only submit attendance captures and poll batch results; they cannot access student rosters, audit logs, or administration endpoints.
3. **Hardware Encrypted Offline Queue**:
   - Android Keystore encrypted burst buffer with 24-hour fail-closed expiration.
   - Instant wipe of raw capture frames from local flash upon server acceptance.
4. **Audit Trail Immutability**:
   - Every administrative override, attendance correction, and biometric enrollment writes an immutable audit record containing actor identity, client IP, timestamp, and cryptographic event hash.

---

## Author & Maintainers

**Katkam Koushik**  
*Lead Systems Architect & Full-Stack AI Engineer*  
GitHub: [@KatkamKoushik](https://github.com/KatkamKoushik)  
Repository: [FRS-Face-Recognition-Attendance-System](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System)  
Mirror Repository: [Frs](https://github.com/nothingonly/Frs)

---

## License & Compliance Notice

- Official Buffalo_L weights are subject to DeepInsight non-commercial academic research terms. Commercial live deployments require licensing clearance or substitute model weights.
- Consult [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md) for vulnerability disclosure and code standards.
