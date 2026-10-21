# FRS — Institutional Biometric Notice, Consent, and Alternative Attendance Policy

**Document Reference:** FRS-GOV-POL-001
**Status:** Approved Engineering Model for Campus Legal/Institutional Review
**Governing Frameworks:** FERPA (Family Educational Rights and Privacy Act), GDPR (General Data Protection Regulation, Art. 9), ISO/IEC 19794-5, ISO/IEC 30107-3

---

## 1. Purpose and Scope
This policy establishes the formal terms governing the collection, processing, encryption, retention, and deletion of facial biometric data within the Face Recognition Attendance System (FRS). It provides students, faculty, and administrators with clear legal disclosures and establishes mandatory, equal non-biometric alternatives for any student who elects not to participate in biometric attendance verification.

---

## 2. Institutional Biometric Notice (Student & Faculty Disclosure)

### 2.1 What Data Is Collected
1. **Facial Probe Images (Temporary):** High-speed multi-frame camera bursts (3 to 8 frames) captured during attendance sessions.
2. **Facial Feature Embeddings (Mathematical Representation):** 512-dimensional numerical float vectors extracted via pure ONNX Runtime models (ArcFace/SCRFD). FRS **never stores raw facial geometry or photographic likeness in database columns**.
3. **Audit Records:** Non-biometric metadata including timestamp, session ID, subject code, confidence score, and client kiosk device ID.

### 2.2 Purpose of Collection
Biometric data is collected solely to authenticate student attendance in authorized university class groups and examinations. Biometric data will **never** be used for marketing, surveillance, commercial profiling, or shared with third parties, law enforcement, or commercial vendors without explicit judicial subpoena.

### 2.3 Cryptographic Safeguards
- **Field-Level Encryption:** All 512-D float vectors are encrypted at rest using AES-256-GCM prior to database commit.
- **Payload Minimization:** Raw probe images in the capture batch queue are encrypted in transit and at rest, and automatically purged within 24 to 72 hours of verification.
- **Log Sanitization:** Server and client diagnostic logs use automated redaction filters (`RedactingFilter`) ensuring raw vectors and image payloads are never written to disk or stdout.

---

## 3. Explicit Consent and Voluntary Participation

Participation in the biometric attendance system is **strictly voluntary**.
- Prior to enrollment, students must sign an explicit, affirmative Biometric Consent Agreement.
- Consent may be revoked at any time by submitting a de-enrollment request via the Registrar or Department Administrative Office.
- Revocation of consent carries **zero academic penalty or discrimination**.

---

## 4. Equal Non-Biometric Attendance Alternatives

In compliance with institutional governance and privacy mandates, an equal, non-biometric attendance mechanism must be available in every lecture hall:

### 4.1 Approved Alternative Methods
1. **Administrative Roster Check-In (Faculty / Teaching Assistant):**
   - The instructor or proctor records attendance manually via the Admin Web Console (`POST /api/v1/admin/attendance/manual-entry`).
   - The student's attendance event is recorded with status `PRESENT` and decision state `MANUAL_ENTRY`, with full audit attribution.
2. **Kiosk PIN / University ID Card Scan:**
   - Kiosk interfaces support student ID number entry or NFC smart-card tap, bypassing camera capture entirely.
3. **Department Office Paper Sign-In:**
   - Daily attendance slips signed by the instructor and countersigned by the department coordinator.

### 4.2 Non-Biometric Record Storage
Students opting out of biometrics have standard student records (`Student`), but zero entries in `embedding_records`. Manual attendance records link to an un-enrolled demographic identity with decision state `MANUAL_ENTRY`.

---

## 5. Biometric Data Retention and Deletion Lifecycle

### 5.1 Retention Schedule
| Data Category | Storage Location | Retention Limit | Destruction Mechanism |
|---|---|---|---|
| **Raw Probe Image Bursts** | Database Queue (`capture_batch_jobs`) | Max 30 Days (default: 24h) | Automated SQL purge via `run_retention_purge()` erasing payloads and nonces. |
| **Enrolled Facial Embeddings** | Encrypted `embedding_records` | Duration of active enrollment | Erased immediately upon graduation or de-enrollment. |
| **Attendance Event Metadata** | `attendance_events` table | Academic record duration (5 years) | Retained as standard non-biometric transcript evidence. |

### 5.2 Certified De-Enrollment Workflow
Upon student request or graduation:
1. Operator triggers `POST /api/v1/admin/students/{student_id}/de-enroll`.
2. All biometric embeddings in `embedding_records` are permanently deleted.
3. Associated Cloudinary / cloud storage face crops are permanently deleted via API.
4. An HMAC-SHA256 authenticated digital **Deletion Certificate** is issued containing:
   - Certificate ID and timestamp
   - Deletion digest
   - Digital signature generated using institutional private key
   - Immutable log in `audit_events` with `action="BIOMETRIC_DE_ENROLLMENT"`

---

## 6. Institutional Sign-Off and Execution Matrix

| Role | Responsibility | Status |
|---|---|:---:|
| **Chief Information Security Officer (CISO)** | Verification of cryptographic storage and key rotation | Pending Institutional Review |
| **University Legal Counsel / DPO** | Privacy compliance and consent disclosure verification | Pending Institutional Review |
| **Dean of Academic Affairs** | Non-biometric alternative parity and student protections | Pending Institutional Review |
| **Engineering Architecture Team** | Implementation of technical safeguards and deletion APIs | **Verified in Code** |
