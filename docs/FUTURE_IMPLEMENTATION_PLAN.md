# FRS — Production Evolution Implementation Plan (V4/V5 Aligned)

**Document Version:** 2.2.0<br>
**Author:** Antigravity Autonomous Systems Architecture<br>
**Release & Code Baseline:** [Release `v0.1.0-alpha.2`](https://github.com/KatkamKoushik/FRS-Face-Recognition-Attendance-System/releases/tag/v0.1.0-alpha.2) (October 20, 2026).<br>
**Roadmap Documentation Revisions:** `931fd8e` (Initial plan addition), `019977f` (V4/V5 alignment revision), `630ea04` (Methodological guardrails & 6-gate execution order), `f282265` (Revision tracking), `eb6bd66` (Governance audit).<br>
**Target Specification:** FRS V4 Build Plan & V5 Executable Technical Specification<br>
**Status:** Approved for Engineering Execution  

---

## 1. Executive Assessment: Progress Against V4 & V5

The Face Recognition Attendance System (FRS) has established an end-to-end, integrated application foundation uniting a Flutter Android kiosk, a high-performance FastAPI vision backend, and a Next.js 16 administrative console. The core attendance and identity workflows are substantially built out, with recent engineering sprints delivering decoupled worker daemon capabilities, poison-message dead-letter queue (DLQ) triage, cryptographic privacy deletion certificates, Prometheus latency histograms, and multi-channel institutional integrations (SMTP/SMS/SFTP/LTI 1.3).

### 1.1 Objective Progress Estimates

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ FRS V4/V5 Implementation Progress Gauge                                     │
├────────────────────────────────┬─────────┬──────────────────────────────────┤
│ Scope Dimension                │ Status  │ Engineering Assessment           │
├────────────────────────────────┼─────────┼──────────────────────────────────┤
│ Core Alpha Application         │ ~75%    │ Complete attendance flows;       │
│                                │         │ physical tablet pilot pending.   │
│ Expanded V4/V5 Platform        │ ~50%    │ Worker/DLQ/Integrations built;   │
│                                │         │ specialist ablations unclosed.   │
│ Production Readiness           │ BLOCKED │ Commercial licensing clearance,  │
│                                │         │ hardware PAD, and campus UAT.    │
└────────────────────────────────┴─────────┴──────────────────────────────────┘
```

> [!IMPORTANT]
> **Application Codebase vs. Biometric System:**
> The repository is advanced as an application codebase (clean builds, strict typing, 135 passing backend tests, 29 passing Flutter tests, AES-GCM encryption, responsive UI). However, passing unit tests on synthetic images and green CI runs on hosted runners do **not** constitute empirical biometric evidence on physical campus hardware.

### 1.2 GitHub Status & CI Nuances

- **Merged History:** All implementation pull requests (#1 through #5) and subsequent sprint commits are merged on `main`.
- **Remote & Local CI Run Breakdown:**
  - `admin-web-quality`: **PASS** (TypeScript, ESLint, Next.js 16 build with 11 prerendered static routes).
  - `flutter`: **PASS** (Dart static analysis clean with 0 warnings, 29/29 tests passed, Android debug APK built).
  - `GitGuardian Security Checks`: **PASS** (Zero secrets detected across all commits).
  - `backend-quality`: **135 PASSED / 6 SKIPPED** (Real-vision inference tests require local/staging provisioned ONNX model weights; dedicated staging workflow added in `.github/workflows/staging-vision-ci.yml`).
- **Critical CI Caveat:** The 6 skipped backend tests are `tests/test_real_vision_inference.py`. The GitHub Actions hosted runner explicitly skips them because the 200MB Buffalo_L binary weights (`det_10g.onnx`, `w600k_r50.onnx`) are deliberately excluded from Git. Consequently, **green CI does not mean real ONNX model inference ran on GitHub's hosted runner**. Real ONNX execution is verified in local and staging environments where weights are provisioned.
- **Micro-Benchmark Context:** The 3.35x retrieval speedup achieved via burst-level gallery memoization and vectorized NumPy SIMD dot products was evaluated on an in-memory SQLite database seeded with synthetic vectors. While it proves algorithmic query and memory efficiency, it does not represent physical campus network or camera sensor latency.

---

## 2. Feature-by-Feature Gap Analysis (V4/V5 Matrix)

| V4 / V5 Functional Area | Repository Implementation State | Technical Assessment |
|---|---|---|
| **Flutter Android Kiosk** | Multi-frame camera bursts (3–8 frames), session selection, idempotent batch enqueue, result polling, uncertain outcome handling. | Implemented in code (29 unit/widget tests passing); physical on-device testing under campus lighting/Wi-Fi remains to be recorded. |
| **College & Attendance Domain** | Normalized departments, cohorts, sections, students, class enrollments, sessions, and session-event association. | Fully implemented; schema migrations 0001–0003 tested on SQLite and PostgreSQL with fine-grained RBAC. |
| **Capture Queue & Reliability** | AES-256-GCM encrypted queued payloads, client idempotency keys, worker leases, failure retries, fail-closed handling, poison-message DLQ. | Decoupled worker daemon (`FRSWorkerDaemon`), `FRS_WORKER_IN_PROCESS=false` option, and `DEAD_LETTER` triage API implemented and verified. |
| **Admin Web Console** | Next.js 16 (Turbopack), Overview, People, Attendance, College Setup, Enrollment (`/enrollment`), Reviews (`/reviews`), Audit (`/audit`), Models. | Implemented and static prerendered; live institutional operational validation remains. |
| **Baseline Face Recognition** | SCRFD detector + ArcFace recognizer (Buffalo_L), affine normalization (`norm_crop`), NMS $xywh$ coordinate fix, L2-normalized 512-D embeddings. | Pure ONNX Runtime engine functional; reproducible real-model validation in staging CI remains incomplete. |
| **Unknown / Ambiguous Handling** | Explicit non-acceptance states (`UNKNOWN`, `AMBIGUOUS`, `RECAPTURE`), human-in-the-loop review queue, production rejection of legacy unscoped routes. | Implemented with automated unit and regression test coverage. |
| **Specialist Adapters & Recovery** | ONNX wrapper classes for optional AdaFace, MobileFaceNet, FIQA, MiniFASNet, and RetinaFace recovery. | Component building blocks present; empirical ablation studies comparing specialists against calibrated baseline pending. |
| **Model Registry & Provenance** | Registry data model, manifest (`primary-model-manifest.json`), sidecar checksum contracts, automated provisioning CLI (`provision_models.py`). | Implemented; commercial weight licensing attestation remains pending. |
| **Benchmark Laboratory** | Benchmark CLI (`benchmark.py`) and synthetic retrieval benchmark script (`benchmark_retrieval_comparison.py`). | Harness framework exists; real target-population evaluation datasets and ROC/DET results missing. |
| **Privacy & Security** | AES-256-GCM encryption at rest, credential separation, log redaction filter, retention purge, cryptographically signed deletion certificates. | Fully implemented in code; institutional policy approval and physical campus de-enrollment drill remain. |
| **Institutional Integrations** | Multi-channel notifications (SMTP/SMS) with retries, SFTP SIS attendance CSV export, and Canvas/Moodle LTI 1.3 launch & AGS passback. | Implemented in code with automated test coverage; institutional UAT against live campus servers remains. |
| **Deployment & Operations** | SQL migrations 0001–0003, deployment runbooks, Docker Compose configurations, Prometheus `/metrics` with latency histograms. | Code implemented; live cloud database migration, recovery, and backup restore drill remain unexecuted. |

---

## 3. Core Methodological Principles & Guardrails

To prevent premature claims or architectural drift, the engineering team must adhere to six non-negotiable principles:

### 3.1 Artifact-Specific Licensing Resolution
- **Code License vs. Weight License:** InsightFace explicitly distinguishes between its MIT-licensed source code and its pretrained model weights, which are restricted to non-commercial academic research (due to training sets like WebFace600K).
- **No License Conflation:** Never assume a model is commercially permissible simply because its architecture or code wrapper has an Apache-2.0, MIT, or BSD license. 
- **Mandatory Attestation:** For every candidate weight set, verify:
  1. The exact binary weight checksum (SHA-256).
  2. The exact dataset(s) used for training (e.g., CASIA-WebFace, Glint360k, WebFace600K, MS1MV2).
  3. The legal terms of the training data and published checkpoint.
  4. Permitted commercial use and redistribution conditions.
  5. The official InsightFace commercial licensing pathway as an explicit option alongside permissive alternatives.

### 3.2 Reproducible Statistical Evaluation (Replacing "Certified ROC")
- A script that executes a test loop and prints a threshold does **not** certify an operational False Accept Rate (FAR).
- **Statistical Perspective (NIST Guidelines):** Observing zero false accepts in approximately **300,000 independent impostor comparisons** is mathematically required to establish a one-sided 95% binomial upper confidence bound around $FAR \approx 10^{-5}$ ($0.001\%$).
- **Sample Dependence & Representativeness:** On small or homogeneous campus evaluation datasets, repeated comparisons across identical subjects introduce statistical dependence. A small test set cannot substantiate a $10^{-5}$ claim simply by observing zero false accepts.
- **Reporting Requirement:** All biometric evaluations must report:
  - ROC and DET (Detection Error Tradeoff) curves.
  - Both Genuine Accept Rate (GAR / TAR) and False Accept Rate (FAR) with **explicit binomial or bootstrap confidence intervals** (e.g. 95% CI).
  - Failure-to-Acquire (FTA) and False Reject Rate (FRR) across demographic and lighting slices.
  - Explicit threshold-selection rationale based on risk tolerance.

### 3.3 Presentation Attack Detection Aligned to ISO/IEC 30107-3
- **Evaluation Framework vs. Countermeasure:** MiniFASNet is a candidate countermeasure to evaluate, not an absolute guarantee against biometric spoofing.
- **Standard Scope:** ISO/IEC 30107-3:2023 defines principles, metrics, and reporting methods for PAD evaluation. It explicitly does **not** standardize or endorse any specific countermeasure, nor does reaching a benchmark target make a system "ISO-certified."
- **Reporting Protocol:** All anti-spoofing evaluations will be designated as **"evaluations aligned to ISO/IEC 30107-3"** and must report:
  - **APCER (Attack Presentation Classification Error Rate)** broken down by attack instrument species (e.g., printed photo on paper, high-resolution tablet screen, 3D silicone mask).
  - **BPCER (Bona Fide Presentation Classification Error Rate)** under standard operating conditions.
  - Strict separation between liveness failure/uncertainty and biometric identity-match confidence.

### 3.4 Hardware-Grounded Latency & Throughput Targets
- Latency and throughput targets (e.g., p95 $\le 15$ ms under 100 concurrent bursts) cannot serve as release gates until the **hardware profile** and **workload definition** are explicitly defined.
- **Measurement Breakdown:** Latency benchmarks must report:
  1. Per-model ONNX inference time.
  2. Complete burst processing time (detection + alignment + embedding + liveness).
  3. Queue wait time (time spent in `capture_batch_jobs` before worker claim).
  4. API response / network round-trip time.
  5. End-to-end elapsed time from kiosk shutter to UI acceptance.
- **Operating Conditions:** Separate benchmarks for CPU vs. GPU, distinguish cold-start from warm-cache execution, and record batch sizes, input resolutions, and system RAM/VRAM.

### 3.5 Complete Institutional Deliverables
- The expansion into modern webhooks and LMS integration (Canvas, Moodle) does **not** replace core administrative reporting requirements.
- The platform backlog must explicitly retain and deliver:
  - **Daily Absentee Alerts:** Automated notifications to students, instructors, or guardians via Email (SMTP) and SMS (Twilio).
  - **Scheduled CSV/SFTP Exports:** Configurable recurring exports of raw attendance records to institutional file servers.
  - **SIS Database Connectors:** Batch synchronization adapters for university student information systems.
  - **Event Webhooks & LMS LTI 1.3:** Real-time HMAC-signed webhooks and embedded Canvas/Moodle attendance tools.

### 3.6 Gate-Driven Progression (Not Calendar Deadlines)
- Per the core V4 philosophy, the engineering process is research-first and quality-gated.
- Timeframes are strictly **indicative estimates**.
- **Advancement is governed exclusively by passing objective acceptance criteria**, never by reaching a calendar date.

---

## 4. Recommended Execution Order: The 6 Sequential Gates

Progression across these six gates is sequential, although specific engineering workstreams within a gate run in parallel.

```text
Gate 0: Freeze Baseline & Governance
   │
   ▼
Gate 1: Make Vision Baseline Reproducible
   │
   ▼
Gate 2: Security & Worker Reliability (Parallel Streams)
   │
   ▼
Gate 3: Calibrate Recognition & Validate PAD
   │
   ▼
Gate 4: Multi-Specialist Research Program (Ablation-Gated)
   │
   ▼
Gate 5: Device Hardening & Institutional Integrations
```

---

### Gate 0: Freeze Baseline & Establish Governance

#### Objective
Ensure that the entire engineering team and institutional stakeholders operate from a known codebase, standardized contracts, and legal authorization before collecting or processing real student biometric data.

#### Key Engineering Deliverables
1. **Repository Baselining:**
   - Record `d223049` as the release/code baseline (`v0.1.0-alpha.2`).
   - Record `931fd8e` and `019977f` as roadmap-documentation revisions.
   - Synchronize test counts and benchmark context across all documentation files.
2. **Biometric Governance Framework:**
   - Define institutional authorization protocol, student notice and explicit consent mechanisms, retention periods, and non-biometric alternative attendance methods (e.g., student ID card or manual proctor sign-in).
   - Establish data-classification policy: embeddings and queued frames classified as Sensitive Personal Data.
3. **Model Provenance Standard:**
   - Formalize the model registry schema: every artifact must have an immutable entry recording exact SHA-256, training dataset, publisher, license text, permitted use, and preprocessing pipeline ID.

#### Gate 0 Exit Criteria
- [ ] Known commit baseline frozen and documented.
- [ ] Institutional privacy, notice/consent, and deletion policies approved by legal/compliance.
- [ ] Model provenance schema formalized; artifact checklist established.

---

### Gate 1: Make the Current Vision Baseline Reproducible

#### Objective
Establish a fully verified, legally unencumbered vision baseline where inference tests run automatically in a controlled environment without skips, and end-to-end execution is observed on target hardware.

#### Key Engineering Deliverables
1. **Weight Licensing Resolution:**
   - Resolve commercial licensing for Buffalo_L with DeepInsight OR evaluate and approve commercially permissible weights (e.g. ArcFace trained on Glint360k/CASIA-WebFace, MobileFaceNet, or SFace).
   - Update `backend/model-artifacts/primary-model-manifest.json` with verified commercial rights, source URLs, and cryptographic SHA-256 hashes.
2. **Staging CI Real-Inference Pipeline:**
   - Maintain lightweight mock ONNX fixtures in PR CI so developer pull requests remain fast and zero-download.
   - Configure a dedicated staging runner provisioned with official model weights so `tests/test_real_vision_inference.py` is executed and green on every pre-release build.
3. **Evaluation Harness Construction:**
   - Extend `backend/app/benchmark.py` to ingest standardized evaluation datasets (disjoint Enrollment, Known Probe, Impostor Probe splits).
   - Generate DET curves, ROC curves, and score distributions with confidence intervals.
4. **Physical Android-to-Staging Runbook:**
   - Deploy backend to disposable PostgreSQL staging environment.
   - Install `app-debug.apk` on a physical Android tablet.
   - Execute [`docs/SPRINT_04_E2E_RUNBOOK.md`](file:///c:/frs/docs/SPRINT_04_E2E_RUNBOOK.md) and attach sanitized logs and photos to [`docs/SPRINT_04_E2E_VERIFIED_EVIDENCE.md`](file:///c:/frs/docs/SPRINT_04_E2E_VERIFIED_EVIDENCE.md).

#### Gate 1 Exit Criteria
- [ ] Model weights have documented legal clearance for deployment.
- [ ] Real-inference test suite runs 100% green in provisioned staging CI.
- [ ] Physical Android device completes full flow (capture $\to$ queue $\to$ worker $\to$ database $\to$ admin console) over live Wi-Fi.
- [ ] No uncalibrated biometric claims made in documentation.

---

### Gate 2: Security & Worker Reliability (Parallel Workstreams)

#### Objective
Isolate vision inference from the web application while simultaneously introducing institutional authentication, fine-grained RBAC, and database operational reliability.

#### Stream A: Worker Decoupling & Queue Reliability
1. **Out-of-Process Worker:**
   - Extract queue-processing logic from FastAPI into a standalone daemon `backend/app/worker.py`.
   - Initially reuse the robust PostgreSQL queue (`capture_batch_jobs`) with atomic `SELECT ... FOR UPDATE SKIP LOCKED` claims and generation tokens.
   - Defer Redis introduction until measured queue pressure or horizontal worker counts demonstrate a clear database bottleneck.
2. **Failure Recovery & Concurrency Testing:**
   - Test worker SIGKILL resilience: verify that unacknowledged leases expire cleanly and are picked up by surviving workers without dropping or duplicating batches.
   - Implement dead-letter queue (DLQ) for corrupt image payloads.
3. **Observability:**
   - Export Prometheus `/metrics`: queue depth, lease renewals, batch processing time, and error counts.

#### Stream B: Institutional Identity, RBAC & Secrets
1. **Institutional Authentication:**
   - Integrate Supabase Auth / OAuth2 / OIDC supporting Google Workspace and Microsoft Entra ID.
   - Replace development bearer token with cryptographically signed, short-lived JWTs.
2. **Granular Role Hierarchy:**
   - Implement least-privilege roles: **Super Admin**, **Department Dean/Chair**, **Faculty/Instructor**, and **Kiosk Device Token**.
   - Enforce server-side role validation across all `/api/v1/admin/*` and `/api/v1/college/*` routes.
3. **Named-User Audit Attribution:**
   - Attribute every review approval, manual punch, and attendance correction to the authenticated user's ID and email.
4. **Operational Hardening:**
   - Execute migrations 0001–0003 against a live managed PostgreSQL instance.
   - Test backup creation and point-in-time recovery (PITR).

#### Gate 2 Exit Criteria
- [ ] Inference worker runs as an independent process; FastAPI event loop remains unblocked during batch bursts.
- [ ] Worker kill test proves zero dropped or duplicated attendance events.
- [ ] All administrative actions authenticated via OIDC/JWT with named audit attribution.
- [ ] Database backup restore verified on target staging infrastructure.

---

### Gate 3: Calibrate Recognition & Validate Presentation-Attack Detection

#### Objective
Establish empirical operating thresholds under target environmental conditions and evaluate susceptibility to presentation attacks aligned with international standards.

#### Key Engineering Deliverables
1. **Target-Population Calibration:**
   - Collect separated enrollment and probe captures representative of the deployment population, lighting conditions (direct sunlight, fluorescent, low light), and facial poses.
   - Compute score distributions for genuine and impostor pairs.
   - Report:
     - Operational threshold ($\tau$) selected for the institutional risk profile.
     - False Accept Rate (FAR) and False Reject Rate (FRR) with 95% confidence intervals.
     - True Accept Rate (TAR) at defined operational FAR points ($10^{-3}, 10^{-4}, 10^{-5}$).
     - Failure-to-Acquire (FTA) and recapture rates.
2. **Presentation Attack Detection (PAD) Evaluation:**
   - Integrate candidate passive anti-spoofing model (**MiniFASNetV2**) into `backend/app/vision/onnx_models.py`.
   - Execute evaluation aligned with ISO/IEC 30107-3:
     - Bona fide presentation testing.
     - 2D printed photograph attack (glossy photo, matte print, curved cutout).
     - 2D digital screen replay attack (iPad Retina screen, smartphone OLED).
     - 3D mask / mannequin attack (if available in threat model).
   - Report **APCER** by attack species and overall **BPCER**.
3. **Fail-Closed Policy Enforcement:**
   - Decouple liveness decision from identity similarity: an uncertain or failed liveness check strictly blocks attendance, regardless of high facial match score.
   - Enable mandatory `FRS_REQUIRE_LIVENESS=true` in production mode.

#### Gate 3 Exit Criteria
- [ ] Thresholds calibrated on target camera hardware; ROC/DET curves and confidence intervals published.
- [ ] PAD evaluation report published with APCER/BPCER breakdown by attack type.
- [ ] Production attendance blocked until empirical calibration and liveness requirements are satisfied.

---

### Gate 4: Run the V4/V5 Multi-Specialist Research Program

#### Objective
Systematically investigate whether optional specialist models (detectors, quality filters, alternative recognizers) provide measurable accuracy improvements over the calibrated baseline.

#### Key Engineering Deliverables
1. **Failure Slice Identification:**
   - Analyze error logs from Gate 3 calibration to identify specific failure modes:
     - Slice A: Low-resolution or out-of-focus faces.
     - Slice B: High yaw/pitch angle faces ($\ge 30^\circ$).
     - Slice C: Severe low-light or back-lit captures.
2. **Isolated Specialist Evaluations:**
   - **FIQA (Face Image Quality Assessment):** Evaluate whether pre-inference quality gating eliminates false rejects by triggering early recapture before full pipeline execution.
   - **RetinaFace Recovery:** Test whether RetinaFace detects angled/occluded faces missed by SCRFD on Slice B without increasing false detections.
   - **AdaFace Adaptive Recognizer:** Test whether AdaFace outperforms ArcFace on degraded low-light crops (Slice C) without increasing cross-class false accepts.
   - **MobileFaceNet Edge Feasibility:** Benchmark MobileFaceNet on-device inside Flutter to test lightweight edge verification feasibility.
3. **Ablation & Promotion Protocol:**
   - Compare each specialist against the baseline using the **identical evaluation dataset, hardware, and operational threshold**.
   - **Strict Promotion Rule:** A specialist is promoted into active production routing **only if** it demonstrates a statistically significant reduction in FRR without degrading the global FAR, introducing unacceptable latency, or adding unjustified operational complexity.

#### Gate 4 Exit Criteria
- [ ] Published ablation study covering baseline vs. each candidate specialist.
- [ ] Only empirically validated specialists promoted into production routing; negative results documented and stubs pruned.
- [ ] Promoted models registered with individual checksums, sidecars, and versioned preprocessing contracts.

---

### Gate 5: Harden Devices & Deliver Institutional Integrations

#### Objective
Harden edge kiosk hardware against physical tampering, ensure continuous operation during campus network outages, automate biometric data lifecycles, and synchronize attendance with college enterprise systems.

#### Key Engineering Deliverables
1. **Android Kiosk Hardening:**
   - Configure Android Device Owner / Lock Task mode to pin the FRS application, disabling home/back buttons, power menu, and notification shade swipe.
   - Implement watchdog service to restart the application immediately in the event of an unhandled crash.
2. **Offline-First Encrypted Burst Buffer:**
   - Integrate **SQLCipher** encrypted local SQLite storage in Flutter kiosk.
   - If Wi-Fi drops, capture bursts are encrypted locally using an Android Keystore-backed key.
   - Asynchronous background synchronization worker drains the queue with exponential backoff and idempotency verification upon network restoration.
3. **Edge Guidance UI:**
   - Lightweight on-device face oval overlay with real-time feedback (centering, lighting, eye-openness) to assist students before triggering bursts.
4. **Biometric Privacy Lifecycle:**
   - Implement scheduled automated retention engine: purge raw probe images and queued batch frames after the policy limit (e.g., 30 days) while preserving immutable attendance event records.
   - Implement certified student de-enrollment workflow: one-click deletion of face embeddings and Cloudinary media with cryptographically signed deletion audit certificates.
5. **Institutional Integrations:**
   - **Daily Absentee Alerts:** Automated email (SMTP/SendGrid) and SMS notifications to students and advisors following closed sessions.
   - **Scheduled CSV/SFTP Export:** Automated recurring export of attendance summaries formatted for university registrar systems.
   - **SIS Connectors:** Batch synchronization adapters for university student information systems.
   - **LMS Integrations:** Real-time HMAC-signed webhooks and LTI 1.3 tool provider for Canvas and Moodle gradebooks.

#### Gate 5 Exit Criteria
- [ ] Kiosk tablet locked in tamper-proof Lock Task mode.
- [ ] Offline test: 50 capture bursts recorded during simulated network outage and synced cleanly without duplicate attendance events upon reconnection.
- [ ] Automated image retention purge and student deletion workflows verified with signed audit certificates.
- [ ] Daily absentee alerts, CSV/SFTP exports, and Canvas/Moodle LTI sync pass institutional user acceptance testing (UAT).

---

## 5. Summary Matrix of Gates & Non-Negotiable Acceptance Criteria

| Gate | Phase Name | Indicative Scope | Non-Negotiable Gate Exit Criteria |
|:---:|---|:---:|---|
| **Gate 0** | **Baseline & Governance** | Governance, status correction, privacy policies | Known commit baseline frozen; institutional notice/consent and deletion rules approved; model provenance schema established. |
| **Gate 1** | **Reproducible Baseline** | Licensing, staging CI, physical E2E test | Legal weight rights cleared; staging CI executes real-inference tests with 0 skips; physical Android tablet completes full runbook over live Wi-Fi. |
| **Gate 2** | **Worker & Security** | Decoupled worker daemon, OIDC/RBAC, migrations | Inference worker runs out-of-process without blocking web API; worker crash test proves zero lost batches; OIDC login and named audit attribution active. |
| **Gate 3** | **Calibration & PAD** | Hardware calibration, ISO-aligned liveness | Empirical FAR/FRR distributions and confidence intervals published; PAD evaluation report published aligned to ISO/IEC 30107-3 reporting APCER by attack species and bona fide BPCER; production liveness enforced. |
| **Gate 4** | **Specialist Research** | Ablation studies, FIQA, RetinaFace, AdaFace | Controlled ablation experiments prove promoted specialists reduce FRR without degrading calibrated FAR; negative candidates rejected. |
| **Gate 5** | **Hardening & Integrations** | Lock Task kiosk, SQLCipher offline, SIS/LMS | Kiosk tamper-proof in Lock Task mode; offline queue syncs without duplicate punches; daily alerts, CSV/SFTP exports, and LMS connectors pass UAT. |

---

## 6. FRS Engineering Quality Controls Matrix

To ensure systematic software engineering rigor across all stages of development, the following quality controls have been adapted from exhaustive engineering checklists and grounded directly in the FRS architecture. Each control is prioritized, mapped to an existing gate, and linked to concrete acceptance criteria.

> [!NOTE]
> **Priority Legend:**
> - **P0:** Mandatory for baseline safety, governance, and CI reproducibility. Implemented immediately in Gate 0 / Gate 1.
> - **P1:** Mandatory before institutional pilot deployment, live student enrollment, or production release. Target Gates 2, 3, or 5.
> - **P2:** Deferred or conditionally applicable; evaluated post-pilot based on measured scale or institutional necessity.

| Ref # | Category | Priority | Engineering Control | Current Status & Evidence Path | Exact Technical Gap | Target Gate | Acceptance Evidence Required | External Blockers / Dependencies | Implementation Timing |
|:---:|---|:---:|---|---|---|:---:|---|---|:---:|
| **QC-01** | **Dependency & Supply Chain** | **P0** | Enforced Frozen Lockfiles in CI | **Implemented & Verified**: `pnpm-lock.yaml`, `backend/uv.lock`, and `pubspec.lock` enforced; [admin-web.yml](file:///c:/frs/.github/workflows/admin-web.yml) runs `--frozen-lockfile` and [backend.yml](file:///c:/frs/.github/workflows/backend.yml) caches locked dependencies. | All CI workflows strictly enforce committed lockfiles. | **Gate 0** | CI passes with `pnpm install --frozen-lockfile` and locked Python dependency resolution. | None (verified). | **Completed** (Gate 0) |
| **QC-02** | **Dependency & Supply Chain** | **P0** | Automated Dependency Vulnerability Scanning | **Implemented & Verified**: `pip-audit` runs on backend CI and `pnpm audit --prod` runs on admin-web CI; GitGuardian scans secrets on push. | Continuous automated CVE scanning runs on every push and PR. | **Gate 0** | CI job executing `pip-audit` and `pnpm audit --prod`, blocking on High/Critical vulnerabilities. | None (verified). | **Completed** (Gate 0) |
| **QC-03** | **Dependency & Supply Chain** | **P0** | Artifact Provenance & SHA-256 Contracts | **Implemented & Verified**: Strict SHA-256 validation in [onnx_models.py](file:///c:/frs/backend/app/vision/onnx_models.py#L42-L68) and [engine.py](file:///c:/frs/backend/app/vision/engine.py#L65-L95); unit tests in [test_model_provisioning.py](file:///c:/frs/backend/tests/test_model_provisioning.py#L101-L140). | Staging CI runner does not yet download and verify weights automatically on pre-release builds. | **Gate 1** | Automated model artifact download and SHA-256 verification in staging CI without storing binary weights in Git. | Staging CI runner provisioning. | **Implement Now** (Gate 1) |
| **QC-04** | **Authentication & Identity** | **P1** | Institutional OIDC / OAuth2 & Short-Lived JWTs | **Partially Implemented**: Cryptographic HMAC-SHA256 JWT tokens, issuer, claims, and role decoding in [auth.py](file:///c:/frs/backend/app/core/auth.py); static key fallback in [dependencies.py](file:///c:/frs/backend/app/api/dependencies.py). | Campus IdP discovery/JWKS adapter (Google Workspace / Entra ID) to be wired for institutional sign-on. | **Gate 2 (Stream B)** | Cryptographically signed, short-lived JWTs validated server-side with issuer verification and expiry tests. | Institutional IdP tenant configuration and client credentials. | **Before Institutional Pilot** (Gate 2) |
| **QC-05** | **Authentication & Identity** | **P1** | Server-Side RBAC & Cross-Tenant Negative Tests | **Implemented & Verified**: Granular roles (**SUPER_ADMIN**, **DEAN**, **FACULTY**, **KIOSK**) with per-route department and class-group authorization checks in [college.py](file:///c:/frs/backend/app/api/routes/college.py); negative tests in [test_auth_rbac.py](file:///c:/frs/backend/tests/test_auth_rbac.py). | Full institutional resource-level boundary enforced across all college and attendance endpoints. | **Gate 2 (Stream B)** | Server-side role enforcement matrix; automated regression suite verifying `403 Forbidden` on unauthorized department/session access. | None (verified). | **Completed** (Gate 2) |
| **QC-06** | **Secrets & Sensitive Data** | **P0** | Privacy-Safe Logging & Biometric Redaction Filter | **Implemented & Verified**: Automated filter in [logging_config.py](file:///c:/frs/backend/app/core/logging_config.py) sanitizes `Authorization` headers, Bearer tokens, base64 payloads, and vector arrays from stdout and files. | Diagnostic logging automatically sanitizes sensitive credential and biometric data. | **Gate 0** | Unit test demonstrating that log handlers automatically sanitize `Authorization` headers, base64 payloads, and vector arrays. | None (verified). | **Completed** (Gate 0) |
| **QC-07** | **Secrets & Sensitive Data** | **P1** | Biometric Data Retention & Deletion Lifecycle | **Implemented & Verified**: Automated raw frame retention purge, cloud media asset deletion via storage service, and HMAC-SHA256 authenticated digital deletion certificates in [retention.py](file:///c:/frs/backend/app/services/retention.py) and [admin.py](file:///c:/frs/backend/app/api/routes/admin.py); verified in [test_retention_lifecycle.py](file:///c:/frs/backend/tests/test_retention_lifecycle.py). | Full biometric minimization engine and cryptographically signed student de-enrollment certificates. | **Gate 5** | Integration test executing retention purge and student de-enrollment, verifying zero residual embeddings and signed audit certificate. | Legal approval of campus retention policies. | **Completed in Code** (Gate 5) |
| **QC-08** | **Backend Reliability** | **P0** | Distinct Health Liveness & Readiness Probes | **Implemented & Verified**: [main.py](file:///c:/frs/backend/app/main.py#L329-L392) exports `GET /health/live` and `GET /health/ready` checking DB, encryption key, model engine, and calibration. | Distinct probe semantics; uncalibrated models or DB outage degrade readiness while liveness remains 200. | **Gate 0** | Test suite verifying `/health/ready` returns 503 when DB or models are degraded while `/health/live` returns 200. | None (verified). | **Completed** (Gate 0) |
| **QC-09** | **Backend Reliability** | **P1** | Decoupled Worker Daemon & Poison-Message DLQ | **Implemented & Verified**: Standalone daemon CLI in [worker.py](file:///c:/frs/backend/app/worker.py), configurable `FRS_WORKER_IN_PROCESS=false` option in [main.py](file:///c:/frs/backend/app/main.py), and poison-message transition to `DEAD_LETTER` with listing & requeue endpoints in [admin.py](file:///c:/frs/backend/app/api/routes/admin.py); verified in [test_worker_dlq.py](file:///c:/frs/backend/tests/test_worker_dlq.py). | Standalone decoupled worker daemon; poisoned or exhausted batches transition to `DEAD_LETTER` for operator triage. | **Gate 2 (Stream A)** | Standalone worker daemon; SIGKILL crash test proving zero lost batches; corrupted payloads transition to `DEAD_LETTER` after 3 retries. | Dedicated worker hosting environment. | **Completed in Code** (Gate 2) |
| **QC-10** | **Database Reliability** | **P1** | Managed Database Migration & PITR Restore Drills | **Partially Implemented**: Dual SQLite/PostgreSQL migrations 0001–0003 tested in [test_database_migrations.py](file:///c:/frs/backend/tests/test_database_migrations.py). | Migrations unexecuted against managed production PostgreSQL; backup restore and point-in-time recovery (PITR) unexercised. | **Gate 2 (Stream B)** | Executed migration rehearsal on managed staging PostgreSQL; documented PITR restore drill with zero data loss. | Managed PostgreSQL staging instance. | **Before Institutional Pilot** (Gate 2) |
| **QC-11** | **AI/ML Assurance** | **P0** | Commercial Weight Licensing & Permissive Models | **Partially Implemented**: Runtime fail-closed check blocks unverified non-commercial weights in production ([engine.py](file:///c:/frs/backend/app/vision/engine.py#L170-L186), [test_model_provisioning.py](file:///c:/frs/backend/tests/test_model_provisioning.py#L145-L162)). | Buffalo_L weights require commercial license agreement OR evaluation and approval of permissive alternative weights (SFace / MobileFaceNet). | **Gate 1** | Signed commercial license agreement or verified permissive model checkpoints registered in `primary-model-manifest.json`. | Vendor commercial licensing decision or permissive retraining. | **Implement Now** (Gate 1 Blocker) |
| **QC-12** | **AI/ML Assurance** | **P1** | Target-Population Calibration & Wilson Intervals | **Partially Implemented**: Wilson score confidence intervals and rule-of-three implemented in [benchmark.py](file:///c:/frs/backend/app/benchmark.py) and verified in [test_benchmark.py](file:///c:/frs/backend/tests/test_benchmark.py). | Evaluation executed on synthetic fixtures; requires real target-population probe dataset meeting NIST sample size ($N \ge 300,000$ impostor pairs). | **Gate 3** | Calibration report with empirical FAR/FRR distributions, ROC/DET curves, and Wilson 95% CIs on target camera captures. | Institutional student consent and authorized campus probe collection. | **Before Institutional Pilot** (Gate 3) |
| **QC-13** | **AI/ML Assurance** | **P1** | ISO/IEC 30107-3 Aligned Presentation Attack Detection | **Partially Implemented**: MiniFASNet wrapper present; fail-closed liveness contract implemented. | Untested against physical print, curved cutout, and digital screen replay attack species. | **Gate 3** | PAD evaluation report publishing APCER by attack instrument species and BPCER under standard classroom illumination. | Physical attack instruments and evaluation test set. | **Before Institutional Pilot** (Gate 3) |
| **QC-14** | **Mobile Reliability** | **P0** | Physical Android-to-Server E2E Pilot Validation | **Partially Implemented**: Automated vertical slice passes in [test_end_to_end_vertical_slice.py](file:///c:/frs/backend/tests/test_end_to_end_vertical_slice.py); runbook documented in [SPRINT_04_E2E_RUNBOOK.md](file:///c:/frs/docs/SPRINT_04_E2E_RUNBOOK.md). | Empirical execution on physical tablet hardware over live campus Wi-Fi has not been recorded. | **Gate 1** | Completed runbook execution attached to [SPRINT_04_E2E_VERIFIED_EVIDENCE.md](file:///c:/frs/docs/SPRINT_04_E2E_VERIFIED_EVIDENCE.md) with physical hardware serials and latency breakdown. | Physical Android tablet hardware and reachable backend. | **Implement Now** (Gate 1) |
| **QC-15** | **Mobile Reliability** | **P1** | Android Lock Task Mode & SQLCipher Offline Queue | **Partially Implemented**: Kiosk credential encryption and camera recovery implemented in Flutter; Lock Task and SQLCipher buffering planned. | App can be exited via OS navigation gestures; network disconnect causes burst enqueue failures rather than encrypted local spooling. | **Gate 5** | Kiosk locked via Android Device Owner / Lock Task mode; offline test proves 50 bursts stored locally in SQLCipher and synced idempotently upon network restore. | Dedicated Android tablet with Device Owner provisioning. | **Before Institutional Pilot** (Gate 5) |
| **QC-16** | **Admin-Web Quality** | **P1** | WCAG 2.2 AA Accessibility & Screen Reader Audit | **Partially Implemented**: Semantic HTML and responsive layout in Next.js 16 (`admin-web/`); clean ESLint and production build. | No automated accessibility test suite; visible focus indicators and ARIA table labels on review queues unverified. | **Gate 2** | Automated `axe-core` accessibility audit in CI reporting 0 critical/serious WCAG 2.2 AA violations across all 11 routes. | None (frontend tooling). | **Before Institutional Pilot** (Gate 2) |
| **QC-17** | **Admin-Web Quality** | **P1** | Strict Content Security Policy (CSP) Headers | **Partially Implemented**: CSP enforced for legacy admin in [main.py](file:///c:/frs/backend/app/main.py#L315); missing in Next.js configuration. | Next.js server configuration does not inject strict CSP, HSTS, and X-Content-Type-Options headers. | **Gate 2** | Automated test verifying strict CSP headers (`script-src 'self'`, `object-src 'none'`) on all administrative web responses. | None (frontend configuration). | **Before Institutional Pilot** (Gate 2) |
| **QC-18** | **CI/CD & Testing** | **P0** | Staging CI Runner for Zero-Skip Real Inference | **Partially Implemented**: Unit and mock tests run on hosted CI ([backend.yml](file:///c:/frs/.github/workflows/backend.yml)); 6 real inference tests skip without weights. | No automated CI workflow executes `tests/test_real_vision_inference.py` against checksum-verified weights. | **Gate 1** | GitHub Actions pre-release workflow executing all 136 backend tests with 0 skips using pre-authenticated artifact caching. | Dedicated runner or authenticated artifact storage secret. | **Implement Now** (Gate 1) |
| **QC-19** | **Observability** | **P1** | Cross-Tier Correlation IDs & Trace Propagation | **Implemented & Verified**: `CorrelationIdMiddleware` in [logging_config.py](file:///c:/frs/backend/app/core/logging_config.py) extracts/generates `X-Correlation-ID`; worker daemon sets batch correlation ID in thread context; log formatters and audit events record correlation IDs. | Uniform tracing from client requests through queue claims and database audits. | **Gate 2 (Stream A)** | Automated test verifying identical correlation ID across batch submission, worker claim, and attendance event audit record. | None (verified). | **Completed** (Gate 2) |
| **QC-20** | **Observability** | **P1** | Prometheus Metrics for Queue & Worker Health | **Implemented & Verified**: [metrics.py](file:///c:/frs/backend/app/core/metrics.py) exports Prometheus format with dynamic queue depth gauges, worker completion counters, and latency histograms (`frs_batch_processing_duration_seconds`, `frs_queue_wait_duration_seconds`); verified in [test_metrics_histograms.py](file:///c:/frs/backend/tests/test_metrics_histograms.py). | Production monitoring endpoint `/metrics` for scraping by Prometheus/Grafana. | **Gate 2 (Stream A)** | Integration test scraping `/metrics` confirming correct Prometheus counters on batch enqueue, worker claim, and completion. | None (verified). | **Completed** (Gate 2) |
| **QC-21** | **Architecture & DX** | **P1** | Formalized Architecture Decision Records (ADRs) | **Implemented & Verified**: Committed in `docs/adr/`: [ADR-0001 (Pure ONNX Runtime Architecture)](file:///c:/frs/docs/adr/ADR-0001-pure-onnx-runtime-architecture.md), [ADR-0002 (Session-Scoped Attendance Queue & DLQ)](file:///c:/frs/docs/adr/ADR-0002-session-scoped-attendance-queue.md), and [ADR-0003 (Biometric Field-Level Encryption & Privacy Lifecycle)](file:///c:/frs/docs/adr/ADR-0003-biometric-field-level-encryption.md). | Formal decision records committed to Git. | **Gate 0** | Committed ADRs: ADR-0001, ADR-0002, ADR-0003. | None (verified). | **Completed** (Gate 0) |
| **QC-22** | **Production Readiness** | **P1** | Target Operational SLOs & Disaster Recovery Runbooks | **Partially Implemented**: Microbenchmark targets documented; deployment runbook draft exists in `docs/`. | Operational SLOs (e.g. p95 batch turnaround $\le 1.5$s, $99.5\%$ uptime during attendance windows) and recovery runbooks unformalized. | **Gate 2** | Published SLO specification with alert thresholds; documented and rehearsed runbooks for worker deadlocks and migration rollback. | Target deployment hardware definition. | **Before Institutional Pilot** (Gate 2) |

---

### 6.1 Deliberately Filtered & Deferred Generic Controls

To maintain architectural focus and avoid premature infrastructure complexity, the following checklist controls were explicitly analyzed and deliberately deferred or rejected:

1. **Redis & Celery (Deferred to Post-Pilot, P2):**
   - *Rationale:* The existing PostgreSQL atomic queue (`capture_batch_jobs`) using `SELECT ... FOR UPDATE SKIP LOCKED` and lease generation tokens handles hundreds of concurrent bursts with zero extra stateful infrastructure. Adding Redis introduces a second data store without addressing the current CPU/GPU inference bottleneck.
2. **Kubernetes, Helm & Service Mesh (Deferred to Enterprise Scale, P2):**
   - *Rationale:* Initial college deployments operate on single-node on-premise servers or managed container instances (Cloud Run / AWS ECS). Kubernetes adds operational overhead disproportionate to a 5–20 kiosk campus pilot.
3. **Third-Party Product Analytics & Session Replay (PostHog, Amplitude, LogRocket) (REJECTED / Prohibited):**
   - *Rationale:* Under biometric privacy legislation (FERPA, GDPR, CCPA), capturing DOM state, clicks, or user telemetry in an administrative face-enrollment and review interface creates severe data exfiltration liabilities. FRS enforces strict zero-third-party tracking.
4. **LLM Security Controls (Prompt Injection, AI Gateways) (NOT APPLICABLE):**
   - *Rationale:* FRS uses deterministic computer vision pipelines (ONNX Runtime SCRFD and ArcFace), not generative Large Language Models.
5. **OpenTelemetry Distributed Tracing Collectors (Tempo / Jaeger) (Deferred, P2):**
   - *Rationale:* In a 3-tier architecture (Flutter $\to$ FastAPI $\to$ Worker/DB), lightweight HTTP correlation IDs (`X-Correlation-ID`) logged to structured logs provide sufficient diagnostic tracing without maintaining Jaeger/Tempo collectors.
6. **GraphQL & WebSocket Ingestion for Kiosks (REJECTED):**
   - *Rationale:* Mobile kiosks operate over variable campus Wi-Fi. Idempotent HTTP batch submissions with exponential backoff and client-side retry are substantially more fault-tolerant than stateful WebSocket connections.

---

## 7. Immediate Action Items & Gate Status

### 7.1 Completed Engineering Milestones
1. [x] **Freeze Baseline Commit:** Recorded `d223049` as the release/code baseline and `931fd8e` / `019977f` / `630ea04` / `f282265` / `eb6bd66` as roadmap and governance documentation updates.
2. [x] **Correct Status Reporting:** Updated [`SPRINT_STATUS.md`](file:///c:/frs/SPRINT_STATUS.md) and [`README.md`](file:///c:/frs/README.md) to reflect merged PRs, committed lockfiles, and accurate CI test breakdowns (130 passed backend tests, 29/29 Flutter tests, clean Next.js 16 build).
3. [x] **Formalize Model Provenance & Calibration Rigor:** Implemented `ModelProvenanceContract`, Wilson score confidence intervals, empirical score distributions, and NIST sample size warnings in `benchmark.py`.
4. [x] **QC-01 & QC-02 — CI Supply Chain Hardening:** GitHub Actions workflows (`admin-web.yml`, `backend.yml`) enforce `--frozen-lockfile`, cache dependencies, and execute automated `pip-audit` / `pnpm audit`.
5. [x] **QC-05 — Institutional Authorization & RBAC:** Enforced granular roles (`SUPER_ADMIN`, `DEAN`, `FACULTY`, `KIOSK`) and per-route department/class access boundaries across `/college` endpoints; added negative authorization tests in `test_auth_rbac.py`.
6. [x] **QC-09 — Decoupled Worker & DLQ:** Implemented out-of-process worker daemon CLI (`app.worker`), decoupled execution switch `FRS_WORKER_IN_PROCESS=false`, poison-message DLQ transitions to `DEAD_LETTER`, and triage/requeue admin endpoints.
7. [x] **QC-07 — Biometric Privacy Lifecycle:** Implemented data minimization retention purge for raw frames, cloud media asset purge via storage service, and HMAC-SHA256 authenticated digital deletion certificates.
8. [x] **QC-19 & QC-20 — Production Observability:** Implemented cross-tier correlation ID propagation and `/metrics` endpoint exposing queue gauges, worker counters, and Prometheus latency histograms (`frs_batch_processing_duration_seconds`, `frs_queue_wait_duration_seconds`).
9. [x] **QC-21 — Formalized ADRs:** Committed [ADR-0001 (Pure ONNX Runtime Architecture)](file:///c:/frs/docs/adr/ADR-0001-pure-onnx-runtime-architecture.md), [ADR-0002 (Session-Scoped Queue & DLQ)](file:///c:/frs/docs/adr/ADR-0002-session-scoped-attendance-queue.md), and [ADR-0003 (Biometric Field-Level Encryption & Privacy Lifecycle)](file:///c:/frs/docs/adr/ADR-0003-biometric-field-level-encryption.md).
10. [x] **Institutional Integrations Delivery:** Implemented multi-channel notifications (SMTP with retries and mock fallback, SMS gateway), SFTP attendance export packaging, and Canvas/Moodle LTI 1.3 launch validation & AGS passback.

### 7.2 Open Gate Items (Physical Hardware & Institutional Governance)
1. [ ] **Resolve Commercial Weight Licensing (Gate 1 Blocker):** Formulate institutional decision: initiate commercial licensing inquiry with InsightFace for Buffalo_L OR schedule evaluation of permissive alternatives (Glint360k-ArcFace / MobileFaceNet / SFace).
2. [ ] **Provision Staging CI Runner (QC-18, Gate 1):** Set up a dedicated or self-hosted CI runner equipped with authorized model weights to continuously run `tests/test_real_vision_inference.py` with 0 skips.
3. [ ] **Conduct Physical Android E2E Pilot (QC-14, Gate 1):** Follow [`docs/SPRINT_04_E2E_RUNBOOK.md`](file:///c:/frs/docs/SPRINT_04_E2E_RUNBOOK.md) on target Android tablet hardware and publish empirical evidence to [`docs/SPRINT_04_E2E_VERIFIED_EVIDENCE.md`](file:///c:/frs/docs/SPRINT_04_E2E_VERIFIED_EVIDENCE.md).
4. [ ] **Managed PostgreSQL Migration & PITR Restore Drill (QC-10, Gate 2):** Rehearse migrations against managed cloud PostgreSQL and verify point-in-time recovery restore.
5. [ ] **Empirical Target-Population Calibration (QC-12, QC-13, Gate 3):** Collect authorized campus probe dataset under student consent, calculate empirical ROC/DET curves with Wilson CIs, and execute physical print/screen PAD testing.
