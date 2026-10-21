# Sprint 4 — Disposable environment and end-to-end runbook

This runbook defines how to execute and record the Sprint 4 vertical slice. It is a procedure, not evidence that any external environment has already been tested. Record results only after execution.

## 0. Safety and prerequisites

Use a **disposable, isolated PostgreSQL database**, a test backend, and an approved Android test device. Never point these commands at production. Before processing face data, obtain institutional authorization, the required notice/consent or other lawful basis, a retention deadline, and a deletion procedure. Use only authorized test participants or an approved test dataset; do not commit face images, embeddings, API keys, database URLs, or private license documents.

Required before a real-model run:

- The exact model artifacts required by the selected configuration, already provisioned from an approved source. Record the SHA-256, source, license/permitted-use decision, model version, preprocessing ID, input/output contract, and reviewer for each artifact. Do not silently download or invent model weights.
- A valid `FRS_DATA_ENCRYPTION_KEY` decoding to 32 bytes, separate high-entropy administrator and kiosk credentials, and secrets stored only in the private environment.
- A reachable test backend using TLS for non-loopback traffic and an Android test build configured for that backend.
- A validation protocol with **disjoint** enrollment, known-probe and unknown-probe captures. Keep raw faces out of logs, CI artifacts and public issues.

Production mode also validates calibration, license attestation, mandatory liveness and configured specialist-model requirements at startup. Do not set `FRS_ENV=production` for this run until every applicable configuration and release gate is genuinely satisfied. A successful development-mode smoke test is not a production acceptance test.

## 1. Apply migrations to the disposable database

Take a recoverable snapshot of the empty/disposable database and record the provider and PostgreSQL version. Apply migrations as a trusted database administrator, in order:

```bash
psql "$FRS_TEST_PSQL_URL" -v ON_ERROR_STOP=1 -f backend/migrations/0001_base_schema.sql
psql "$FRS_TEST_PSQL_URL" -v ON_ERROR_STOP=1 -f backend/migrations/0002_college_domain.sql
psql "$FRS_TEST_PSQL_URL" -v ON_ERROR_STOP=1 -f backend/migrations/0003_capture_batches.sql
```

`FRS_TEST_PSQL_URL` must be a private libpq-compatible PostgreSQL connection URI (for example, `postgresql://...`). The application's SQLAlchemy URL is configured separately as `FRS_DATABASE_URL` and normally uses `postgresql+psycopg://...`. Do not place either URI in the repository, command output, screenshots or a public report.

Verify that the expected schema exists and record the output without credentials:

- `departments`, `class_groups`, `students`, `class_enrollments`
- `attendance_sessions`, `attendance_events`, `audit_events`
- `model_registry`, `embedding_records`, `capture_batch_jobs`
- Unique idempotency constraint and queue/session indexes on `capture_batch_jobs`
- Row-level security enabled as expected by the selected migration, and no unintended broad `anon`/`authenticated` policies.

These migration files do not provide a general reverse-migration script. Test recovery on a disposable snapshot/restore path; do not improvise destructive DDL against a retained environment. Record pre/post migration versions, command exit codes, schema checks, snapshot/restore result and any provider-specific differences.

## 2. Configure and start a test backend

Configure `backend/.env` or the private environment for the backend using the variables documented in `backend/.env.example` and `backend/migrations/README.md`. At minimum confirm:

- `FRS_DATABASE_URL` points only to the disposable database.
- `FRS_DEVICE_API_KEYS` and `FRS_ADMIN_API_KEY` are separate test secrets (and never the same value).
- `FRS_DATA_ENCRYPTION_KEY` is valid; all instances that could process the queue must use the same approved key.
- Model paths point to the provisioned artifacts, and license provenance/threshold calibration is honestly represented. Do not change a calibration flag to `true` without documented calibration evidence.
- The required liveness policy is met by a compatible model if liveness is required.

Install and start using the repository's documented backend workflow; for example, from `backend/` run `python -m pip install -e ".[dev]"`, then `uvicorn app.main:app --host 127.0.0.1 --port 8000` for a loopback-only local test. The FastAPI lifespan loads configured model components and starts the in-process capture worker. Confirm startup logs show the intended test database/model readiness and that `GET /health` (or the actual configured health path) returns the expected response before continuing. Do not expose this development admin console or a loopback-only server to a public network.

In a second shell, set non-exported placeholders for your private terminal session only:

```bash
export FRS_TEST_API=http://127.0.0.1:8000
export FRS_TEST_ADMIN_KEY='REPLACE_WITH_PRIVATE_TEST_ADMIN_SECRET'
export FRS_TEST_DEVICE_KEY='REPLACE_WITH_DIFFERENT_PRIVATE_TEST_DEVICE_SECRET'
```

Use loopback HTTP only when the backend and client run on the same trusted machine. A physical Android device must use a reachable TLS endpoint with the certificate correctly configured; do not reuse the loopback URL on a phone.

## 3. Create one test department, class, student and open session

Use unique test-only codes and identifiers. The examples use `curl` and `jq` to pass generated IDs between requests.

```bash
export ADMIN_AUTH="Authorization: Bearer $FRS_TEST_ADMIN_KEY"
export DEVICE_AUTH="Authorization: Bearer $FRS_TEST_DEVICE_KEY"

curl --fail-with-body -sS -X POST "$FRS_TEST_API/api/v1/admin/college/departments" \
  -H "$ADMIN_AUTH" -H 'Content-Type: application/json' \
  -d '{"code":"TST","name":"Sprint 4 Test Department"}' > /tmp/frs-test-dept.json
export DEPARTMENT_ID="$(jq -r .department_id /tmp/frs-test-dept.json)"

curl --fail-with-body -sS -X POST "$FRS_TEST_API/api/v1/admin/college/class-groups" \
  -H "$ADMIN_AUTH" -H 'Content-Type: application/json' \
  -d "{\"department_id\":\"$DEPARTMENT_ID\",\"year_of_study\":2,\"section\":\"Z\",\"academic_year\":\"2026-2027\"}" \
  > /tmp/frs-test-group.json
export CLASS_GROUP_ID="$(jq -r .class_group_id /tmp/frs-test-group.json)"

curl --fail-with-body -sS -X POST "$FRS_TEST_API/api/v1/admin/college/students" \
  -H "$ADMIN_AUTH" -H 'Content-Type: application/json' \
  -d "{\"student_number\":\"FRS-TEST-001\",\"full_name\":\"Authorized Test Participant\",\"class_group_id\":\"$CLASS_GROUP_ID\"}" \
  > /tmp/frs-test-student.json
export STUDENT_ID="$(jq -r .student_id /tmp/frs-test-student.json)"
export PERSON_ID="$(jq -r .person_id /tmp/frs-test-student.json)"

curl --fail-with-body -sS -X POST "$FRS_TEST_API/api/v1/admin/college/attendance-sessions" \
  -H "$ADMIN_AUTH" -H 'Content-Type: application/json' \
  -d "{\"class_group_id\":\"$CLASS_GROUP_ID\",\"subject_code\":\"TST401\",\"subject_name\":\"Sprint 4 Verification\",\"idempotency_key\":\"s4-test-session-unique-001\"}" \
  > /tmp/frs-test-session.json
export ATTENDANCE_SESSION_ID="$(jq -r .session_id /tmp/frs-test-session.json)"

curl --fail-with-body -sS "$FRS_TEST_API/api/v1/attendance/sessions/open" \
  -H "$DEVICE_AUTH" | jq .
```

Inspect the redacted responses. Confirm the expected session and class group appear in the open-session list. If this is a repeated run, use new unique identifiers or restore the empty database snapshot; do not disable uniqueness constraints to force the setup through.

## 4. Enroll the authorized participant with real model assets

A college student row is **not** biometric enrollment. Enroll the participant through the protected multi-frame enrollment endpoint using at least the configured minimum number of distinct, consented test captures:

```bash
curl --fail-with-body -sS -X POST "$FRS_TEST_API/api/v1/biometrics/enroll/admin" \
  -H "$ADMIN_AUTH" \
  -F "employee_id=FRS-TEST-001" \
  -F "full_name=Authorized Test Participant" \
  -F "department=TST" \
  -F "images=@$FRS_TEST_FRAME_1;type=image/jpeg" \
  -F "images=@$FRS_TEST_FRAME_2;type=image/jpeg" \
  -F "images=@$FRS_TEST_FRAME_3;type=image/jpeg"
```

`FRS_TEST_FRAME_1` to `FRS_TEST_FRAME_3` above are local shell paths to approved test images; set them only in the private shell. Capture multiple genuinely distinct views, not copies of one image. Store no source images in Git. Record the enrollment result, resulting model/config identifiers and sanitized audit reference. If model artifacts, license approval, or threshold calibration are missing, stop this real-model run and record it as **BLOCKED**, not as a recognition failure or pass.

## 5. Submit a session-scoped capture and exercise idempotency

Use the Android kiosk for the definitive device run. For an API contract smoke test, submit a set of distinct approved test frames with a stable key:

```bash
export IDEMPOTENCY_KEY='sprint4-test-batch-0001'

curl --fail-with-body -sS -X POST \
  "$FRS_TEST_API/api/v1/attendance/sessions/$ATTENDANCE_SESSION_ID/batches" \
  -H "$DEVICE_AUTH" \
  -F "idempotency_key=$IDEMPOTENCY_KEY" \
  -F 'punch_type=CHECK_IN' \
  -F 'client_device_id=sprint4-test-kiosk' \
  -F "images=@$FRS_TEST_FRAME_1;type=image/jpeg" \
  -F "images=@$FRS_TEST_FRAME_2;type=image/jpeg" \
  -F "images=@$FRS_TEST_FRAME_3;type=image/jpeg" \
  > /tmp/frs-test-batch.json

export BATCH_ID="$(jq -r .batch_id /tmp/frs-test-batch.json)"
curl --fail-with-body -sS \
  "$FRS_TEST_API/api/v1/attendance/batches/$BATCH_ID" \
  -H "$DEVICE_AUTH" | jq .
```

Poll the same batch ID until it reaches a terminal state; record queue wait and end-to-end time. Repeat the exact request with the same idempotency key and exact same frame bytes: verify the response identifies the same logical batch and no second attendance event is created. Reusing that key with different frames/session/punch/device must return a conflict. Polling another kiosk's batch must be denied.

A success is only valid when the persisted attendance event, audit evidence, and `SUCCEEDED` batch agree. For unknown or ambiguous captures, expect a non-accept terminal outcome and **zero** new attendance rows. A test double can validate worker failure handling but cannot establish biometric recognition performance.

## 6. Exercise negative and recovery cases

Run each case in an isolated test session and record expected/actual HTTP status, batch state, attendance-event count before/after, audit reference, latency, and sanitized logs:

1. Closed session: close it with the admin session-close route, then enqueue using a **new** idempotency key; verify the write is rejected.
2. Different class: create a separate active class enrollment and verify a person enrolled only in that other class cannot match the original session.
3. Unknown identity and ambiguous/conflicting frames: verify no attendance event is created; do not substitute fake model scores.
4. Low-quality/repeated frames and required-liveness unavailable/failed: verify recapture/review/reject as configured, never acceptance without policy-required evidence.
5. Duplicate idempotency key with changed request: expect conflict, no second batch.
6. Worker/API interruption: only in disposable test infrastructure, interrupt processing, restart the worker/backend and verify safe lease recovery; confirm a stale attempt cannot overwrite a newer claim or create duplicate attendance.
7. Credential isolation: an invalid/missing device key cannot enqueue or read a batch; one device cannot read another device's batch; admin-only queue inspection requires the separate administrator key.
8. Retention/deletion: confirm terminal job payload bytes are cleared as expected, and complete the approved cleanup of test templates and any temporary local images/backups.

Do not intentionally expose a public unauthenticated service or conduct presentation-attack testing on a live attendance environment.

## 7. Device-to-admin vertical slice

For the physical-device acceptance run:

1. Configure the Android kiosk against the TLS test backend and authenticate it with its dedicated test device key.
2. Select the open class session, capture a real distinct multi-frame burst, submit once, and poll/resume the same batch after a simulated network interruption.
3. Confirm the worker processes the encrypted queued capture with the selected real model stack and only active enrollments from the session's class.
4. Inspect session, batch, attendance and audit state through the protected admin console/API and the database. Record pseudonymized IDs and redact all bearer tokens, private URLs, student identifiers and biometric material.
5. Repeat with an approved unknown test participant and verify no attendance is recorded.

Record exact Git commit, CI run URLs, DB/provider version and migration evidence, model manifests and hashes, license approvals, preprocessing IDs, Android device/OS/APK hash, configuration revision, capture conditions, dataset sizes/split procedure, correct accept/reject counts, false-accept/false-reject rates, recapture and failure-to-enroll rates, liveness attack types/results where required, and median/p95/max latency. Preserve the raw evidence privately under the institution's approved controls, not in public GitHub.

## 8. Closeout and go/no-go

Complete `docs/SPRINT_04_E2E_EVIDENCE_TEMPLATE.md` from the actual run. Mark every scenario PASS, FAIL, BLOCKED or NOT RUN with a supporting artifact; leave unexecuted scenarios NOT RUN. Never infer biometric accuracy from compilation, mocked/unit tests, a green CI run, or a debug APK.

A limited-test GO decision requires the responsible reviewer to accept the privacy/legal controls, model rights, calibrated thresholds, fail-closed unknown behavior, migration/recovery, credential controls, deletion behavior, and the measured evidence for the exact tested commit and artifacts. Otherwise record NO-GO or NOT EVALUATED, list owners for each blocker, restore/dispose the test database safely, and verify test biometric-data deletion.
