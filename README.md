# FRS — Face Recognition Attendance System

This repository contains the Android kiosk client and a modular FastAPI backend for the FRS V4/V5 architecture. The project is intended to be a real evidence-driven biometric system: **no synthetic identity scores, mocked recognizers, generated attendance events, or silent model-download fallbacks are used**.

## System layout

- \`lib/\`: Flutter Android kiosk, camera capture, settings, client state and REST contract.
- \`backend/app/api/\`: device-authenticated attendance and identification APIs, administrator enrollment, protected roster/attendance/audit/model endpoints.
- \`backend/app/vision/\`: actual SCRFD/ArcFace inference, quality metrics, explicit ONNX adapters for RetinaFace/AdaFace/MobileFaceNet/MiniFASNet/FIQA, and conditional image enhancement.
- \`backend/app/services/pipeline.py\`: frame-burst evaluation, quality routing, version/preprocessing-scoped exact cosine retrieval, calibrated per-model thresholds, temporal evidence, independent secondary recognition, attendance transition/cooldown policy, multi-view enrollment, encrypted embeddings and audit events.
- \`backend/app/benchmark.py\`: real-data benchmark and empirical operating-threshold report.
- \`backend/app/web/\`: browser-based admin console backed exclusively by live API results.
- \`backend/tests/\` and \`test/\`: Python and Flutter tests.

## V4/V5 operating path

The primary fast route is:

\`camera burst → frame gate → SCRFD → deterministic quality → alignment → ArcFace → roster-scoped exact cosine → temporal confirmation → decision\`

Conditional routes can use exposure-specific enhancement, AdaFace for degraded-but-usable frames, RetinaFace recovery after a missed primary detection, MobileFaceNet for independently calibrated checks, FIQA as an additional quality signal, and MiniFASNet when policy requires liveness. Uncertainty can end in recapture, secondary check, review or unknown—not an assumed identity.

## Important: model artifacts are not included

Model weights are external, versioned assets. Do not treat the repository as operational until the actual compatible model artifacts have been provisioned, their full SHA-256 checksums and provenance recorded, licenses and permitted use verified, model-specific thresholds calibrated on representative local validation data, and hardware/runtime behavior tested. The backend intentionally fails startup when required model files or provenance records are missing. It does not silently download unknown weights.

The public InsightFace source package and its pretrained weights have different licensing terms. The commonly distributed pretrained weights are restricted to non-commercial research unless separately licensed. For an attendance deployment, procure model rights suitable for the actual use and record those rights for each exact artifact.

See [backend/model-artifacts/README.md](backend/model-artifacts/README.md) and [backend/README.md](backend/README.md).

## Backend quick start

Requirements: Docker Engine with Compose plugin, plus the separately licensed model artifacts described in the backend model documentation.

1. Enter \`backend/\`.
2. Generate private service secrets: \`python3 scripts/generate_secrets.py\`.
3. Configure \`.env\` with real model paths, compatible artifact sidecars, secret values and deployment settings. The generator does not invent model weights, license provenance, or calibrated thresholds.
4. Provision the exact SCRFD/ArcFace model pack and specialist ONNX artifacts, with per-artifact checksums and contracts.
5. Build and start: \`docker compose up --build -d\`.
6. Inspect startup: \`docker compose logs -f api\`.
7. Read health and model readiness at \`http://127.0.0.1:8000/health\`; ready status is separate from process liveness.
8. Open the admin console at \`http://127.0.0.1:8000/admin\`. Use HTTPS in any non-loopback or production deployment; webcam use in a browser requires a secure context.

Do not set \`FRS_ENV=production\` until model licenses, all required specialist assets, thresholds and liveness have been validated. Production startup intentionally refuses uncalibrated configurations.

## Flutter kiosk

Use the Flutter version selected by the repository's CI workflow. From the project root:

\`\`\`bash
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
\`\`\`

On the Android kiosk, set the backend URL and provision the kiosk **device** bearer credential in Settings. The credential is written through the Android encrypted secure-storage plugin. Administrator enrollment uses a separate admin bearer key, which the server validates; there is no hard-coded local admin PIN.

The Android app captures three real camera exposures in a burst and submits them as repeated \`images\` parts. One photograph is not duplicated to impersonate temporal evidence. HTTP is allowed only for loopback development builds/configuration; use HTTPS for remote networks and production.

## API surface

- \`GET /health/live\` — process liveness.
- \`GET /health\` — operational database/model/status snapshot and readiness flag.
- \`GET /health/ready\` — returns a ready response only when required policy/model/configuration gates pass.
- \`POST /api/v1/attendance/identify\` — automatic 1:N identification from a real frame burst.
- \`POST /api/v1/attendance/verify\` — roster-scoped 1:1 identity verification from a real frame burst.
- \`POST /api/v1/biometrics/enroll/admin\` — separately admin-authenticated multi-view enrollment.
- \`GET /api/v1/admin/people\`, \`GET /api/v1/admin/attendance\`, \`GET /api/v1/admin/audit/{audit_id}\`, \`GET /api/v1/admin/models\` — protected management and evidence APIs.
- \`/docs\` — API schema and interactive docs for developers.

All attendance and enrollment data must be collected and retained under an appropriate legal basis, notice/consent process and organizational retention policy. Raw face crops and embeddings must not be written to ordinary logs.

## Testing and release gates

CI runs Python compilation/lint/unit tests and Flutter analyze/test/debug APK build. A green unit-test workflow validates software contracts; it does **not** prove real biometric accuracy or live-device behavior. Before enabling actual attendance, also run the real-data benchmark with disjoint enrollment, known-probe and unknown-probe splits, evaluate false accepts/false rejects and attack-specific liveness errors, confirm licensing, and test on the target Android camera and backend hardware.

The final application is gated by evidence, as specified in V4/V5—not by whether an API can return HTTP 200.
