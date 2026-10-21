from app.services.pipeline import _record_unique_frame_hash


def test_duplicate_visual_frame_hash_is_rejected() -> None:
    seen: set[str] = set()
    assert _record_unique_frame_hash("pixel-hash-a", seen)
    assert not _record_unique_frame_hash("pixel-hash-a", seen)
    assert _record_unique_frame_hash("pixel-hash-b", seen)
    assert seen == {"pixel-hash-a", "pixel-hash-b"}


def test_empty_visual_frame_hash_is_rejected() -> None:
    seen: set[str] = set()
    assert not _record_unique_frame_hash("", seen)
    assert not seen
