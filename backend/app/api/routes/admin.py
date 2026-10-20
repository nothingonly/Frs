from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import admin_actor
from app.database import get_db
from app.db.entities import AttendanceEvent, AuditEvent, ModelRegistryEntry, Person

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


@router.get("/people")
def list_people(
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(Person)
    if active_only:
        statement = statement.where(Person.is_active.is_(True))
    people = db.execute(statement.order_by(Person.employee_id).limit(limit).offset(offset)).scalars().all()
    return {
        "items": [{
            "person_id": p.person_id,
            "employee_id": p.employee_id,
            "full_name": p.full_name,
            "department": p.department,
            "is_active": p.is_active,
            "enrollment_version": p.enrollment_version,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        } for p in people],
        "limit": limit,
        "offset": offset,
    }


@router.post("/people/{employee_id}/deactivate")
def deactivate_person(
    employee_id: str,
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    person = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if person.is_active:
        person.is_active = False
        person.updated_at = datetime.now(timezone.utc)
    event = AuditEvent(
        session_id=f"admin:{employee_id}",
        actor_type="administrator",
        actor_id=actor,
        action="person.deactivate",
        decision_state="REVOKED",
        reason_codes_json=json.dumps(["ADMINISTRATIVE_REVOCATION"]),
        evidence_json=json.dumps({"employee_id": employee_id, "enrollment_version": person.enrollment_version}),
    )
    db.add(event)
    db.commit()
    return {"status": "success", "employee_id": employee_id, "is_active": False, "audit_id": event.audit_id}


@router.post("/people/{employee_id}/reactivate")
def reactivate_person(
    employee_id: str,
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    person = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    person.is_active = True
    person.updated_at = datetime.now(timezone.utc)
    event = AuditEvent(
        session_id=f"admin:{employee_id}",
        actor_type="administrator",
        actor_id=actor,
        action="person.reactivate",
        decision_state="REACTIVATED",
        reason_codes_json=json.dumps(["ADMINISTRATIVE_REACTIVATION"]),
        evidence_json=json.dumps({"employee_id": employee_id, "enrollment_version": person.enrollment_version}),
    )
    db.add(event)
    db.commit()
    return {"status": "success", "employee_id": employee_id, "is_active": True, "audit_id": event.audit_id}


@router.get("/attendance")
def list_attendance(
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(AttendanceEvent)
    if employee_id:
        statement = statement.where(AttendanceEvent.employee_id == employee_id)
    rows = db.execute(statement.order_by(AttendanceEvent.timestamp.desc()).limit(limit).offset(offset)).scalars().all()
    return {
        "items": [{
            "attendance_id": row.attendance_id,
            "employee_id": row.employee_id,
            "punch_type": row.punch_type,
            "timestamp": row.timestamp.isoformat(),
            "similarity_score": row.similarity_score,
            "threshold": row.threshold,
            "client_device_id": row.client_device_id,
            "pipeline_version": row.pipeline_version,
            "evidence_id": row.evidence_id,
            "attendance_session_id": row.attendance_session_id,
        } for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/audit/{audit_id}")
def get_audit(
    audit_id: str,
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    event = db.get(AuditEvent, audit_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found.")
    return {
        "audit_id": event.audit_id,
        "session_id": event.session_id,
        "occurred_at": event.occurred_at.isoformat(),
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "action": event.action,
        "decision_state": event.decision_state,
        "reason_codes": json.loads(event.reason_codes_json),
        "evidence": json.loads(event.evidence_json),
    }


@router.get("/models")
def list_models(
    request: Request,
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.execute(select(ModelRegistryEntry).order_by(ModelRegistryEntry.model_id, ModelRegistryEntry.model_version)).scalars().all()
    return {
        "runtime_components": request.app.state.vision.component_status,
        "registry": [{
            "model_id": row.model_id,
            "model_version": row.model_version,
            "artifact_sha256": row.artifact_sha256,
            "artifact_path": row.artifact_path,
            "license_name": row.license_name,
            "source_url": row.source_url,
            "permitted_use": row.permitted_use,
            "preprocessing_id": row.preprocessing_id,
            "input_contract": json.loads(row.input_contract_json),
            "output_contract": json.loads(row.output_contract_json),
            "benchmark": json.loads(row.benchmark_json),
            "active": row.active,
            "registered_at": row.registered_at.isoformat(),
        } for row in rows],
    }
