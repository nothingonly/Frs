# FRS — Managed Database Migration and Disaster Recovery Runbook

**Document Reference:** FRS-OPS-DOC-003
**Target Gate:** Gate 2 (Security and Worker Reliability)
**Applicability:** Managed PostgreSQL / Supabase / Neon / Cloud SQL

---

## 1. Overview and Recovery Objectives
This runbook provides step-by-step procedures for deploying, migrating, backing up, and performing Point-in-Time Recovery (PITR) on managed PostgreSQL instances hosting the FRS database.

### 1.1 Recovery Objectives (SLOs)
- **Recovery Point Objective (RPO):** $\le 5$ minutes (maximum acceptable data loss window via continuous WAL archiving).
- **Recovery Time Objective (RTO):** $\le 30$ minutes (maximum time to restore database and resume kiosk attendance ingestion).

---

## 2. Managed Database Migration Procedure

### 2.1 Pre-Migration Health Checks
1. Verify database connectivity:
   ```bash
   psql "$DATABASE_URL" -c "SELECT version();"
   ```
2. Verify active connection count and disk space:
   ```bash
   psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity;"
   ```

### 2.2 Applying Database Migrations
Migrations are maintained as ordered, idempotent SQL scripts in `backend/migrations/`:
- `0001_base_schema.sql` (core biometric tables, audit trail, model registry)
- `0002_college_domain.sql` (departments, class groups, students, sessions)
- `0003_capture_batches.sql` (encrypted capture batch queue and RLS)
- `0004_dead_letter_status.sql` (DEAD_LETTER constraint forward-migration)

Apply directly via psql:
```bash
for migration in backend/migrations/*.sql; do
    echo "Applying $migration..."
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
done
```
Or initialize and verify compatibility via the application schema runner:
```bash
python -c "from app.database import create_schema; create_schema()"
```
Verify all tables and constraints exist:
```bash
psql "$DATABASE_URL" -c "\dt"
# Expected tables:
# - attendance_events
# - attendance_sessions
# - audit_events
# - capture_batch_jobs
# - class_enrollments
# - class_groups
# - departments
# - embedding_records
# - model_registry
# - persons
# - students
```

---

## 3. Backup Strategy and Execution

### 3.1 Automated Snapshot Schedule
- **Full Daily Logical Backup:** Executed daily at 01:00 UTC via `pg_dump` with compressed custom format (`-Fc`).
- **Continuous WAL Archiving:** Write-Ahead Logs streamed to object storage (S3 / GCS / Supabase Storage) every 60 seconds.

### 3.2 Manual Pre-Deployment Backup
Always execute a standalone snapshot prior to code releases or schema migrations:
```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
pg_dump "$DATABASE_URL" -Fc -f "frs_backup_${TIMESTAMP}.dump"
sha256sum "frs_backup_${TIMESTAMP}.dump" > "frs_backup_${TIMESTAMP}.dump.sha256"
```

---

## 4. Disaster Recovery & Point-in-Time Recovery (PITR) Drill

### 4.1 Simulated Disaster Scenarios
1. **Accidental Table Truncation / Data Corruption:** Operator or bug alters attendance records.
2. **Database Instance Failure:** Managed database node crashes or suffers storage volume failure.

### 4.2 Restoring from Full Dump
```bash
# 1. Terminate active backend workers and API instances
systemctl stop frs-backend frs-worker

# 2. Provision or reset target database
psql "$DATABASE_ADMIN_URL" -c "DROP DATABASE IF EXISTS frs_recovery;"
psql "$DATABASE_ADMIN_URL" -c "CREATE DATABASE frs_recovery;"

# 3. Restore schema and data
pg_restore -d "$RECOVERY_DATABASE_URL" -v "frs_backup_${TIMESTAMP}.dump"

# 4. Verify integrity and record counts
psql "$RECOVERY_DATABASE_URL" -c "SELECT count(*) FROM students;"
psql "$RECOVERY_DATABASE_URL" -c "SELECT count(*) FROM attendance_events;"
psql "$RECOVERY_DATABASE_URL" -c "SELECT count(*) FROM capture_batch_jobs WHERE status = 'DEAD_LETTER';"

# 5. Point backend to recovered database and restart
export DATABASE_URL="$RECOVERY_DATABASE_URL"
systemctl start frs-backend frs-worker
```

### 4.3 Executing Point-in-Time Recovery (PITR)
On managed cloud platforms (Supabase / AWS RDS / GCP Cloud SQL):
1. In the cloud management console or CLI, navigate to **Backups & Restore**.
2. Select **Point-in-Time Restore**.
3. Specify the target recovery timestamp (e.g. `2026-10-21 12:00:00 UTC`, 1 minute prior to the incident).
4. Launch the restored instance to a new endpoint (e.g., `frs-db-restored.postgres.internal`).
5. Update DNS or `DATABASE_URL` environment secret and execute health probes:
   ```bash
   curl -s http://localhost:8000/health/ready | jq .
   # Expected: {"status": "ready"}
   ```

---

## 5. Drill Verification Sign-Off Checklist
- [ ] Pre-migration snapshot generated with valid SHA-256 checksum.
- [ ] Restore executed into isolated staging instance without errors.
- [ ] Automated regression test suite passes 100% against restored database.
- [ ] Measured recovery time $\le 30$ minutes.
