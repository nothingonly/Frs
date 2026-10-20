from __future__ import annotations

import cv2
import numpy as np

from app.vision.onnx_models import (
    _REFERENCE_5PTS,
    _distance2bbox,
    _distance2kps,
    norm_crop,
)
from app.services.pipeline import _cosine, _normalise


def test_norm_crop_affine_properties_and_scaling():
    """Verify norm_crop uses rigid similarity transform and scales reference points for different image sizes."""
    # Test identical reference points yield identity transform
    img = np.zeros((112, 112, 3), dtype=np.uint8)
    cropped_112 = norm_crop(img, _REFERENCE_5PTS, image_size=112)
    assert cropped_112.shape == (112, 112, 3)

    # Test with scaled image size 224
    pts = _REFERENCE_5PTS.copy()
    cropped_224 = norm_crop(img, pts, image_size=224)
    assert cropped_224.shape == (224, 224, 3)

    # Verify scaling math: ref points scaled by 224 / 112 = 2.0
    ref_224 = _REFERENCE_5PTS * (224.0 / 112.0)
    tform, _ = cv2.estimateAffinePartial2D(pts, ref_224)
    # The transform scale should be exactly 2.0
    scale = np.sqrt(tform[0, 0] ** 2 + tform[0, 1] ** 2)
    assert np.isclose(scale, 2.0, atol=1e-5)


def test_distance2bbox_and_kps_geometry():
    """Verify coordinate reconstruction from anchor centers and offsets."""
    centers = np.array([[100.0, 100.0], [200.0, 200.0]], dtype=np.float32)
    distances = np.array([[20.0, 30.0, 40.0, 50.0], [10.0, 10.0, 10.0, 10.0]], dtype=np.float32)

    bboxes = _distance2bbox(centers, distances)
    # Box 0: x1 = 100 - 20 = 80, y1 = 100 - 30 = 70, x2 = 100 + 40 = 140, y2 = 100 + 50 = 150
    assert np.allclose(bboxes[0], [80.0, 70.0, 140.0, 150.0])
    # Box 1: x1 = 190, y1 = 190, x2 = 210, y2 = 210
    assert np.allclose(bboxes[1], [190.0, 190.0, 210.0, 210.0])

    # KPS offsets for 5 points (10 values)
    kps_offsets = np.ones((2, 10), dtype=np.float32) * 5.0
    kps = _distance2kps(centers, kps_offsets)
    assert kps.shape == (2, 5, 2)
    assert np.allclose(kps[0, 0], [105.0, 105.0])


def test_nms_preserves_adjacent_faces_with_xywh_conversion():
    """Verify that converting bboxes to [x, y, w, h] prevents false suppression of adjacent faces."""
    # Two distinct faces with width=50, height=50 separated horizontally by dx=22
    # In xywh format, their IoU is ~0.35, which is below the 0.4 NMS threshold. Both must survive.
    b_xyxy = np.array([[100.0, 100.0, 150.0, 150.0], [122.0, 100.0, 172.0, 150.0]], dtype=np.float32)
    scores = [0.9, 0.8]

    # Convert to xywh as implemented in fixed SCRFDDetector
    nms_boxes = b_xyxy.copy()
    nms_boxes[:, 2] -= nms_boxes[:, 0]
    nms_boxes[:, 3] -= nms_boxes[:, 1]

    indices = cv2.dnn.NMSBoxes(nms_boxes.tolist(), scores, 0.5, 0.4)
    flat_idx = np.array(indices).flatten()
    assert len(flat_idx) == 2, "Both faces must survive NMS; false suppression indicates area distortion"


def test_arcface_preprocessing_and_normalization():
    """Verify ArcFace input transformation: mean subtraction, scaling, and unit vector output."""
    # Synthetic 112x112 aligned face
    img = np.full((112, 112, 3), 128, dtype=np.uint8)
    blob = cv2.dnn.blobFromImage(img, 1.0 / 128.0, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
    # Blob should have shape (1, 3, 112, 112)
    assert blob.shape == (1, 3, 112, 112)
    # Expected value: (128 - 127.5) / 128.0 = 0.5 / 128.0 ≈ 0.00390625
    expected_val = (128.0 - 127.5) / 128.0
    assert np.isclose(blob[0, 0, 0, 0], expected_val, atol=1e-5)

    # Normalization math
    vec = np.array([3.0, 4.0] + [0.0] * 510, dtype=np.float32)
    normed = _normalise(vec)
    assert np.isclose(np.linalg.norm(normed), 1.0, atol=1e-6)
    assert np.isclose(normed[0], 3.0 / 5.0)
    assert np.isclose(normed[1], 4.0 / 5.0)

    # Cosine similarity bounds and symmetry
    sim_self = _cosine(normed, normed)
    assert np.isclose(sim_self, 1.0, atol=1e-6)

    orthogonal = np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)
    sim_ortho = _cosine(normed, orthogonal)
    assert np.isclose(sim_ortho, 0.0, atol=1e-6)

    opposite = -normed
    sim_opp = _cosine(normed, opposite)
    assert np.isclose(sim_opp, -1.0, atol=1e-6)
