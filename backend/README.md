# FRS Backend

The backend is a FastAPI service that validates multi-frame biometric evidence, runs the configured vision models, applies recognition/attendance policy, and records attendance and audit information. It intentionally requires real model artifacts and refuses to silently download unknown weights.

## Requirements

- Python 3.11 or 3.12 for local Python development (see `pyproject.toml`).
- Docker Engine + Compose plugin for a containerized deployment.
- Compatible, separately provisioned model assets with verified provenance and permitted-use terms.
- A PostgreSQL database for a multi-user deployment. SQLite may be used for isolated development tests.

## First-time setup

From this directory:

```bash
python3 scripts/generate_secrets.py
```

The script creates `.env` with fresh database, device, admin and encryption secrets. It will not overwrite an existing `.env` unless explicitly requested. Keep the file private and out of source control.

Update `.env` with the intended environment, database URL, model root/pack, artifact paths, policy and deployment values. Do not set production mode until every production startup guard is satisfied. The sample configuration is deliberately conservative and does not include model weights.

See [model-artifacts/README.md](model-artifacts/README.md) for artifact layout, provenance sidecars and license checks.

## Run with Docker Compose

```bash
docker compose config
docker compose up --build -d
docker compose logs -f api
```

The API process must bind to an address reachable inside the container network; expose it only through an appropriately configured reverse proxy or restricted host port. Use HTTPS for clients on any non-loopback network. Do not expose the administrative console or API directly to an untrusted network.

Check:

- `GET /health/live`: process is alive.
- `GET /health`: operational health and readiness details.
- `GET /health/ready`: readiness response only when policy and model requirements pass.
- `GET /docs`: generated API schema (disable or restrict in production according to deployment policy).
- `/admin`: browser-based operations console; use a secure browser context and admin credential.

A healthy process is not equivalent to recognition readiness, and a passing unit test is not an accuracy certification.

## Local development and tests

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
python -m compileall -q app tests
ruff check app tests
pytest -q
```

For development that does not require loading a real model pack, unit tests exercise pure contracts, quality measurements, cryptographic behavior, configuration validation and benchmark utilities. A real inference test still requires the actual compatible licensed artifacts and must not be replaced with mock embeddings when claiming biometric acceptance performance.

## Configuration notes

- Device API keys authenticate kiosk attendance endpoints. The administrator key is separate and must not be distributed to kiosks.
- Production JWT signing requires an explicit `FRS_JWT_SECRET` of at least 32 characters, distinct from every admin and device API key.
- `FRS_DELETION_CERTIFICATE_KEY` is URL-safe base64 encoding of a randomly generated 32-byte Ed25519 private-key seed. The generator creates it independently; keep the seed private and pin the corresponding public key out of band for certificate verification.
- Embedding encryption requires a URL-safe base64 key decoding to exactly 32 bytes.
- Model registry records include artifact provenance, checksum, preprocessing and input/output contracts.
- Model-specific similarity thresholds must be calibrated from site-representative validation data.
- If liveness is required, the policy must fail closed when the configured liveness asset is unavailable.
- Enrollment validates all frames before committing a roster/embedding update.
- Attendance state transitions (for example, check-in/check-out sequencing) are enforced server-side.

## Operational obligations

Before real attendance: validate model licenses and hashes; calibrate against disjoint enrollment, known-probe and unknown-probe samples; measure false accepts/rejects; test printed-photo, screen-replay and other relevant attack modes; confirm audit retention and access control; test backup/restore and migration; and verify Android camera performance under actual lighting. Do not put faces, raw images, API keys or full embedding arrays in logs or bug reports.
