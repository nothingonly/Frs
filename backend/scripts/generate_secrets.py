from __future__ import annotations

import argparse
import base64
import secrets
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate private FRS backend secrets from .env.example.")
    parser.add_argument("--force", action="store_true", help="Replace an existing .env file; all previous secrets will change.")
    args = parser.parse_args()

    backend = Path(__file__).resolve().parents[1]
    template = backend / ".env.example"
    target = backend / ".env"
    if target.exists() and not args.force:
        parser.error(f"{target} already exists. Back it up and use --force only when you intend to rotate every generated secret.")
    if not template.is_file():
        parser.error(f"Template not found: {template}")

    postgres_password = secrets.token_hex(32)
    device_key = secrets.token_urlsafe(48)
    admin_key = secrets.token_urlsafe(48)
    while secrets.compare_digest(device_key, admin_key):
        admin_key = secrets.token_urlsafe(48)
    encryption_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")

    content = template.read_text(encoding="utf-8")
    content = content.replace("POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_POSTGRES_PASSWORD", f"POSTGRES_PASSWORD={postgres_password}")
    content = content.replace(
        "FRS_DATABASE_URL=postgresql+psycopg://frs:REPLACE_WITH_RANDOM_POSTGRES_PASSWORD@db:5432/frs",
        f"FRS_DATABASE_URL=postgresql+psycopg://frs:{postgres_password}@db:5432/frs",
    )
    content = content.replace(
        "FRS_DEVICE_API_KEYS=REPLACE_WITH_RANDOM_DEVICE_KEY_AT_LEAST_32_CHARS",
        f"FRS_DEVICE_API_KEYS={device_key}",
    )
    content = content.replace(
        "FRS_ADMIN_API_KEY=REPLACE_WITH_DIFFERENT_RANDOM_ADMIN_KEY_AT_LEAST_32_CHARS",
        f"FRS_ADMIN_API_KEY={admin_key}",
    )
    content = content.replace(
        "FRS_DATA_ENCRYPTION_KEY=REPLACE_WITH_BASE64_URLSAFE_32_RANDOM_BYTES",
        f"FRS_DATA_ENCRYPTION_KEY={encryption_key}",
    )
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    print(f"Created {target} with mode 0600.")
    print("Keep this file private. Do not paste its contents into chat or commit it.")
    print("Model paths and model licenses must be configured and verified separately.")
    print("Threshold calibration remains disabled until you run the documented real-data benchmark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
