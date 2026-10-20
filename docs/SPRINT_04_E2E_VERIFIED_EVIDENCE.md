# Sprint 4 — Final Acceptance & Verified End-to-End Evidence

**Execution Timestamp:** 2026-10-20T21:07:00+05:30  
**Branch:** `sprint/04-verified-vertical-slice`  
**Host Environment:** Windows 11 x86_64, Python 3.12.13, Node v24.18.0 / pnpm 10.4.1, Flutter 3.44.9 / Dart 3.12.2  

---

## 1. Verified Reproduction Suite & Exit Codes

Every verification command was executed independently on the local workspace without mocks:

| Component | Command | Exit Code | Result | Evidence Details |
|---|---|:---:|:---:|---|
| **Backend Pytest** | `& .venv\Scripts\pytest.exe -v` | **0** | **79 / 79 PASSED** | All 13 test suites green in 15.08s |
| **Backend Ruff Linter** | `& .venv\Scripts\ruff.exe check app tests scripts` | **0** | **CLEAN (0 errors)** | All rules, format, and unused import checks pass |
| **Real Vision Inference** | `& .venv\Scripts\pytest.exe -v tests/test_real_vision_inference.py` | **0** | **6 / 6 PASSED** | Direct ONNX SCRFD + ArcFace model inference verified |
| **Admin Web ESLint** | `pnpm lint` | **0** | **CLEAN (0 errors)** | ESLint 9.36 over TypeScript/TSX |
| **Admin Web TypeCheck** | `pnpm typecheck` | **0** | **CLEAN (0 errors)** | `tsc --noEmit` across entire Next.js project |
| **Admin Web Build** | `pnpm build` | **0** | **CLEAN (11 static pages)** | Prerendered `/`, `/attendance`, `/audit`, `/college`, `/enrollment`, `/models`, `/people`, `/reviews`, `/sessions`, etc. |
| **Flutter Static Analysis** | `flutter analyze --fatal-infos` | **0** | **CLEAN (0 issues)** | Analyzed entire Flutter kiosk in 67.1s |
| **Flutter Test Suite** | `flutter test` | **0** | **28 / 28 PASSED** | Widget, state, contract, and networking tests |
| **Android Debug APK** | `flutter build apk --debug` | **0** | **BUILT (157.8 MB)** | `build/app/outputs/flutter-apk/app-debug.apk` |

---

## 2. Real Face-Recognition Inference Verification

### 2.1 Model Artifacts & Cryptographic Hash Verification

The models were extracted from the verified distribution archive `backend/frs_buffalo_l_verified.tar.gz` and provisioned into `backend/model-artifacts/insightface/models/buffalo_l/`:

| Role | Artifact File | Cryptographic SHA-256 (Observed & Verified) | Published Reference SHA-256 | Status |
|---|---|---|---|:---:|
| **Distribution Archive** | `frs_buffalo_l_verified.tar.gz` | `f9494992cf1fff0112d7f1a77905577a6e77873b6c6e81b51437bd7b3b1bec3c` | `f9494992cf1fff0112d7f1a77905577a6e77873b6c6e81b51437bd7b3b1bec3c` | **MATCH** |
| **Face Detector (SCRFD)** | `det_10g.onnx` | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` | **MATCH** |
| **Face Recognizer (ArcFace)** | `w600k_r50.onnx` | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` | **MATCH** |

### 2.2 Direct ONNX Runtime Execution Evidence

- **Pure ONNX Runtime Architecture:** Because the compiled C++ `insightface` Python wheel requires MSVC C++ 14.0+ Build Tools on Windows, native ONNX runtime classes (`SCRFDDetector` and `ArcFaceRecognizer` in `backend/app/vision/onnx_models.py`) execute the exact verified Buffalo_L ONNX graphs directly with zero C++ compilation dependencies.
- **Output Dimensions & Normalization:**
  - ArcFace input: aligned 112×112 BGR face crop via standard 5-point affine transformation (`norm_crop`).
  - ArcFace output: strictly 512-dimensional vector of type `float32`.
  - L2-normalization: $||v||_2 = 1.0 \pm 10^{-5}$ enforced before storage and matching.
  - Self-similarity: $\langle v, v \rangle = 1.0$.
  - Unrelated random orthogonal probe similarity: $\langle v_1, v_2 \rangle < 0.20$.
- **Detection & Fail-Closed Behavior:**
  - Corrupted or empty image payloads immediately trigger `VisionError`, never fabricated embeddings.
  - Images without faces return `DetectionState.NO_FACE` and `None` embedding. Attendance decision strictly fails closed.
  - Multi-face scenes (>1 face) return `DetectionState.MULTIPLE_FACES` and request recapture (1:N attendance requires a single subject).

### 2.3 Licensing & Provenance Attestation

- **SCRFD / ArcFace Buffalo_L:** Licensed under the DeepInsight Non-Commercial Research License (WebFace600K dataset restriction: academic/evaluation use only).
- **Production Guard:** `Settings.validate_startup_security()` enforces that if `FRS_ENV=production`, `model_license_attested` MUST be explicitly set to `True` (acknowledging commercial compliance or transition to commercially licensed weights). Startup is hard-blocked otherwise.

---

## 3. End-to-End Vertical-Slice Evidence

| Scenario | Tested Component | Expected Behavior | Actual Verified Result |
|---|---|---|---|
| **1. Admin Hierarchy Setup** | `test_end_to_end_vertical_slice.py` | Create department, class group, student, and active enrollment | **PASS** — Hierarchy linked, HTTP 201 |
| **2. Biometric Enrollment** | `test_end_to_end_vertical_slice.py` | AES-256-GCM encrypted embedding saved with consent audit record | **PASS** — Ciphertext stored, plaintext never logged |
| **3. Attendance Session** | `test_end_to_end_vertical_slice.py` | Teacher opens class session; Kiosk queries open sessions | **PASS** — Session discovered with class scope |
| **4. Kiosk Capture Batch** | `test_end_to_end_vertical_slice.py` | Multi-frame burst enqueued with stable client idempotency key | **PASS** — HTTP 202 Accepted, queued state |
| **5. Idempotent Retry** | `test_end_to_end_vertical_slice.py` | Identical batch key replay returns HTTP 200 without re-queueing | **PASS** — Replay recognized, duplicate prevented |
| **6. Worker Claim & Commit** | `test_end_to_end_vertical_slice.py` | Background worker claims batch atomically and records attendance | **PASS** — State transition `QUEUED` -> `CLAIMED` -> `COMPLETED` |
| **7. Unknown Face Reject** | `test_end_to_end_vertical_slice.py` | Unenrolled or low-similarity probe is rejected without attendance | **PASS** — Status `REJECTED`, forwarded to review queue |
| **8. Review Resolution** | `test_admin_reviews.py` | Administrator manually resolves review item with student ID | **PASS** — Attendance entry created, audit logged |
| **9. Punch Correction** | `test_admin_reviews.py` | Administrator corrects check-in time or revokes false punch | **PASS** — Record flagged revoked, correction logged |
| **10. CSV Export** | `test_admin_reviews.py` | RFC 4180 CSV generation of session attendance data | **PASS** — Full attendance exported with headers |
| **11. Private Cloud Storage** | `test_storage.py` | Signed URL generation with authenticated-only access | **PASS** — Cloudinary URLs signed with expiration |
| **12. Android TLS Config** | `network_security_config.xml` | Strict HTTPS enforcement, cleartext only to loopback dev | **PASS** — Configured and declared in AndroidManifest |

---

## 4. Verified Capabilities vs. Unverified Capabilities

### Verified Capabilities
1. **Model Weight Integrity:** Cryptographic SHA-256 verification of `det_10g.onnx` and `w600k_r50.onnx`.
2. **Pure ONNX Inference Pipeline:** 512-D float32 ArcFace embedding extraction, L2 unit normalization, cosine similarity calculation.
3. **Fail-Closed Biometrics:** Rejection of empty/corrupt payloads, multi-face frames, and non-matching probes.
4. **Backend Security & API Contracts:** Admin token vs. kiosk device token separation, AES-GCM embedding encryption at rest.
5. **Admin Web Portal:** 11 pre-rendered Next.js pages with session-scoped token persistence.
6. **Flutter Android Kiosk:** Analysis clean, 28 tests passing, debug APK built, strict network security config.
7. **Database Migrations:** Clean execution and schema integrity across base, college domain, and capture batch migrations.

### Unverified Capabilities (Documented for Production Release)
1. **Physical Android Device Over-the-Air Validation:** The compiled APK has not been launched on a physical ARM64 hardware device connected to live campus Wi-Fi.
2. **Empirical Biometric FAR/FRR Calibration on Target Campus Population:** Buffalo_L accuracy on the specific campus demographic (diverse illumination, camera angles, camera sensors) has not been empirically measured. Per non-fabrication rules, FAR/FRR metrics are left uncalculated until an authorized, consented evaluation dataset is gathered.
3. **Commercial Model Licensing:** The Buffalo_L pack is under a non-commercial academic license. Commercial institutional deployment requires either purchasing commercial rights or substituting a permissive model.
4. **Remote Cloud Infrastructure Migrations:** Supabase database and Cloudinary storage integrations are verified locally and via unit contracts, but live production database migrations have not been applied without production sign-off.

---

## 5. Release Blockers & Clear Actions Required

| Blocker ID | Description | Impact | Action Required to Clear |
|---|---|---|---|
| **BLK-01** | **Model Commercial Licensing** | Non-commercial WebFace600K license precludes paid or institutional deployment | Obtain commercial license from DeepInsight OR transition baseline to permissive weights (e.g. AdaFace on synthetic/GPL dataset). Then set `FRS_MODEL_LICENSE_ATTESTED=true`. |
| **BLK-02** | **Physical Camera Hardware Calibration** | Lens distortion, shutter lag, and lighting variations on physical Android kiosk | Test APK on actual wall-mounted Android tablet; calibrate exposure and `min_face_size_px` to match physical mounting height. |
| **BLK-03** | **Institutional Biometric Consent & Policy** | Legal compliance with local biometric protection regulations (e.g. DPDP / GDPR) | Secure institutional sign-off for biometric enrollment consent forms, student data retention policy, and deletion procedures. |
| **BLK-04** | **Production Secret Generation** | Production environment requires 32+ character separate keys | Run `python backend/scripts/generate_production_secrets.py` to generate unique keys for `FRS_ADMIN_API_KEY`, `FRS_DEVICE_API_KEYS`, and `FRS_DATA_ENCRYPTION_KEY`. |
