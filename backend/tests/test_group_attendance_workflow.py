from __future__ import annotations

from collections.abc import Generator

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import admin_actor, session_actor
from app.api.routes.attendance import router as attendance_router
from app.api.routes.college import router as college_router
from app.core.config import Settings
from app.database import Base, get_db
from app.db.entities import (
    AttendanceEvent,
    EmbeddingRecord,
    Student,
)
from app.security import encrypt_embedding
from app.services.pipeline import AttendancePipeline
from app.vision.engine import GroupFaceObservation


class MockVisionEngine:
    def __init__(self):
        self.recognizer_id = "ArcFace"
        self.recognizer_version = "mock-arcface-v1"
        self.pipeline_version = "frs-vision:mock-v1"
        self.mock_faces: list[GroupFaceObservation] = []

    def set_mock_detections(self, faces: list[GroupFaceObservation]):
        self.mock_faces = faces

    def detect_all_faces(self, image_bytes: bytes) -> list[GroupFaceObservation]:
        return self.mock_faces


@pytest.fixture
def test_setup() -> Generator[tuple[TestClient, sessionmaker[Session], MockVisionEngine], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(college_router)
    app.include_router(attendance_router)

    import base64
    valid_enc_key = base64.urlsafe_b64encode(b"01234567890123456789012345678901").decode("ascii")
    settings = Settings(
        secret_key="test-secret-key-32-bytes-long!",
        data_encryption_key=valid_enc_key,
        env="testing",
        similarity_threshold=0.60,
    )
    mock_vision = MockVisionEngine()
    pipeline = AttendancePipeline(settings=settings, vision=mock_vision)
    app.state.settings = settings
    app.state.pipeline = pipeline

    def override_db() -> Generator[Session, None, None]:
        session = testing_sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[admin_actor] = lambda: "administrator:test"
    app.dependency_overrides[session_actor] = lambda: "faculty:test_prof"

    with TestClient(app) as client:
        yield client, testing_sessions, mock_vision
    engine.dispose()


def test_academic_departments_seed_and_create(test_setup):
    client, sessions, _ = test_setup
    # Seed the 7 required departments
    res = client.post("/api/v1/admin/college/departments/seed-defaults")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "CSE" in data["seeded"]
    assert "CSD" in data["seeded"]
    assert "MECH" in data["seeded"]
    assert "CIVIL" in data["seeded"]
    assert "IT" in data["seeded"]
    assert "ECE" in data["seeded"]
    assert "EEE" in data["seeded"]

    # Verify listing
    res2 = client.get("/api/v1/admin/college/departments")
    assert res2.status_code == 200
    depts = {d["code"]: d for d in res2.json()["items"]}
    assert len(depts) >= 7
    assert "CSE" in depts and "CSD" in depts and "ECE" in depts


def test_specific_class_and_lab_sessions(test_setup):
    client, sessions, _ = test_setup
    client.post("/api/v1/admin/college/departments/seed-defaults")

    depts = {d["code"]: d for d in client.get("/api/v1/admin/college/departments").json()["items"]}
    cse_id = depts["CSE"]["department_id"]

    # 1. Create a Specific Class Group
    res_cg = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": cse_id,
        "year_of_study": 3,
        "section": "A",
        "academic_year": "2026-2027",
        "semester": 5,
        "is_lab": False,
    })
    assert res_cg.status_code == 201
    cg_data = res_cg.json()
    assert cg_data["semester"] == 5
    assert cg_data["is_lab"] is False

    # Create students in CSE 3rd Year Sec A
    s1 = client.post("/api/v1/admin/college/students", json={
        "student_number": "24CSE01", "full_name": "Alice Smith", "class_group_id": cg_data["class_group_id"]
    }).json()
    client.post("/api/v1/admin/college/students", json={
        "student_number": "24CSE02", "full_name": "Bob Jones", "class_group_id": cg_data["class_group_id"]
    }).json()

    # 2. Create Specific Attendance Session
    res_sess = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": cg_data["class_group_id"],
        "subject_name": "Operating Systems",
        "subject_code": "CS301",
        "session_type": "SPECIFIC",
        "semester": 5,
    })
    assert res_sess.status_code == 201
    sess_data = res_sess.json()
    assert sess_data["session_type"] == "SPECIFIC"
    assert sess_data["expected_roster_count"] == 2

    # Query roster endpoint
    roster_res = client.get(f"/api/v1/attendance/sessions/{sess_data['session_id']}/roster")
    assert roster_res.status_code == 200
    roster_data = roster_res.json()
    assert roster_data["expected_count"] == 2
    rolls = [r["student_number"] for r in roster_data["roster"]]
    assert "24CSE01" in rolls and "24CSE02" in rolls

    # 3. Create a Lab Session
    res_lab_cg = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": cse_id,
        "year_of_study": 3,
        "section": "LAB1",
        "academic_year": "2026-2027",
        "semester": 5,
        "is_lab": True,
        "lab_name": "Operating Systems Lab Batch 1",
    })
    assert res_lab_cg.status_code == 201
    lab_cg_id = res_lab_cg.json()["class_group_id"]

    # Enroll Alice in Lab 1
    client.post(f"/api/v1/admin/college/class-groups/{lab_cg_id}/students/{s1['student_id']}")

    res_lab_sess = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": lab_cg_id,
        "subject_name": "OS Lab",
        "session_type": "LAB",
        "lab_name": "Networks Lab 101",
        "semester": 5,
    })
    assert res_lab_sess.status_code == 201
    lab_sess_data = res_lab_sess.json()
    assert lab_sess_data["session_type"] == "LAB"
    assert lab_sess_data["lab_name"] == "Networks Lab 101"
    assert lab_sess_data["expected_roster_count"] == 1


def test_mixed_session_combining_groups_and_deduplicating(test_setup):
    client, sessions, _ = test_setup
    client.post("/api/v1/admin/college/departments/seed-defaults")
    depts = {d["code"]: d for d in client.get("/api/v1/admin/college/departments").json()["items"]}

    cse_id = depts["CSE"]["department_id"]
    csd_id = depts["CSD"]["department_id"]

    cg_cse = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": cse_id, "year_of_study": 2, "section": "A", "academic_year": "2026-2027"
    }).json()["class_group_id"]

    cg_csd = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": csd_id, "year_of_study": 2, "section": "A", "academic_year": "2026-2027"
    }).json()["class_group_id"]

    client.post("/api/v1/admin/college/students", json={
        "student_number": "25CSE01", "full_name": "Charlie CSE", "class_group_id": cg_cse
    }).json()
    client.post("/api/v1/admin/college/students", json={
        "student_number": "25CSD01", "full_name": "Dave CSD", "class_group_id": cg_csd
    }).json()

    # Create a mixed session combining CSE and CSD
    res_mixed = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": cg_cse,
        "class_group_ids": [cg_cse, cg_csd],
        "subject_name": "Mathematics for Computing (Combined)",
        "session_type": "MIXED",
        "semester": 3,
    })
    assert res_mixed.status_code == 201
    mixed_data = res_mixed.json()
    assert mixed_data["session_type"] == "MIXED"
    assert mixed_data["expected_roster_count"] == 2
    assert cg_cse in mixed_data["class_group_ids"] and cg_csd in mixed_data["class_group_ids"]

    # Verify roster returns union with distinct student IDs
    roster_res = client.get(f"/api/v1/attendance/sessions/{mixed_data['session_id']}/roster")
    roster = roster_res.json()["roster"]
    assert len(roster) == 2
    student_numbers = {r["student_number"] for r in roster}
    assert "25CSE01" in student_numbers
    assert "25CSD01" in student_numbers


def test_multi_photo_group_capture_deduplication_and_review(test_setup):
    client, sessions, mock_vision = test_setup
    client.post("/api/v1/admin/college/departments/seed-defaults")
    depts = {d["code"]: d for d in client.get("/api/v1/admin/college/departments").json()["items"]}
    cse_id = depts["CSE"]["department_id"]

    cg = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": cse_id, "year_of_study": 4, "section": "A", "academic_year": "2026-2027"
    }).json()["class_group_id"]

    # Create enrolled students
    s1 = client.post("/api/v1/admin/college/students", json={
        "student_number": "23CSE01", "full_name": "Student One", "class_group_id": cg
    }).json()
    s2 = client.post("/api/v1/admin/college/students", json={
        "student_number": "23CSE02", "full_name": "Student Two", "class_group_id": cg
    }).json()
    s3 = client.post("/api/v1/admin/college/students", json={
        "student_number": "23CSE03", "full_name": "Student Three", "class_group_id": cg
    }).json()

    # Create an enrolled student from outside the roster (Mech)
    mech_id = depts["MECH"]["department_id"]
    cg_mech = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": mech_id, "year_of_study": 4, "section": "A", "academic_year": "2026-2027"
    }).json()["class_group_id"]
    s_mech = client.post("/api/v1/admin/college/students", json={
        "student_number": "23MECH01", "full_name": "Outside Mech Student", "class_group_id": cg_mech
    }).json()

    # Enroll synthetic ArcFace templates in database
    db = sessions()
    settings = client.app.state.settings

    # Template vector for s1
    vec1 = np.zeros(512, dtype=np.float32)
    vec1[0] = 1.0
    c1, n1 = encrypt_embedding(vec1.tobytes(), settings)
    db.add(EmbeddingRecord(
        person_id=s1["person_id"], enrollment_version=1, recognizer_id="ArcFace",
        model_version="mock-arcface-v1", preprocessing_id="arcface:norm_crop",
        embedding_dim=512, ciphertext=c1, nonce=n1, sample_sha256="sha1", quality_json="{}", accepted=True
    ))

    # Template vector for s2
    vec2 = np.zeros(512, dtype=np.float32)
    vec2[1] = 1.0
    c2, n2 = encrypt_embedding(vec2.tobytes(), settings)
    db.add(EmbeddingRecord(
        person_id=s2["person_id"], enrollment_version=1, recognizer_id="ArcFace",
        model_version="mock-arcface-v1", preprocessing_id="arcface:norm_crop",
        embedding_dim=512, ciphertext=c2, nonce=n2, sample_sha256="sha2", quality_json="{}", accepted=True
    ))

    # Template vector for outside student s_mech
    vec_mech = np.zeros(512, dtype=np.float32)
    vec_mech[2] = 1.0
    c_mech, n_mech = encrypt_embedding(vec_mech.tobytes(), settings)
    db.add(EmbeddingRecord(
        person_id=s_mech["person_id"], enrollment_version=1, recognizer_id="ArcFace",
        model_version="mock-arcface-v1", preprocessing_id="arcface:norm_crop",
        embedding_dim=512, ciphertext=c_mech, nonce=n_mech, sample_sha256="sha_mech", quality_json="{}", accepted=True
    ))
    db.commit()

    # Create Attendance Session
    sess = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": cg,
        "subject_name": "Advanced Distributed Systems",
        "session_type": "SPECIFIC",
    }).json()
    session_id = sess["session_id"]

    # -------------------------------------------------------------
    # Capture Photo 1: Contains Student 1 (confident) and Unknown face
    # -------------------------------------------------------------
    vec_unknown = np.zeros(512, dtype=np.float32)
    vec_unknown[100] = 1.0 # Does not match any template

    mock_vision.set_mock_detections([
        GroupFaceObservation(
            face_index=0, bbox=[10, 10, 100, 100], detection_confidence=0.95,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=vec1,
            quality_score=50.0, is_usable=True, rejection_reason=None
        ),
        GroupFaceObservation(
            face_index=1, bbox=[120, 10, 220, 100], detection_confidence=0.90,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=vec_unknown,
            quality_score=40.0, is_usable=True, rejection_reason=None
        ),
    ])

    fake_img = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 1000
    res_cap1 = client.post(
        f"/api/v1/attendance/sessions/{session_id}/group-captures",
        files={"image": ("photo1.jpg", fake_img, "image/jpeg")},
    )
    assert res_cap1.status_code == 200
    cap1_data = res_cap1.json()
    assert cap1_data["capture"]["faces_detected"] == 2
    assert cap1_data["capture"]["faces_matched"] == 1
    assert cap1_data["capture"]["faces_unknown"] == 1
    assert cap1_data["cumulative_state"]["present_count"] == 1
    assert cap1_data["cumulative_state"]["photos_captured_count"] == 1

    # Check that AttendanceEvents are NOT created yet (not finalized)
    assert db.execute(select(AttendanceEvent).where(AttendanceEvent.attendance_session_id == session_id)).all() == []

    # -------------------------------------------------------------
    # Capture Photo 2: Contains Student 1 AGAIN (duplicate) + Student 2 (confident)
    # -------------------------------------------------------------
    mock_vision.set_mock_detections([
        GroupFaceObservation(
            face_index=0, bbox=[15, 15, 105, 105], detection_confidence=0.96,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=vec1,
            quality_score=60.0, is_usable=True, rejection_reason=None
        ),
        GroupFaceObservation(
            face_index=1, bbox=[200, 20, 300, 110], detection_confidence=0.92,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=vec2,
            quality_score=55.0, is_usable=True, rejection_reason=None
        ),
    ])

    res_cap2 = client.post(
        f"/api/v1/attendance/sessions/{session_id}/group-captures",
        files={"image": ("photo2.jpg", fake_img, "image/jpeg")},
    )
    assert res_cap2.status_code == 200
    cap2_data = res_cap2.json()
    assert cap2_data["capture"]["faces_detected"] == 2
    assert cap2_data["capture"]["faces_matched"] == 1 # Student 2 is new match
    assert cap2_data["capture"]["duplicates_ignored"] == 1 # Student 1 ignored as duplicate
    assert cap2_data["cumulative_state"]["present_count"] == 2
    assert cap2_data["cumulative_state"]["photos_captured_count"] == 2

    # -------------------------------------------------------------
    # Capture Photo 3: Contains outside Mech student (should be flagged PENDING_REVIEW)
    # and uncertain match
    # -------------------------------------------------------------
    # Vector that has marginal similarity ~0.50 (below 0.60 threshold)
    marginal_vec = np.zeros(512, dtype=np.float32)
    marginal_vec[0] = 0.52
    marginal_vec[10] = 0.85
    marginal_vec = marginal_vec / np.linalg.norm(marginal_vec)

    mock_vision.set_mock_detections([
        GroupFaceObservation(
            face_index=0, bbox=[10, 10, 100, 100], detection_confidence=0.90,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=vec_mech,
            quality_score=45.0, is_usable=True, rejection_reason=None
        ),
        GroupFaceObservation(
            face_index=1, bbox=[110, 10, 200, 100], detection_confidence=0.90,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=marginal_vec,
            quality_score=45.0, is_usable=True, rejection_reason=None
        ),
    ])

    res_cap3 = client.post(
        f"/api/v1/attendance/sessions/{session_id}/group-captures",
        files={"image": ("photo3.jpg", fake_img, "image/jpeg")},
    )
    assert res_cap3.status_code == 200
    cap3_data = res_cap3.json()
    assert cap3_data["capture"]["faces_uncertain"] >= 1

    # Check provisional state
    prov_res = client.get(f"/api/v1/attendance/sessions/{session_id}/provisional")
    assert prov_res.status_code == 200
    pstate = prov_res.json()
    assert pstate["photos_captured_count"] == 3
    assert pstate["present_count"] == 2 # s1 and s2

    # -------------------------------------------------------------
    # Faculty Manual Review and Toggle
    # -------------------------------------------------------------
    # Exercise the non-biometric/manual path: a legacy student may have no linked person ID.
    # The backend should recover the existing person record or create one before finalization.
    with sessions() as db:
        student_three = db.get(Student, s3["student_id"])
        student_three.person_id = None
        db.commit()

    # Student 3 was absent; faculty manually resolves student 3 as PRESENT with note
    toggle_res = client.post(
        f"/api/v1/attendance/sessions/{session_id}/provisional/{s3['student_id']}/toggle",
        json={"new_status": "PRESENT", "notes": "Approved by faculty in person"},
    )
    assert toggle_res.status_code == 200
    assert toggle_res.json()["provisional_status"] == "PRESENT"

    prov_res_after = client.get(f"/api/v1/attendance/sessions/{session_id}/provisional").json()
    assert prov_res_after["present_count"] == 3

    # -------------------------------------------------------------
    # Finalize Attendance
    # -------------------------------------------------------------
    fin_res = client.post(f"/api/v1/attendance/sessions/{session_id}/finalize")
    assert fin_res.status_code == 200
    fin_data = fin_res.json()
    assert fin_data["status"] == "success"
    assert fin_data["state"] == "CLOSED"
    assert fin_data["present_count"] == 3

    # Check that durable AttendanceEvents now exist in database for the 3 present students
    events = db.execute(
        select(AttendanceEvent).where(AttendanceEvent.attendance_session_id == session_id)
    ).scalars().all()
    assert len(events) == 3
    event_pids = {e.person_id for e in events}
    assert s1["person_id"] in event_pids
    assert s2["person_id"] in event_pids
    assert s3["person_id"] in event_pids
    manual_event = next(e for e in events if e.person_id == s3["person_id"])
    assert manual_event.pipeline_version == "manual-administrative-review"
    assert manual_event.similarity_score == 0.0
    assert manual_event.threshold == 1.0
    assert manual_event.client_device_id == "faculty-manual-override"

    # -------------------------------------------------------------
    # Idempotent Finalization Check
    # -------------------------------------------------------------
    fin_res_repeat = client.post(f"/api/v1/attendance/sessions/{session_id}/finalize")
    assert fin_res_repeat.status_code == 200
    assert fin_res_repeat.json()["status"] == "already_finalized"

    # Events count should NOT have doubled
    events_after = db.execute(
        select(AttendanceEvent).where(AttendanceEvent.attendance_session_id == session_id)
    ).scalars().all()
    assert len(events_after) == 3
    db.close()


def test_bulk_student_csv_import_validation_and_preview(test_setup):
    client, sessions, _ = test_setup
    client.post("/api/v1/admin/college/departments/seed-defaults")

    csv_data = """student_number,full_name,department_code,year_of_study,section,academic_year,semester,email
26CSE01,Rohan Verma,CSE,1,A,2026-2027,1,rohan@campus.edu
26CSE02,Pooja Patel,CSE,1,A,2026-2027,1,pooja@campus.edu
26CSE02,Duplicate Pooja,CSE,1,A,2026-2027,1,pooja2@campus.edu
26INV01,Bad Dept Student,INVALID_DEPT,1,A,2026-2027,1,bad@campus.edu
26BAD01,Bad Year Student,CSE,9,A,2026-2027,1,badyear@campus.edu
"""
    # 1. Test Dry Run: should report validation errors for the invalid rows
    res_dry = client.post(
        "/api/v1/admin/college/students/bulk-import?dry_run=true",
        files={"file": ("students.csv", csv_data.encode("utf-8"), "text/csv")},
    )
    assert res_dry.status_code == 200
    dry_data = res_dry.json()
    assert dry_data["dry_run"] is True
    assert dry_data["total_rows"] == 5
    assert dry_data["invalid_rows_count"] >= 3
    error_rolls = {e["student_number"] for e in dry_data["errors"]}
    assert "26CSE02" in error_rolls  # duplicate in file
    assert "26INV01" in error_rolls  # invalid department
    assert "26BAD01" in error_rolls  # bad year 9

    # 2. Test Clean CSV import
    clean_csv = """student_number,full_name,department_code,year_of_study,section,academic_year,semester,email
26ECE01,Kiran Kumar,ECE,2,B,2026-2027,3,kiran@campus.edu
26ECE02,Laxmi Devi,ECE,2,B,2026-2027,3,laxmi@campus.edu
"""
    res_import = client.post(
        "/api/v1/admin/college/students/bulk-import?dry_run=false",
        files={"file": ("clean_students.csv", clean_csv.encode("utf-8"), "text/csv")},
    )
    assert res_import.status_code == 200
    imp_data = res_import.json()
    assert imp_data["status"] == "SUCCESS"
    assert imp_data["imported_count"] == 2

    # Verify query
    st_res = client.get("/api/v1/admin/college/students")
    students = {s["student_number"]: s for s in st_res.json()["items"]}
    assert "26ECE01" in students
    assert "26ECE02" in students
    assert students["26ECE01"]["full_name"] == "Kiran Kumar"


def test_bulk_photo_biometric_enrollment(test_setup):
    client, sessions, mock_vision = test_setup
    client.post("/api/v1/admin/college/departments/seed-defaults")
    depts = {d["code"]: d for d in client.get("/api/v1/admin/college/departments").json()["items"]}
    eee_id = depts["EEE"]["department_id"]

    cg = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": eee_id, "year_of_study": 1, "section": "A", "academic_year": "2026-2027"
    }).json()["class_group_id"]

    client.post("/api/v1/admin/college/students", json={
        "student_number": "26EEE01", "full_name": "Suresh Reddy", "class_group_id": cg
    })

    # Prepare mock single-face detection
    enroll_vec = np.zeros(512, dtype=np.float32)
    enroll_vec[42] = 1.0
    mock_vision.set_mock_detections([
        GroupFaceObservation(
            face_index=0, bbox=[20, 20, 150, 150], detection_confidence=0.98,
            keypoints=[[1,1],[2,2],[3,3],[4,4],[5,5]], primary_embedding=enroll_vec,
            quality_score=75.0, is_usable=True, rejection_reason=None
        )
    ])

    fake_img = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 1000

    # Test upload with one matched student photo and one unmatched photo
    res_enroll = client.post(
        "/api/v1/admin/college/students/bulk-enroll-photos",
        files=[
            ("images", ("26EEE01.jpg", fake_img, "image/jpeg")),
            ("images", ("99UNKNOWN.jpg", fake_img, "image/jpeg")),
        ],
    )
    assert res_enroll.status_code == 200
    enroll_data = res_enroll.json()
    assert enroll_data["total_files"] == 2
    assert enroll_data["enrolled_count"] == 1
    assert enroll_data["failed_count"] == 1

    results_by_roll = {r["student_number"]: r for r in enroll_data["results"]}
    assert results_by_roll["26EEE01"]["status"] == "ENROLLED"
    assert results_by_roll["99UNKNOWN"]["status"] == "FAILED"
    assert "STUDENT_NOT_FOUND" in results_by_roll["99UNKNOWN"]["reason"]
