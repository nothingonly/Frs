# Release Notes

## Release `v0.2.0-beta.1` (Current Milestone)

**Release Date:** October 21, 2026  
**Type:** Feature & Resilience Milestone (Beta)  
**Author:** Katkam Koushik  

### Highlights & New Capabilities
1. **Hardware-Encrypted Offline Burst Buffer:**
   - Android Keystore EncryptedSharedPreferences / AES stream cipher with 16-byte random nonce.
   - 3-to-16 frames per capture burst; 24-hour fail-closed retention policy.
   - Upper limit of 500 batches to prevent flash exhaustion.
   - Background reconnection auto-drain worker with immediate flash wipe upon server acceptance.
2. **Route-Wide RBAC & Scoping Matrix:**
   - Multi-tier authorization distinguishing Super Admin, Deans, Faculty, and Kiosk Devices.
   - Deans restricted to department for audit, review queue, dead-letter, and student de-enrollment.
   - Faculty restricted to assigned class cohorts; destructive operations restricted to Super Admin.
3. **Database Migrator with Transactional Rollback:**
   - Atomic forward SQL migrations (`0001` through `0004_dead_letter_status.sql`).
   - Transactional rollback on error to prevent partial/corrupt database schema drift.
4. **Presentation Attack Detection (PAD) Aligned to ISO/IEC 30107-3:**
   - Spoof presentation error metrics: APCER, BPCER, and ACER.
   - Enforcement of HTTP 403 `LIVENESS_FAILED` on presentation attacks.
5. **Automated Attendance Follow-up Daemon:**
   - Polls closed sessions, reconciles absentees, dispatches multi-channel alerts (SMS/Email), and SFTP export.
   - Service unit `frs-followup-worker.service` and Compose integration.
6. **Android Kiosk Lock Task Service & Hardware Verification:**
   - Lock Task service integration and ADB hardware readiness probe (`verify_kiosk_hardware_readiness.ps1`).

---

## Release `v0.1.0-alpha.1` (Initial Foundation)

**Release Date:** October 21, 2026  
**Type:** Foundation Architecture (Alpha)  

- Flutter Android kiosk with native multi-frame camera burst capture.
- Device-authenticated 1:N identification and employee-scoped 1:1 verification APIs.
- Separately authenticated administrator multi-frame biometric enrollment.
- FastAPI vision service with pure ONNX Runtime SCRFD/ArcFace engine.
- AES-256-GCM encryption at rest for biometric embeddings.
- Next.js 16 modern administrative console with 11 prerendered static routes.
- CI workflows for code quality, tests, and Android debug APK compilation.

---

### Before a Release Can Be Labelled Production-Ready
Complete every item in [`docs/CAMPUS_ACCEPTANCE_CHECKLIST.md`](docs/CAMPUS_ACCEPTANCE_CHECKLIST.md) (Gates 0 through 5), require passing CI on the release candidate commit, publish a reproducible build and SBOM, verify licenses and privacy obligations, and review operational rollback/backup procedures.

