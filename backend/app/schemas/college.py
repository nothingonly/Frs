from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DepartmentCreate(StrictPayload):
    code: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=160)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class ClassGroupCreate(StrictPayload):
    department_id: str = Field(min_length=1, max_length=36)
    year_of_study: int = Field(ge=1, le=4)
    section: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    academic_year: str = Field(min_length=9, max_length=9, pattern=r"^\d{4}-\d{4}$")

    @field_validator("section")
    @classmethod
    def normalize_section(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("academic_year")
    @classmethod
    def validate_academic_year(cls, value: str) -> str:
        start, end = (int(part) for part in value.split("-"))
        if end != start + 1:
            raise ValueError("academic_year must be consecutive, e.g. 2026-2027")
        return value


class StudentCreate(StrictPayload):
    student_number: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._/-]+$")
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    class_group_id: str | None = Field(default=None, max_length=36)

    @field_validator("student_number")
    @classmethod
    def normalize_student_number(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("email must be a valid email address")
        return normalized.lower()


class AttendanceSessionCreate(StrictPayload):
    class_group_id: str = Field(min_length=1, max_length=36)
    subject_name: str = Field(min_length=1, max_length=160)
    subject_code: str | None = Field(default=None, max_length=40)
    starts_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("starts_at")
    @classmethod
    def require_timezone_for_explicit_start(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("starts_at must include a timezone offset")
        return value

    @field_validator("subject_code")
    @classmethod
    def normalize_subject_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None
