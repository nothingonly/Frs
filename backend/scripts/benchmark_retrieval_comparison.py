"""
Reproducible Benchmark: Unoptimized vs Optimized Gallery Retrieval
Compares:
1. Baseline: No burst caching (DB queried & AES decrypted on every frame) + iterative Python cosine loop.
2. Optimized: Burst-level gallery memoization + vectorized SIMD BLAS matrix-vector dot product.
"""

from __future__ import annotations

import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Add backend to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Settings
from app.database import Base
from app.db.entities import EmbeddingRecord, Person
from app.security import decrypt_embedding, encrypt_embedding
from app.schemas.contracts import RetrievalCandidate


def _normalise(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(value))
    if value.size == 0 or not np.all(np.isfinite(value)) or norm <= 1e-12:
        raise ValueError("Embedding is empty, non-finite, or has zero norm")
    return value / norm


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    a, b = _normalise(left), _normalise(right)
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def baseline_read_gallery(session, settings, recognizer_id, model_version, preprocessing_id):
    """Simulates the unoptimized implementation: queries DB and decrypts all records each call."""
    statement = (
        select(EmbeddingRecord, Person)
        .join(Person, Person.person_id == EmbeddingRecord.person_id)
        .where(
            EmbeddingRecord.accepted.is_(True),
            EmbeddingRecord.recognizer_id == recognizer_id,
            EmbeddingRecord.model_version == model_version,
            EmbeddingRecord.preprocessing_id == preprocessing_id,
            EmbeddingRecord.enrollment_version == Person.enrollment_version,
            Person.is_active.is_(True),
        )
    )
    rows = session.execute(statement).all()
    vectors_by_person = defaultdict(list)
    people_by_id = {}
    for record, person in rows:
        raw = decrypt_embedding(record.ciphertext, record.nonce, settings)
        vector = np.frombuffer(raw, dtype=np.float32)
        vectors_by_person[person.person_id].append(_normalise(vector.copy()))
        people_by_id[person.person_id] = person

    profiles = []
    for person_id, vectors in vectors_by_person.items():
        prototype = _normalise(np.mean(np.stack(vectors, axis=0), axis=0))
        profiles.append((people_by_id[person_id], prototype))
    return profiles, len(rows)


def baseline_retrieve(session, settings, query, recognizer_id, model_version, preprocessing_id, top_k=5):
    """Baseline retrieval: reads gallery every frame and iterates with Python _cosine."""
    profiles, _ = baseline_read_gallery(session, settings, recognizer_id, model_version, preprocessing_id)
    query_vector = _normalise(query)
    scored = []
    for person, profile in profiles:
        score = _cosine(query_vector, profile)
        scored.append(RetrievalCandidate(
            person_id=person.person_id,
            employee_id=person.employee_id,
            full_name=person.full_name,
            similarity=score,
        ))
    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:top_k]


def optimized_read_gallery(session, settings, recognizer_id, model_version, preprocessing_id, gallery_cache=None):
    """Optimized implementation: checks burst-level gallery_cache first."""
    cache_key = (recognizer_id, model_version, preprocessing_id, None, None)
    if gallery_cache is not None and cache_key in gallery_cache:
        return gallery_cache[cache_key]

    profiles, row_count = baseline_read_gallery(session, settings, recognizer_id, model_version, preprocessing_id)
    result = (profiles, row_count)
    if gallery_cache is not None:
        gallery_cache[cache_key] = result
    return result


def optimized_retrieve(session, settings, query, recognizer_id, model_version, preprocessing_id, gallery_cache=None, top_k=5):
    """Optimized retrieval: uses gallery_cache and vectorized SIMD matrix-vector dot product."""
    profiles, _ = optimized_read_gallery(
        session, settings, recognizer_id, model_version, preprocessing_id, gallery_cache=gallery_cache
    )
    if not profiles:
        return []
    query_vector = _normalise(query)
    gallery_matrix = np.stack([profile for _person, profile in profiles], axis=0)
    sim_scores = np.clip(gallery_matrix @ query_vector, -1.0, 1.0)
    scored = [
        RetrievalCandidate(
            person_id=person.person_id,
            employee_id=person.employee_id,
            full_name=person.full_name,
            similarity=float(sim_scores[i]),
        )
        for i, (person, _profile) in enumerate(profiles)
    ]
    scored.sort(key=lambda item: item.similarity, reverse=True)
    return scored[:top_k]


def run_benchmark(n_students=60, n_burst_frames=3, iterations=100):
    import base64
    import os

    ephemeral_key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    settings = Settings(
        env="development",
        data_encryption_key=ephemeral_key,
        database_url="sqlite:///:memory:",
    )
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    rec_id = "ArcFace"
    version = "w600k_r50_v1"
    prep_id = "ArcFace:w600k_r50_v1:five-point-norm-crop-112-v1:original"

    # Seed students and encrypted embeddings
    rng = np.random.default_rng(42)
    with Session() as session:
        for i in range(n_students):
            pid = str(uuid.uuid4())
            person = Person(
                person_id=pid,
                employee_id=f"STU{i:04d}",
                full_name=f"Student {i}",
                department="CS",
                enrollment_version=1,
                is_active=True,
            )
            session.add(person)
            session.flush()

            # 3 sample vectors per student
            for _ in range(3):
                vec = _normalise(rng.standard_normal(512).astype(np.float32))
                ct, nonce = encrypt_embedding(vec.tobytes(), settings)
                rec = EmbeddingRecord(
                    person_id=pid,
                    enrollment_version=1,
                    recognizer_id=rec_id,
                    model_version=version,
                    preprocessing_id=prep_id,
                    embedding_dim=512,
                    ciphertext=ct,
                    nonce=nonce,
                    sample_sha256="test",
                    quality_json="{}",
                    accepted=True,
                )
                session.add(rec)
        session.commit()

    # Generate 3 query vectors (burst)
    burst_queries = [_normalise(rng.standard_normal(512).astype(np.float32)) for _ in range(n_burst_frames)]

    # Benchmark Baseline (Unoptimized)
    baseline_times = []
    with Session() as session:
        for _ in range(iterations):
            t0 = time.perf_counter()
            for q in burst_queries:
                _ = baseline_retrieve(session, settings, q, rec_id, version, prep_id)
            baseline_times.append((time.perf_counter() - t0) * 1000.0)

    # Benchmark Optimized
    optimized_times = []
    with Session() as session:
        for _ in range(iterations):
            burst_cache = {}
            t0 = time.perf_counter()
            for q in burst_queries:
                _ = optimized_retrieve(session, settings, q, rec_id, version, prep_id, gallery_cache=burst_cache)
            optimized_times.append((time.perf_counter() - t0) * 1000.0)

    b_arr = np.array(baseline_times)
    o_arr = np.array(optimized_times)

    print("=" * 60)
    print(f"BENCHMARK RESULTS: {n_students} Enrolled Students, {n_burst_frames}-Frame Burst, {iterations} Iterations")
    print("=" * 60)
    print(f"Total Enrolled Embedding Records: {n_students * 3}")
    print()
    print("--- Unoptimized Baseline (No Cache, Iterative Cosine) ---")
    print(f"  P50 Latency: {np.percentile(b_arr, 50):.2f} ms")
    print(f"  P95 Latency: {np.percentile(b_arr, 95):.2f} ms")
    print(f"  P99 Latency: {np.percentile(b_arr, 99):.2f} ms")
    print(f"  Throughput:  {1000.0 / np.mean(b_arr):.1f} bursts/sec")
    print(f"  DB Queries / burst:       {n_burst_frames}")
    print(f"  AES Decryptions / burst:  {n_burst_frames * n_students * 3}")
    print()
    print("--- Optimized (Burst Gallery Memoization + Vectorized SIMD) ---")
    print(f"  P50 Latency: {np.percentile(o_arr, 50):.2f} ms")
    print(f"  P95 Latency: {np.percentile(o_arr, 95):.2f} ms")
    print(f"  P99 Latency: {np.percentile(o_arr, 99):.2f} ms")
    print(f"  Throughput:  {1000.0 / np.mean(o_arr):.1f} bursts/sec")
    print("  DB Queries / burst:       1 (66.7% reduction)")
    print(f"  AES Decryptions / burst:  {n_students * 3} (66.7% reduction)")
    print()
    speedup = np.median(b_arr) / np.median(o_arr)
    print(f"Speedup Factor (Median P50): {speedup:.2f}x faster")
    print("=" * 60)


if __name__ == "__main__":
    run_benchmark()
