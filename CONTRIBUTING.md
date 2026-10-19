# Contributing

Thank you for improving FRS. Because changes can affect identity matching, biometric privacy and payroll-adjacent attendance records, correctness and fail-closed behavior are more important than accepting a convenient success path.

## Development setup

### Python backend

```bash
cd backend
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
python -m compileall -q app tests
ruff check app tests
pytest -q
```

### Flutter kiosk

Use the stable Flutter toolchain used by the CI workflow:

```bash
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze --fatal-infos
flutter test --reporter expanded
flutter build apk --debug
```

## Change requirements

- Add regression tests for every bug fix and boundary behavior.
- Do not add synthetic identity scores, fake attendance events, silent weight downloads or mocked biometric results to the production path.
- Never turn unknown, ambiguous, low-quality, liveness-unavailable or invalid-transition outcomes into acceptance.
- Keep device authentication and admin authentication separate.
- Changes to persisted fields must include a migration and an upgrade test.
- Changes to model contracts must update sidecar examples and document normalization, color order, tensor layout, output type and preprocessing.
- Do not log raw face images, credentials or full embeddings.
- Document any new environment variable, API contract or operator action.
- Keep licenses and data-use rights explicit; do not check model weights into the repository without review.

## Pull requests

Include the problem being solved, a concise design note, tests run with results, migration or environment-impact details, security/privacy implications and any outstanding limitations. Green unit CI is not a claim of biometric accuracy or deployment readiness.
