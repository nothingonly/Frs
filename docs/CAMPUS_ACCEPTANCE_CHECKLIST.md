# FRS Production Readiness & Campus Acceptance Checklist (Gates 0–5)

**Document Reference:** `docs/CAMPUS_ACCEPTANCE_CHECKLIST.md`  
**Classification:** Institutional Deployment, Verification & Governance Framework  
**Target Architecture:** PostgreSQL + FastAPI Worker + Android Kiosk (Device Owner) + Next.js Admin  

---

## Executive Summary & Production Readiness Gate Framework

To bridge the gap between verified local unit/contract tests and genuine campus production readiness, the Facial Recognition Attendance System (FRS) adheres to a strict six-stage gate model (**Gates 0 through 5**). Passing local code suites is necessary but insufficient; institutional acceptance requires end-to-end evidence across security, biometric accuracy, device resilience, external delivery, and legal compliance.

```
+---------------------------------------------------------------------------------------------------+
| GATE 0: Governance, Biometric Consent & Non-Biometric Exception Workflow                          |
+---------------------------------------------------------------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------------------+
| GATE 1: Hardened CI Workflows, Model Integrity & Cryptographic Attestation                        |
+---------------------------------------------------------------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------------------+
| GATE 2: PostgreSQL Schema, Migrations, Worker Isolation & Dead-Letter Recovery                     |
+---------------------------------------------------------------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------------------+
| GATE 3: Biometric Accuracy, Presentation Attack Detection (ISO/IEC 30107-3) & Calibration        |
+---------------------------------------------------------------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------------------+
| GATE 4: Android Device Owner Provisioning, Hardware Lock Task & Encrypted Offline Burst Buffer    |
+---------------------------------------------------------------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------------------+
| GATE 5: Institutional LMS/SIS Integrations, Scheduled Follow-up & Delivery Reconciliation         |
+---------------------------------------------------------------------------------------------------+
```

---

## Gate 0: Governance, Privacy & Institutional Consent

| Checkpoint | Requirement | Status | Verification & Evidence Location |
|---|---|:---:|---|
| **0.1 Consent Policy** | Formal notice & consent policy covering biometric template generation, AES-256-GCM encryption, retention duration, and student right to de-enrollment. | **DOCUMENTED** | `docs/INSTITUTIONAL_BIOMETRIC_NOTICE_AND_CONSENT_POLICY.md` |
| **0.2 Non-Biometric Alternative** | Accessible fallback attendance recording mechanism for students with privacy opt-outs, temporary facial bandages/injuries, or religious facial coverings. | **VERIFIED IN CODE** | Endpoint `POST /api/v1/attendance/alternative`, `backend/tests/test_non_biometric_attendance.py` |
| **0.3 Student De-enrollment** | De-enrollment immediately deletes template embeddings and related audit payloads from database and signed object storage fail-closed. | **VERIFIED IN CODE** | Endpoint `DELETE /api/v1/admin/students/{id}/biometrics`, `backend/tests/test_rbac_scoping_matrix.py` |
| **0.4 Institutional Sign-Off** | Institutional Review Board (IRB), College Legal Counsel, and Data Protection Officer (DPO) formal written authorization. | **PENDING CAMPUS** | Requires signed institutional memorandum before campus deployment. |

---

## Gate 1: Hardened CI & Model Integrity

| Checkpoint | Requirement | Status | Verification & Evidence Location |
|---|---|:---:|---|
| **1.1 SHA-256 Hash Verification** | Face detection (`det_10g.onnx`) and feature extraction (`w600k_r50.onnx`) models match audited cryptographic hashes. | **VERIFIED** | Model hashes verified in `backend/app/vision/onnx_models.py` and `docs/SPRINT_04_E2E_VERIFIED_EVIDENCE.md` |
| **1.2 Zero Unchecked Tests** | Staging CI executes without artificial test skips when authorized weights are present. | **VERIFIED** | CI workflow `.github/workflows/staging-vision-ci.yml` |
| **1.3 Automated Static Analysis** | Zero lint, formatting, or typecheck errors across all three tiers (Python Ruff, Flutter Analyze, Next.js ESLint/TypeScript). | **VERIFIED** | `ruff check` (0 errors), `flutter analyze` (0 issues), `pnpm typecheck` (0 errors) |
| **1.4 Commercial Model Licensing** | Non-commercial WebFace600K dataset license attested or replaced with commercial permissive weights before production launch. | **ATTESTATION GUARDED** | `Settings.validate_startup_security()` rejects `FRS_ENV=production` unless `FRS_MODEL_LICENSE_ATTESTED=true`. |

---

## Gate 2: Backend Architecture & Production Database

| Checkpoint | Requirement | Status | Verification & Evidence Location |
|---|---|:---:|---|
| **2.1 Production PostgreSQL Assertion** | Production startup hard-rejects SQLite, ensuring PostgreSQL connection, schema migrations, and relational integrity. | **VERIFIED IN CODE** | `Settings.validate_startup_security()`, `backend/tests/test_production_database_config.py` |
| **2.2 Incremental Migrations & Rollback** | Database migrator applies versioned SQL migrations (`0001` through `0004_dead_letter_status.sql`) atomically inside transactions, rolling back cleanly on error. | **VERIFIED IN CODE** | `backend/app/db/migrator.py`, `backend/tests/test_database_migrator.py` (7/7 tests passed) |
| **2.3 Route-Wide Scoping Matrix** | Dean access scoped to faculty department; Faculty access scoped to assigned class groups; destructive operations restricted to Super Admin. | **VERIFIED IN CODE** | `backend/app/api/routes/admin.py`, `backend/tests/test_rbac_scoping_matrix.py` (6/6 tests passed) |
| **2.4 Dead-Letter Queue & Requeue** | Poison-pill captures transition to `DEAD_LETTER` after max retries; Super Admin and authorized Deans can inspect payload and requeue. | **VERIFIED IN CODE** | `backend/app/services/capture_batches.py`, `backend/tests/test_capture_worker_retries.py` |
| **2.5 Automated Retention Purge** | Timed retention worker purges capture batch raw image payloads exceeding retention window (default 7 days) and expired dead-letter items. | **VERIFIED IN CODE** | `backend/app/services/retention.py`, `backend/tests/test_retention_worker.py` |

---

## Gate 3: Biometric Accuracy & Presentation Attack Detection (PAD)

| Checkpoint | Requirement | Status | Verification & Evidence Location |
|---|---|:---:|---|
| **3.1 ISO/IEC 30107-3 PAD Metrics** | Presentation Attack Detection evaluated for Attack Presentation Classification Error Rate (APCER) and Bona Fide Presentation Classification Error Rate (BPCER). | **VERIFIED IN CODE** | `backend/tests/test_presentation_attack_detection.py` (4/4 tests passed) |
| **3.2 Spoof Rejection Enforcement** | Spoof presentations (photo printouts, tablet screen replays) are rejected with HTTP 403 `LIVENESS_FAILED` without recording attendance. | **VERIFIED IN CODE** | `AttendancePipeline.identify()`, `backend/tests/test_presentation_attack_detection.py` |
| **3.3 Campus Demographic Calibration** | Threshold calibration on target student population across skin tones, lighting conditions, and camera mounting angles. | **PENDING CAMPUS** | Requires on-site biometric capture trials with representative sample (recommended $N \ge 300$ subjects, 10,000+ verification pairs). |
| **3.4 Target Operating Thresholds** | $\text{FAR} \le 0.01\%$, $\text{FRR} \le 1.0\%$, and $\text{APCER} \le 2.0\%$ at $\text{BPCER} \le 1.0\%$. | **PENDING PILOT** | Acceptance threshold calibration protocol documented in `docs/MODEL_COMMERCIAL_LICENSING_AND_ALTERNATIVES.md`. |

---

## Gate 4: Managed Android Kiosk & Offline Resilience

| Checkpoint | Requirement | Status | Verification & Evidence Location |
|---|---|:---:|---|
| **4.1 Hardware Lock Task Mode** | Tablet runs in dedicated Lock Task mode, disabling Home, Overview, Notifications, and Power menu navigation escape attempts. | **VERIFIED IN CODE** | `android/app/src/main/kotlin/com/frs/kiosk_app/KioskLockTaskService.kt`, `lib/services/kiosk_lock_task_service.dart` |
| **4.2 Device Owner Provisioning** | Automated provisioning script registers `KioskDeviceAdminReceiver` via ADB or QR enrollment. | **VERIFIED SCRIPT** | `scripts/provision_android_kiosk_device_owner.bat`, `scripts/verify_kiosk_hardware_readiness.ps1` |
| **4.3 Encrypted Offline Burst Buffer** | During network outages, 3-to-16 frame camera bursts are hardware-encrypted with 16-byte nonce and buffered up to 500 batches. | **VERIFIED IN CODE** | `lib/services/offline_queue_service.dart`, `test/offline_queue_service_test.dart` (6/6 tests passed) |
| **4.4 Fail-Closed Expiration** | Offline batches older than 24 hours are automatically purged fail-closed without transmission to prevent stale attendance insertion. | **VERIFIED IN CODE** | `OfflineQueueService.purgeExpiredBatches()`, `test/offline_queue_service_test.dart` |
| **4.5 Auto-Drain & Raw Wipe** | When network connectivity restores, background drain worker verifies backend health, streams pending batches FIFO, and immediately wipes raw payloads upon HTTP 200/202 acceptance. | **VERIFIED IN CODE** | `OfflineQueueService.drainQueue()`, `lib/state/kiosk_state.dart` |

---

## Gate 5: Institutional Integrations & Scheduled Operations

| Checkpoint | Requirement | Status | Verification & Evidence Location |
|---|---|:---:|---|
| **5.1 Automated Absentee Reconciliation** | Background daemon automatically scans closed attendance sessions, identifies absent students, and dispatches multi-channel alerts (SMS/Email). | **VERIFIED IN CODE** | `backend/app/services/followup_worker.py`, `backend/tests/test_followup_worker.py` |
| **5.2 SFTP Attendance Export** | Daily session attendance exports generated and uploaded via encrypted SFTP to institutional SIS server with host-key verification. | **VERIFIED IN CODE** | `backend/app/services/integrations.py`, `backend/tests/test_outbound_integrations.py` |
| **5.3 Outbound Webhooks** | Real-time webhook notifications dispatched for `attendance.marked`, `attendance.anomaly_detected`, and `batch.dead_lettered` with HMAC-SHA256 signature verification. | **VERIFIED IN CODE** | `backend/app/services/integrations.py`, `backend/tests/test_outbound_integrations.py` |
| **5.4 Prometheus & Grafana Telemetry** | Full system metrics exposed at `/metrics` (request latency, queue depth, active worker count, dead-letter counter, match confidence histogram). | **VERIFIED IN CODE** | `backend/app/metrics/prometheus.py`, `deploy/grafana/dashboards/frs_overview.json` |

---

## Institutional Sign-Off Matrix

Before transition from pilot staging to full production authorization, the designated campus stakeholders must review the evidence logs and execute this sign-off matrix:

| Stakeholder Role | Responsibilities | Criteria for Sign-Off | Signature & Date |
|---|---|---|:---:|
| **Dean of Academic Affairs** | Academic scheduling, class attendance rules, and absentee policy alignment. | Review and approve non-biometric exception procedures and faculty manual correction workflow. | `____________________` |
| **Campus Chief Information Officer (CIO)** | Server infrastructure, PostgreSQL deployment, network firewall, and SFTP/LMS integration. | Confirm staging backup restoration runbook, TLS certificate pinning, and Prometheus alert routes. | `____________________` |
| **Data Protection Officer (DPO)** | Student privacy compliance, biometric data encryption, retention duration, and deletion rights. | Audit `INSTITUTIONAL_BIOMETRIC_NOTICE_AND_CONSENT_POLICY.md` and confirm fail-closed de-enrollment. | `____________________` |
| **Lead Hardware / Facilities Officer** | Physical tablet mounting, camera field of view, lighting, and power supply reliability. | Run `scripts/verify_kiosk_hardware_readiness.ps1` on all deployed kiosk tablets; confirm Lock Task active. | `____________________` |

---
*Last Updated: 2026-10-21 — FRS Systems Architecture Group*
