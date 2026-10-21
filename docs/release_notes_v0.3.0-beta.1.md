## FRS v0.3.0 Beta 1 — Collegiate Group-Photo Attendance Redesign

> [!NOTE]
> This release transitions FRS from individual 1:1/1:N kiosk queues to a high-throughput **multi-photo group capture workflow** designed specifically for engineering college classrooms and laboratories (60–70+ students per session).

### Major New Features & Enhancements

1. **Collegiate Academic Hierarchy (7 Departments)**:
   - Out-of-the-box support for the 7 standard engineering college departments: `CSE`, `CSD`, `MECH`, `CIVIL`, `IT`, `ECE`, and `EEE`.
   - Seed default departments endpoint: `POST /api/v1/admin/college/departments/seed-defaults`.
   - Complete cohort modeling across B.Tech years (1–4), semesters (1–8), sections (A, B, C, D), and laboratory batches.
   - Dual-cohort student enrollment allowing students to belong simultaneously to a lecture section and a laboratory batch.

2. **Multi-Photo Classroom Capture & Cross-Photo Deduplication**:
   - `POST /api/v1/attendance/sessions/{session_id}/group-captures`
   - Detects all faces in unconstrained classroom imagery using SCRFD (`max_num=0`), performs landmark affine normalization (`norm_crop`), and extracts 512-d ArcFace embeddings.
   - Matches faces against the active session roster gallery.
   - Cross-photo duplicate suppression: when faculty capture multiple rows or wings in the same class hour, students appearing in multiple captures are counted and deduplicated; no duplicate attendance records are created.
   - Borderline / uncertain matches (0.40 <= similarity < 0.50) are queued for faculty resolution.
   - Non-roster attendees (< 0.40) are reported without contaminating session attendance records.

3. **Faculty Roster Review & Idempotent Finalization**:
   - `GET /api/v1/attendance/sessions/{session_id}/provisional`
   - `POST /api/v1/attendance/sessions/{session_id}/provisional/{student_id}/toggle`
   - `POST /api/v1/attendance/sessions/{session_id}/finalize`
   - Real-time provisional roster table with confidence scores, search filters (`All`, `Present`, `Pending Review`, `Absent`), and 1-tap manual faculty overrides.
   - Explicit confirmation modal before committing durable `AttendanceEvent`s and closing the session.

4. **Flutter Application Redesign**:
   - Camera defaults to **rear-facing camera** (`CameraLensDirection.back`) with live lens indicator badge and camera flip button (`Icons.flip_camera_ios_rounded`).
   - Wide classroom corner framing guide (`_GroupFramingGuidePainter`) with rule-of-thirds grid.
   - Interactive classroom workflow stepper: Session Setup -> Group Photos -> Roster Review -> Finalization.
   - Segmented mode switcher in AppBar to toggle between `Group Photo` mode and legacy `Kiosk Punch` mode.

5. **Admin Web Portal Onboarding (`admin-web/`)**:
   - **Bulk Student CSV / Excel Import**: File upload with dry-run validation preview table, error report badges, and bulk cohort enrollment (`POST /api/v1/admin/college/students/bulk-import`).
   - **Bulk Biometric Photo Enrollment**: Multi-photo upload with automatic roll-number filename parsing, single-face SCRFD validation, and encrypted embedding creation (`POST /api/v1/admin/college/students/bulk-enroll-photos`).
   - **Web-Based Group Attendance**: Direct photo upload to open sessions with live multi-face detection, provisional review, and finalization (`admin-web/app/sessions/page.tsx`).

### Verified Test Status & Continuous Integration
- **GitHub Commit:** `ec8dfca` on `main` and `feature/group-photo-attendance`
- **Backend Tests:** 168 passed, 0 failed, 7 skipped (Ruff clean)
- **Flutter Tests:** 41 passed, 0 failed (Flutter analyze clean)
- **Admin Web Build:** Next.js 16 (App Router + Turbopack) built across 10 static routes (0 type errors, ESLint clean)
