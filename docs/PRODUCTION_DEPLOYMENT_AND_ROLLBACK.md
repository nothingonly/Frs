# FRS — Production Deployment & Rollback Runbook

This guide specifies the end-to-end production deployment, configuration, migration, and rollback procedures for the Face Recognition Attendance System (FRS).

---

## 1. Production Architecture & Invariants

FRS consists of four loosely-coupled, contract-enforced components:

1. **FastAPI Inference & Control Plane (`backend/app/`)**:
   - Python 3.11/3.12 running under Uvicorn/Gunicorn.
   - Enforces fail-closed biometric contracts, class/session scoping, request size guards, and cryptographic verification of all model artifacts.
   - Embeddings and queued capture frames are encrypted using AES-256-GCM (`FRS_DATA_ENCRYPTION_KEY`).
2. **PostgreSQL / Supabase Database (`backend/migrations/`)**:
   - Stores normalized entities (`departments`, `class_groups`, `students`, `class_enrollments`, `attendance_sessions`, `attendance_events`, `audit_events`, `capture_batch_jobs`, `model_registry`).
   - RLS enabled across all tables with zero public/anon policies. All operations route through the authenticated FastAPI service.
3. **Next.js Admin Console (`admin-web/`)**:
   - Next.js 16 (App Router) with Turbopack, React 19, TypeScript.
   - Authenticated via administrator bearer token stored in tab-scoped memory/sessionStorage.
   - Supports live dashboard stats, department/cohort setup, biometric enrollment, review queue resolution, punch correction, manual entry, and CSV export.
4. **Flutter Android Kiosk (`lib/`)**:
   - Android APK running in portrait mode.
   - Camera burst capture (minimum 3 frames, max 8 frames).
   - Android Network Security Config enforces HTTPS by default; plaintext HTTP is restricted strictly to local loopback (127.0.0.1, 10.0.2.2).
   - Device credentials stored securely in Android Keystore (`FlutterSecureStorage`).

---

## 2. Pre-Deployment Configuration & Secrets

### 2.1 Secret Generation
Never reuse development credentials or commit `.env` files into source control. Run the automated cryptographically-secure generator:

```bash
cd backend
python scripts/generate_secrets.py
```

This generates:
- `FRS_DATABASE_URL`: Server-side PostgreSQL connection string.
- `FRS_DEVICE_API_KEYS`: High-entropy (40-char) comma-separated device keys.
- `FRS_ADMIN_API_KEY`: High-entropy (40-char) administrator key.
- `FRS_DATA_ENCRYPTION_KEY`: 32-byte URL-safe base64 key for AES-GCM encryption.

### 2.2 Environment Variables (Production)

| Variable | Description | Required in Production |
|---|---|---|
| `FRS_ENV` | Environment identifier (`production`) | Yes |
| `FRS_DATABASE_URL` | PostgreSQL connection string (`postgresql+psycopg://...`) | Yes |
| `FRS_ADMIN_API_KEY` | Secret token for administrative access (>= 32 chars) | Yes |
| `FRS_DEVICE_API_KEYS` | Authorized kiosk bearer tokens (>= 32 chars each) | Yes |
| `FRS_DATA_ENCRYPTION_KEY` | 32-byte URL-safe base64 key for AES-GCM | Yes |
| `FRS_THRESHOLD_CALIBRATED` | Must be `true` after empirical FAR/FRR testing | Yes |
| `FRS_MODEL_LICENSE_ATTESTED` | Must be `true` after verifying model licenses | Yes |
| `FRS_ALLOWED_ORIGINS` | Comma-separated HTTPS origins for Next.js admin | Yes |
| `FRS_CLOUDINARY_CLOUD_NAME` | Cloudinary tenant for private media | Optional |
| `FRS_CLOUDINARY_API_KEY` | Cloudinary API Key | Optional |
| `FRS_CLOUDINARY_API_SECRET` | Cloudinary API Secret | Optional |

---

## 3. Database Migration Procedure

Migrations must be executed in order by a trusted DBA using PostgreSQL 15+ / Supabase:

```bash
# 1. Base schema (persons, embeddings, attendance, audit, model_registry, RLS)
psql "$PROD_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/0001_base_schema.sql

# 2. College domain (departments, class_groups, students, enrollments, sessions)
psql "$PROD_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/0002_college_domain.sql

# 3. Encrypted capture queue (capture_batch_jobs with idempotency & lease fields)
psql "$PROD_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/0003_capture_batches.sql
```

### Verification Query:
```sql
SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';
```
Ensure all 9 tables show `rowsecurity = true`.

---

## 4. Model Artifact Provisioning

Buffalo_L weights must be verified cryptographically before starting the service:

```bash
cd backend
python scripts/provision_models.py --archive /path/to/frs_buffalo_l_verified.tar.gz
```

Expected Cryptographic Checksums:
- `det_10g.onnx`: `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91`
- `w600k_r50.onnx`: `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43`
- Manifest: Automatically verified and linked at `backend/model-artifacts/insightface/models/buffalo_l/manifest.json`.

---

## 5. Startup Commands

### 5.1 Backend (Production Docker / Systemd)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips="*"
```
Verify health:
```bash
curl -f https://api.frs.college.edu/health
```

### 5.2 Next.js Admin Portal
```bash
cd admin-web
pnpm build
pnpm start -p 3000
```

### 5.3 Android Kiosk Setup
1. Build release APK:
   ```bash
   flutter build apk --release
   ```
2. On Android device, install APK:
   ```bash
   adb install -r build/app/outputs/flutter-apk/app-release.apk
   ```
3. On first launch, enter production backend HTTPS URL (`https://api.frs.college.edu`) and device bearer key. Settings are encrypted into Android Keystore.

---

## 6. Rollback Procedures

### 6.1 Application Service Rollback
If a defect is detected in a new release:
1. Revert container/commit to previous known-good tag:
   ```bash
   git checkout <PREVIOUS_STABLE_TAG>
   ```
2. Restart the FastAPI service:
   ```bash
   sudo systemctl restart frs-backend
   ```
3. Active attendance batches:
   - Any batches in `QUEUED` status will be safely claimed and processed by the older binary.
   - Any batches in `PROCESSING` that time out will be automatically recovered by `_recover_stale_jobs()` within 45 minutes or on service restart.

### 6.2 Database Rollback Strategy
Because FRS migrations are forward-compatible and additive (adding columns with `IF NOT EXISTS` and constraints):
- **Never run destructive drop statements (`DROP TABLE`) in production.**
- If a schema revision needs rollback, execute targeted, audited rollbacks:
  - For soft rollback of sessions: update status to `CANCELLED`.
  - For soft rollback of enrollments: update status to `WITHDRAWN`.
  - For soft rollback of people: call `POST /api/v1/admin/people/{id}/deactivate` (which writes an audit event).

### 6.3 Emergency Compromise / Key Rotation
If a device key or admin key is leaked:
1. Immediately edit `backend/.env` to remove the compromised token from `FRS_DEVICE_API_KEYS` or rotate `FRS_ADMIN_API_KEY`.
2. Reload backend without downtime:
   ```bash
   kill -HUP $(pgrep uvicorn)
   ```
3. The compromised key is instantly rejected with `401 Unauthorized`.
4. Audit log records all actions taken prior to revocation with actor fingerprint.
