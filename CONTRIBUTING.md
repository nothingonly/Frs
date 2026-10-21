# Contributing to FRS

Thank you for your interest in contributing to the Face Recognition Attendance System (FRS).

Because FRS manages biometric identity matching, personal data privacy, and institutional attendance records, correctness, reliability, and fail-closed security contracts take precedence over convenient short-cuts.

---

## Core Engineering Principles

1. **Fail-Closed by Default:** Never convert unknown, ambiguous, low-quality, multi-face, or unverified biometric outcomes into an accepted attendance event.
2. **Zero Synthetic Biometric Bypasses in Production:** Synthetic identities, dummy vectors, mock recognition scores, and automatic passes must never enter production execution paths.
3. **Privacy by Design:** Raw facial imagery and unencrypted biometric vectors must never be committed to source control, written to plain text logs, or exposed to unauthorized clients.
4. **Separation of Concerns:** Maintain strict separation between kiosk terminal credentials, student biometric records, and administrative privilege.

---

## Development Environment Setup

### 1. Python Backend (`backend/`)

Requirements: Python 3.11 or 3.12, virtual environment tool (`venv` or `uv`).

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Linux/macOS
# .venv\Scripts\activate        # On Windows (PowerShell / cmd)

# Upgrade build tools and install package with dev dependencies
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"

# Generate cryptographic keys for local development
python scripts/generate_secrets.py

# Optional: Provision official model weights for real ONNX vision tests
python scripts/provision_models.py

# Run linting, static typecheck, and test suite
ruff check app tests scripts
python -m pytest -v
```

### 2. Next.js 16 Admin Web Console (`admin-web/`)

Requirements: Node.js 20+ and `pnpm`.

```bash
cd admin-web

# Install workspace dependencies
pnpm install

# Configure development environment file
cp .env.example .env.local

# Run linting and TypeScript checks
pnpm lint
pnpm typecheck

# Verify production build prerendering
pnpm build

# Start local development server with Turbopack
pnpm dev
# Console available at http://localhost:3000
```

### 3. Flutter Android Kiosk (`/`)

Requirements: Flutter 3.x+ with Android SDK tools.

```bash
# From repository root
flutter pub get

# Check code formatting and static analysis
dart format --output=none --set-exit-if-changed lib test
flutter analyze --fatal-infos

# Run widget and contract test suite
flutter test

# Build debug APK
flutter build apk --debug
```

---

## CI Quality Gates & Standards

Every pull request is automatically validated by three dedicated GitHub Actions workflows:

1. **`backend.yml` (Python Backend Checks):**
   - Syntax and compilation: `python -m compileall app tests`
   - Linting: `ruff check app tests scripts`
   - Test suite: `pytest -v` (135 passed / 6 skipped on hosted runners without binary weights; 141 passed locally)
2. **`admin-web.yml` (Admin Web Checks):**
   - ESLint: `pnpm lint`
   - Strict TypeScript check: `pnpm typecheck`
   - Next.js production build: `pnpm build` (11 static routes)
3. **`flutter.yml` (Flutter Kiosk Quality Gate):**
   - Code formatting: `dart format --set-exit-if-changed`
   - Static analysis: `flutter analyze --fatal-infos`
   - Test suite: `flutter test` (29 passed)
   - Android debug APK build: `flutter build apk --debug`

---

## Pull Request Guidelines

1. **Scope:** Keep pull requests focused on a single feature, bug fix, or documentation enhancement.
2. **Conventional Commits:** Use standard conventional commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
3. **Regression Tests:** Every bug fix, endpoint addition, or logic change must include automated unit/integration tests verifying both expected success and fail-closed edge cases.
4. **Database Changes:** Schema modifications must include a corresponding ordered migration script under `backend/migrations/` and an accompanying model test.
5. **No Model Weight Commits:** Binary ONNX model files (`*.onnx`) and sample biometric photo datasets must never be committed directly to Git. Use provisioning scripts and reference checksums.
6. **Description:** Describe the problem being solved, the technical implementation, manual or automated verification performed, and any environment variable changes introduced.
