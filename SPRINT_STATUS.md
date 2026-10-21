# FRS Sprint Status & Delivery Log

Last updated: 2026-10-21  
Branch status: `main` is up to date. Pull requests #1, #2, #3, #4, and #5 are **all merged**.  
Published Release: [`v0.1.0-alpha.2`](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/releases/tag/v0.1.0-alpha.2) with attached `app-debug.apk`.

---

## Sprint 1 — Next.js Admin Foundation (PR #2 — MERGED)

### Delivered
- Root pnpm workspace with Next.js App Router application in `admin-web/`.
- Responsive overview, people, attendance, and model registry screens connected to FastAPI admin routes.
- Student/employee search and audited deactivate/reactivate operations.
- Admin-web CI workflow for TypeScript typecheck, ESLint, and Next.js production build.

### Validation
- Admin web: `pnpm install`, TypeScript type-check, ESLint, and Next.js build clean in CI.
- pnpm lockfile (`pnpm-lock.yaml`) is committed at repository root for deterministic installations.

---

## Sprint 2 — College Domain Model & Admin Hierarchy (PR #3 — MERGED)

### Delivered
- SQLAlchemy entities and PostgreSQL migrations (0001, 0002) for departments, class groups, sections, students, class enrollments, and attendance sessions.
- Student records linked to biometric Person identities (`student_number` as identity key).
- Protected admin endpoints and Next.js `/college` management interface.
- Audit records generated for department/student/cohort creation, enrollment/withdrawal, and session lifecycle changes.

### Validation
- Unit & integration tests for cohort-section exclusivity, withdrawal/re-enrollment, and session idempotency.
- Database migrations verified with strict RLS (no public/anon access policies).

---

## Sprint 3 — Session-Scoped Capture Queue (PR #4 — MERGED)

### Delivered
- Migration 0003 creating durable `capture_batch_jobs` queue table; burst payloads packed and encrypted at rest with AES-256-GCM.
- Device-authenticated session batch ingestion endpoints (`POST /api/v1/attendance/sessions/{id}/batches`) with client idempotency keys.
- Atomic job claims, lease renewal, failure retries, and stale job recovery.
- Class-scoped gallery matching: matching is bounded strictly to active students enrolled in the session's class group.
- Next.js `/sessions` interface for monitoring capture batch queues and triggering retries.

### Validation
- Regression tests prove duplicate submissions cannot create duplicate attendance.
- In-process worker runs inside FastAPI; verified fail-closed behavior on non-accept decisions.

---

## Sprint 4 — Verified Vertical Slice & SIMD Retrieval Optimization (PR #5 — MERGED)

### Delivered
- **Pure ONNX Runtime Engine:** Integrated native ONNX Runtime adapters in `backend/app/vision/onnx_models.py` executing SCRFD (`det_10g.onnx`) and ArcFace (`w600k_r50.onnx`) without requiring MSVC C++ 14.0+ Build Tools or Cython.
- **Vision Geometry Fixes:** Fixed SCRFD bounding coordinate $[x_1, y_1, x_2, y_2] \to [x_1, y_1, w, h]$ conversion prior to `cv2.dnn.NMSBoxes` to prevent false adjacent face suppression. Fixed 5-point affine landmark scaling in `norm_crop`.
- **Vectorized SIMD Retrieval:** Implemented burst-level gallery memoization and BLAS matrix-vector dot products ($\mathbf{s} = \text{clip}(\mathbf{G} \mathbf{q}, -1.0, 1.0)$), cutting DB queries and AES decryptions by 66.7% across multi-frame bursts.
- **Next.js 16 Admin Screens:** Biometric multi-frame enrollment workflow (`/enrollment`), exception review queue (`/reviews`), manual punches & punch status corrections (`/attendance`), and audit trail explorer (`/audit`).
- **Secure Media Storage:** Authenticated Cloudinary private storage service (`app/services/storage.py`) generating short-lived (5-minute) signed URLs for audit previews.
- **Production Policy & Hardening:** Legacy unscoped `/identify` and `/verify` endpoints hard-blocked in `FRS_ENV=production` (`HTTP 403 Forbidden`). Zero secrets in repository (verified by GitGuardian).
- **Release Packaging:** Created GitHub Release `v0.1.0-alpha.2` with uploaded `app-debug.apk` (157.8 MB).

### Validation & CI Reporting Breakdown
- **GitHub Actions Remote CI:**
  - `backend-quality`: **89 PASSED, 6 SKIPPED**.
    - *CI Caveat:* The 6 skipped tests are `tests/test_real_vision_inference.py`. They are automatically skipped on the GitHub runner because the large binary Buffalo_L weights (`det_10g.onnx`, `w600k_r50.onnx`) are not checked into Git.
  - `admin-web-quality`: **CLEAN (0 errors)**. Prerendered 11 static pages.
  - `GitGuardian Security Checks`: **PASS (0 secrets detected across all commits)**.
  - `flutter`: **28 / 28 PASSED**, Dart static analysis clean (`--fatal-infos`), Android debug APK built.
- **Local Machine Validation (with provisioned model weights):**
  - Backend: **96 / 96 PASSED** (including all 6 real ONNX Buffalo_L inference tests and expanded calibration/provenance suites).
  - Retrieval Micro-Benchmark: Reduced median burst retrieval latency from **33.39 ms** to **9.96 ms** (**3.35x speedup**) on a synthetic test workload of 60 students and 3-frame bursts in an in-memory SQLite database. *Note:* This demonstrates algorithmic efficiency; it does not measure physical campus network or camera latency.

---

## Outstanding Release Gates & V4/V5 Implementation Gaps

1. **Model Licensing (Release Blocker):** Buffalo_L is restricted to non-commercial academic research (WebFace600K). Must clear commercial rights or transition to commercially licensed weights (MobileFaceNet / SFace / Glint360k ArcFace).
2. **Empirical Biometric Accuracy & Liveness (PAD):** Need separated enrollment/known/unknown probe datasets to calibrate FAR/FRR thresholds; passive presentation attack detection (ISO/IEC 30107-3) is unvalidated.
3. **Physical Hardware Validation:** Physical Android tablet testing against a reachable on-premise backend over live campus Wi-Fi remains unperformed.
4. **Out-of-Process Worker:** The capture batch worker currently runs inside the FastAPI process; needs decoupling into a dedicated GPU-capable worker service.
5. **Multi-Specialist Research Program:** Optional specialist models (AdaFace, MobileFaceNet, FIQA, RetinaFace recovery) exist as building blocks, but evidence-based selective routing and ablation benchmarks remain to be executed.
