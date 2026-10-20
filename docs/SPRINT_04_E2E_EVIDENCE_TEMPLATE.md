# Sprint 4 — End-to-end validation evidence

Use this template only after executing the test. Do not fill missing results with estimates. Redact tokens, private URLs, student identifiers, raw images and biometric embeddings.

## Run identity

- Repository / PR:
- Tested commit SHA:
- Date and operator:
- Environment: local / disposable PostgreSQL / Supabase test / other
- Backend image or package version:
- Admin web commit/build:
- Android device model and OS:
- APK version / SHA-256:
- CI run links:

## Database and migrations

- PostgreSQL version/provider:
- Migration versions present before test:
- Migration versions after test:
- Upgrade output / log reference:
- Constraints and indexes verified:
- Backup/restore or rollback tested:
- Result: PASS / FAIL / NOT RUN
- Notes / evidence link:

## Model provenance and readiness

For every model artifact, record role, filename, source URL or internal provenance, exact SHA-256, version, license and permitted-use decision, preprocessing ID, input/output contract, and who verified it. Do not attach the weight files or private license documents to a public issue.

- Primary detector (SCRFD):
- Recovery detector (RetinaFace, if enabled):
- Primary recognizer (ArcFace):
- Specialist recognizers (if enabled):
- Liveness model and policy (if required):
- Quality model (if enabled):
- Model readiness endpoint result:
- Rights / institutional approval reference:

If any required artifact or rights attestation is absent, the real-model E2E gate is BLOCKED.

## Test data protocol

- Authorization / notice / consent reference:
- Retention and deletion deadline:
- Enrollment set size and collection conditions:
- Known-probe set size and conditions:
- Unknown-probe set size and conditions:
- Confirmation that enrollment and probe captures are disjoint:
- Demographic/subgroup analysis plan, if lawful and appropriate:
- Data custodian and deletion verification:

Do not publish personally identifying details or face images in this report.

## Vertical-slice scenarios

For each scenario record expected result, actual result, attendance-event count before/after, batch ID (pseudonymized), audit reference (redacted), latency, and evidence link.

| Scenario | Expected behavior | Result (PASS/FAIL/NOT RUN) | Evidence / notes |
| --- | --- | --- | --- |
| Create department, class group, student, active enrollment and OPEN session | Records persist and roster is correct | | |
| Enroll test identity with real authorized multi-frame capture | Valid template is persisted; enrollment is auditable | | |
| Android captures a distinct frame burst and submits once | Server accepts a session-scoped batch | | |
| Worker processes a known enrolled student | Correct class-scoped match and permitted attendance transition | | |
| Repeat the same idempotency key | Same logical batch; no duplicate attendance event | | |
| Interrupt network after enqueue and resume | Client retrieves the same batch; no duplicate submission | | |
| Restart API/worker during processing | Lease/retry recovery is safe; stale claim cannot overwrite newer result | | |
| Submit a student not actively enrolled in the session class | No match/attendance for that student | | |
| Unknown person | No attendance event | | |
| Ambiguous identity / conflicting frames | Fail closed or request review according to configured policy | | |
| Low-quality capture | Recapture/failure response; no attendance event | | |
| Liveness unavailable or failed when required | No accepted attendance | | |
| Closed session or invalid check-in/check-out transition | Request rejected; no invalid attendance event | | |
| Admin console inspects session, job and persisted attendance/audit result | Display agrees with database/API state | | |
| Delete test biometric data per approved policy | Source images/templates and queued payloads removed as required | | |

## Measured outcomes

- Known-probe count:
- Correct accept count:
- False reject count / rate:
- Unknown-probe count:
- False accept count / rate:
- Recapture count / rate:
- Failure-to-enroll count / rate:
- Liveness attack types tested and outcomes:
- End-to-end latency: median / p95 / max:
- Queue wait time: median / p95 / max:
- Network / worker failure recovery observations:
- Conditions not tested:

State sample sizes and confidence limitations. Do not claim a low false-accept rate from a tiny or unrepresentative unknown set.

## Security and privacy checks

- Device and admin credentials are distinct:
- TLS used for non-loopback requests:
- No raw face images or full embeddings in logs/traces:
- Admin access and audit permissions checked:
- Upload size, rate limit and replay/idempotency checks:
- Retention/deletion and backup behavior:
- Remaining security findings:

## Final decision

- Software CI: PASS / FAIL / NOT RUN
- Migration and persistence gate: PASS / FAIL / NOT RUN
- Real model readiness / rights gate: PASS / FAIL / BLOCKED
- Biometric accuracy gate: PASS / FAIL / BLOCKED
- Liveness / presentation-attack gate: PASS / FAIL / BLOCKED
- Real-device end-to-end gate: PASS / FAIL / NOT RUN
- Security/privacy gate: PASS / FAIL / BLOCKED
- Overall decision: GO FOR LIMITED TEST / NO-GO / NOT EVALUATED
- Reviewer and date:
- Open blockers / owners:
- Rollback and data-deletion confirmation:

A green unit-test workflow alone is not a GO decision.
