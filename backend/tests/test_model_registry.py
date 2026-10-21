from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.entities import ModelRegistryEntry
from app.database import Base
from app.main import _deactivate_stale_model_versions


def _registry_entry(model_id: str, version: str, active: bool = True) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        model_id=model_id,
        model_version=version,
        artifact_sha256="a" * 64,
        artifact_path=f"/models/{model_id}-{version}.onnx",
        license_name="test-only",
        source_url="https://example.invalid/test-artifact",
        permitted_use="test fixture only",
        preprocessing_id="test-preprocess-v1",
        input_contract_json="{}",
        output_contract_json="{}",
        benchmark_json="{}",
        active=active,
    )


def test_registry_deactivates_superseded_versions_for_loaded_models() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        old_arcface = _registry_entry("ArcFace", "old-version")
        active_arcface = _registry_entry("ArcFace", "current-version")
        configured_adaface = _registry_entry("AdaFace", "ada-version")
        untouched_fiqa = _registry_entry("FIQA", "fiqa-version")
        session.add_all([old_arcface, active_arcface, configured_adaface, untouched_fiqa])
        session.commit()

        _deactivate_stale_model_versions(
            session,
            {"ArcFace": "current-version", "AdaFace": "ada-version"},
        )
        session.commit()

        values = {
            (row.model_id, row.model_version): row.active
            for row in session.scalars(select(ModelRegistryEntry)).all()
        }
        assert values[("ArcFace", "old-version")] is False
        assert values[("ArcFace", "current-version")] is True
        assert values[("AdaFace", "ada-version")] is True
        # Model roles not loaded by this runtime are intentionally outside this update.
        assert values[("FIQA", "fiqa-version")] is True
    engine.dispose()
