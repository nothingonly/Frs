#!/usr/bin/env python3
"""Create a private backend .env with fresh credentials; never print secret values."""
from __future__ import annotations

import argparse
import base64
import os
import secrets
import stat
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXAMPLE = BACKEND_DIR / ".env.example"
DESTINATION = BACKEND_DIR / ".env"


def generate_environment() -> str:
    example = EXAMPLE.read_text(encoding="utf-8")
    db_password = secrets.token_urlsafe(32)
    values = {
        "POSTGRES_PASSWORD": db_password,
        "FRS_DATABASE_URL": f"postgresql+psycopg://frs:{db_password}@db:5432/frs",
        "FRS_DEVICE_API_KEYS": secrets.token_urlsafe(40),
        "FRS_ADMIN_API_KEY": secrets.token_urlsafe(40),
        "FRS_JWT_SECRET": secrets.token_urlsafe(48),
        "FRS_DELETION_CERTIFICATE_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii"),
        "FRS_DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
    }
    lines: list[str] = []
    replaced: set[str] = set()
    for line in example.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines.append(f"{key}={values[key]}")
            replaced.add(key)
        else:
            lines.append(line)
    missing = set(values) - replaced
    if missing:
        raise RuntimeError(f".env.example is missing required settings: {', '.join(sorted(missing))}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing .env (the old file is preserved as .env.bak)",
    )
    args = parser.parse_args()

    if DESTINATION.exists():
        if not args.force:
            parser.error(f"{DESTINATION} already exists; refusing to overwrite secrets. Use --force to rotate them.")
        backup = Path(str(DESTINATION) + ".bak")
        if backup.exists():
            parser.error(f"Refusing to overwrite existing backup {backup}; move it securely first.")
        backup.write_bytes(DESTINATION.read_bytes())
        os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)

    content = generate_environment()
    temp_path = Path(str(DESTINATION) + ".tmp")
    temp_created = False
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        temp_created = True
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, DESTINATION)
        os.chmod(DESTINATION, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temp_created and temp_path.exists():
            temp_path.unlink()
    print(f"Created {DESTINATION} with restrictive file permissions. Secret values were not displayed.")
    print("Review the non-secret environment settings and provision verified model artifacts before starting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
