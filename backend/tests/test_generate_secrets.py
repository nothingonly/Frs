from __future__ import annotations

import base64
from urllib.parse import urlsplit

from scripts.generate_secrets import generate_environment


def parse_env(contents: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in contents.splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_secret_generator_replaces_all_secret_placeholders() -> None:
    values = parse_env(generate_environment())

    assert len(values["POSTGRES_PASSWORD"]) >= 32
    assert values["FRS_DEVICE_API_KEYS"] != values["FRS_ADMIN_API_KEY"]
    assert len(values["FRS_DEVICE_API_KEYS"]) >= 32
    assert len(values["FRS_ADMIN_API_KEY"]) >= 32
    assert len(base64.urlsafe_b64decode(values["FRS_DATA_ENCRYPTION_KEY"])) == 32

    database = urlsplit(values["FRS_DATABASE_URL"])
    assert database.scheme == "postgresql+psycopg"
    assert database.password == values["POSTGRES_PASSWORD"]
    assert "REPLACE_WITH" not in values["FRS_DATABASE_URL"]
    assert "REPLACE_WITH" not in values["FRS_DEVICE_API_KEYS"]
    assert "REPLACE_WITH" not in values["FRS_ADMIN_API_KEY"]
    assert "REPLACE_WITH" not in values["FRS_DATA_ENCRYPTION_KEY"]


def test_each_generation_uses_fresh_credentials() -> None:
    first = parse_env(generate_environment())
    second = parse_env(generate_environment())

    for key in (
        "POSTGRES_PASSWORD",
        "FRS_DEVICE_API_KEYS",
        "FRS_ADMIN_API_KEY",
        "FRS_DATA_ENCRYPTION_KEY",
    ):
        assert first[key] != second[key]
