from __future__ import annotations

import base64
from types import SimpleNamespace

import numpy as np
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.database import Base
from app.db.entities import ClassEnrollment, ClassGroup, Department, EmbeddingRecord, Person, Student
from app.security import encrypt_embedding
from app.services.pipeline import AttendancePipeline


def test_class_scoped_gallery_only_contains_active_enrolled_students() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
    settings = Settings(_env_file=None, env="test", data_encryption_key=key)
    pipeline = AttendancePipeline(settings, SimpleNamespace())

    with sessions() as db:
        dept = Department(code="CSE", name="Computer Science")
        db.add(dept)
        db.flush()
        group_a = ClassGroup(department_id=dept.department_id, year_of_study=3, section='A', academic_year='2026-2027', is_active=True)
        group_b = ClassGroup(department_id=dept.department_id, year_of_study=3, section='B', academic_year='2026-2027', is_active=True)
        db.add_all([group_a, group_b])
        db.flush()
        person_a = Person(employee_id="CSE-A-001", full_name="Enrolled A", is_active=True, enrollment_version=1)
        person_b = Person(employee_id="CSE-B-001", full_name="Enrolled B", is_active=True, enrollment_version=1)
        db.add_all([person_a, person_b])
        db.flush()
        student_a = Student(student_number="CSE-A-001", full_name="Enrolled A", person_id=person_a.person_id, is_active=True)
        student_b = Student(student_number="CSE-B-001", full_name="Enrolled B", person_id=person_b.person_id, is_active=True)
        db.add_all([student_a, student_b])
        db.flush()
        db.add_all([
            ClassEnrollment(student_id=student_a.student_id, class_group_id=group_a.class_group_id, status="ACTIVE"),
            ClassEnrollment(student_id=student_b.student_id, class_group_id=group_b.class_group_id, status="ACTIVE"),
        ])
        for person in (person_a, person_b):
            vector = np.asarray([1.0, 2.0, 3.0], dtype=np.float32).tobytes()
            ciphertext, nonce = encrypt_embedding(vector, settings)
            db.add(EmbeddingRecord(
                person_id=person.person_id, enrollment_version=1, recognizer_id='ArcFace',
                model_version='test-model-v1', preprocessing_id='test-preprocess-v1',
                embedding_dim=3, ciphertext=ciphertext, nonce=nonce,
                sample_sha256=(person.employee_id.encode().hex()[:64]).ljust(64, '0'),
                quality_json='{}', accepted=True,
            ))
        db.commit()

        scoped, _count = pipeline._read_gallery(
            db, recognizer_id='ArcFace', model_version='test-model-v1',
            preprocessing_id='test-preprocess-v1', employee_id=None, class_group_id=group_a.class_group_id,
        )
        unscoped, _all_count = pipeline._read_gallery(
            db, recognizer_id='ArcFace', model_version='test-model-v1',
            preprocessing_id='test-preprocess-v1', employee_id=None,
        )
        assert [person.employee_id for person, _vector in scoped] == ["CSE-A-001"]
        assert {person.employee_id for person, _vector in unscoped} == {"CSE-A-001", "CSE-B-001"}

    engine.dispose()
