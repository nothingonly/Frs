from __future__ import annotations

import base64
import os
import uuid
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.database import Base
from app.db.entities import (
    ClassEnrollment,
    ClassGroup,
    Department,
    EmbeddingRecord,
    Person,
    Student,
)
from app.security import encrypt_embedding
from app.services.pipeline import AttendancePipeline, _normalise


@pytest.fixture
def test_setup():
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    settings = Settings(
        env="development",
        data_encryption_key=key,
        database_url="sqlite:///:memory:",
    )
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return settings, Session


def test_gallery_cache_exact_cosine_equivalence(test_setup):
    """Prove that vectorized matrix dot product produces identical scores to un-vectorized _cosine."""
    settings, Session = test_setup
    pipeline = AttendancePipeline(settings, vision=None)

    rec_id = "ArcFace"
    version = "v1"
    prep_id = "ArcFace:v1:norm_crop:original"

    rng = np.random.default_rng(123)
    query = _normalise(rng.standard_normal(512).astype(np.float32))

    with Session() as db:
        for i in range(10):
            pid = str(uuid.uuid4())
            person = Person(
                person_id=pid, employee_id=f"EMP{i:03d}", full_name=f"Person {i}",
                is_active=True, enrollment_version=1,
            )
            db.add(person)
            db.flush()
            vec = _normalise(rng.standard_normal(512).astype(np.float32))
            ct, nonce = encrypt_embedding(vec.tobytes(), settings)
            db.add(EmbeddingRecord(
                person_id=pid, enrollment_version=1, recognizer_id=rec_id,
                model_version=version, preprocessing_id=prep_id,
                embedding_dim=512, ciphertext=ct, nonce=nonce,
                sample_sha256="sha", quality_json="{}", accepted=True,
            ))
        db.commit()

        # Run with cache
        cache = {}
        cached_top, count, _ = pipeline._retrieve(
            db, query, recognizer_id=rec_id, model_version=version,
            preprocessing_id=prep_id, gallery_cache=cache,
        )

        # Run un-cached
        uncached_top, _, _ = pipeline._retrieve(
            db, query, recognizer_id=rec_id, model_version=version,
            preprocessing_id=prep_id, gallery_cache=None,
        )

        assert len(cached_top) == len(uncached_top)
        for c_cand, u_cand in zip(cached_top, uncached_top):
            assert c_cand.person_id == u_cand.person_id
            assert np.isclose(c_cand.similarity, u_cand.similarity, atol=1e-6)

        # Verify cache has exactly one entry
        cache_key = (rec_id, version, prep_id, None, None)
        assert cache_key in cache
        cached_profiles, row_count = cache[cache_key]
        assert len(cached_profiles) == 10
        assert row_count == 10


def test_gallery_cache_boundary_isolation_by_class_group(test_setup):
    """Prove that data cannot leak across different class groups."""
    settings, Session = test_setup
    pipeline = AttendancePipeline(settings, vision=None)

    rec_id = "ArcFace"
    version = "v1"
    prep_id = "ArcFace:v1:norm_crop:original"
    rng = np.random.default_rng(456)

    with Session() as db:
        dept = Department(department_id=str(uuid.uuid4()), code="CS", name="Computer Science", is_active=True)
        db.add(dept)
        group_a = ClassGroup(
            class_group_id=str(uuid.uuid4()), department_id=dept.department_id,
            academic_year="2026-2027", year_of_study=1, section="A", is_active=True,
        )
        group_b = ClassGroup(
            class_group_id=str(uuid.uuid4()), department_id=dept.department_id,
            academic_year="2026-2027", year_of_study=1, section="B", is_active=True,
        )
        db.add_all([group_a, group_b])
        db.flush()

        # Student in Group A
        p_a = Person(person_id=str(uuid.uuid4()), employee_id="STU_A", full_name="Student A", is_active=True, enrollment_version=1)
        s_a = Student(student_id=str(uuid.uuid4()), student_number="STU_A", full_name="Student A", person_id=p_a.person_id, is_active=True)
        enr_a = ClassEnrollment(enrollment_id=str(uuid.uuid4()), student_id=s_a.student_id, class_group_id=group_a.class_group_id, status="ACTIVE")

        # Student in Group B
        p_b = Person(person_id=str(uuid.uuid4()), employee_id="STU_B", full_name="Student B", is_active=True, enrollment_version=1)
        s_b = Student(student_id=str(uuid.uuid4()), student_number="STU_B", full_name="Student B", person_id=p_b.person_id, is_active=True)
        enr_b = ClassEnrollment(enrollment_id=str(uuid.uuid4()), student_id=s_b.student_id, class_group_id=group_b.class_group_id, status="ACTIVE")

        db.add_all([p_a, s_a, enr_a, p_b, s_b, enr_b])
        db.flush()

        # Add embeddings
        for p in (p_a, p_b):
            vec = _normalise(rng.standard_normal(512).astype(np.float32))
            ct, nonce = encrypt_embedding(vec.tobytes(), settings)
            db.add(EmbeddingRecord(
                person_id=p.person_id, enrollment_version=1, recognizer_id=rec_id,
                model_version=version, preprocessing_id=prep_id,
                embedding_dim=512, ciphertext=ct, nonce=nonce,
                sample_sha256="sha", quality_json="{}", accepted=True,
            ))
        db.commit()

        # Query Group A
        query = _normalise(rng.standard_normal(512).astype(np.float32))
        shared_cache = {}
        top_a, count_a, _ = pipeline._retrieve(
            db, query, recognizer_id=rec_id, model_version=version,
            preprocessing_id=prep_id, class_group_id=group_a.class_group_id,
            gallery_cache=shared_cache,
        )
        assert len(top_a) == 1
        assert top_a[0].employee_id == "STU_A"
        assert count_a == 1

        # Query Group B with same cache
        top_b, count_b, _ = pipeline._retrieve(
            db, query, recognizer_id=rec_id, model_version=version,
            preprocessing_id=prep_id, class_group_id=group_b.class_group_id,
            gallery_cache=shared_cache,
        )
        assert len(top_b) == 1
        assert top_b[0].employee_id == "STU_B"
        assert count_b == 1

        # Check cache has two distinct keys
        key_a = (rec_id, version, prep_id, None, group_a.class_group_id)
        key_b = (rec_id, version, prep_id, None, group_b.class_group_id)
        assert key_a in shared_cache
        assert key_b in shared_cache
        assert shared_cache[key_a][0][0][0].employee_id == "STU_A"
        assert shared_cache[key_b][0][0][0].employee_id == "STU_B"


def test_gallery_cache_freshness_after_revocation(test_setup):
    """Prove that student deactivation or template update is immediately reflected across requests."""
    settings, Session = test_setup
    pipeline = AttendancePipeline(settings, vision=None)

    rec_id = "ArcFace"
    version = "v1"
    prep_id = "ArcFace:v1:norm_crop:original"
    rng = np.random.default_rng(789)

    with Session() as db:
        p = Person(person_id=str(uuid.uuid4()), employee_id="EMP_REVOKE", full_name="Revocable", is_active=True, enrollment_version=1)
        db.add(p)
        db.flush()
        vec = _normalise(rng.standard_normal(512).astype(np.float32))
        ct, nonce = encrypt_embedding(vec.tobytes(), settings)
        db.add(EmbeddingRecord(
            person_id=p.person_id, enrollment_version=1, recognizer_id=rec_id,
            model_version=version, preprocessing_id=prep_id,
            embedding_dim=512, ciphertext=ct, nonce=nonce,
            sample_sha256="sha", quality_json="{}", accepted=True,
        ))
        db.commit()

        # Request 1: Burst 1
        burst_1_cache = {}
        top1, count1, _ = pipeline._retrieve(
            db, vec, recognizer_id=rec_id, model_version=version,
            preprocessing_id=prep_id, gallery_cache=burst_1_cache,
        )
        assert count1 == 1
        assert top1[0].employee_id == "EMP_REVOKE"

        # Now revoke person
        p.is_active = False
        db.commit()

        # Request 2: Burst 2 (new burst has fresh cache, as created per identify request)
        burst_2_cache = {}
        top2, count2, _ = pipeline._retrieve(
            db, vec, recognizer_id=rec_id, model_version=version,
            preprocessing_id=prep_id, gallery_cache=burst_2_cache,
        )
        assert count2 == 0
        assert len(top2) == 0
