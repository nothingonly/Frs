# ADR-0001: Pure ONNX Runtime Architecture over C++ / InsightFace Python Wrapper

## Status
Accepted

## Context
The initial architecture for face detection and embedding extraction relied on the upstream `insightface` Python package, which internally wraps OpenCV, Cython, and C++ extensions with hard-coded filesystem expectations (`~/.insightface/models/`). This introduced several critical operational issues:
1. Complex C++ build dependencies on deployment environments (CUDA, GCC, CMake).
2. Conflation of MIT source code licensing with proprietary/research-only model weight licenses.
3. Lack of strict SHA-256 sidecar checksum verification prior to model memory mapping.
4. Rigid NMS and detection scaling assumptions that did not accommodate strict temporal voting.

## Decision
FRS standardizes exclusively on **pure ONNX Runtime** (`onnxruntime` / `onnxruntime-gpu`):
- All models (SCRFD detector, ArcFace embedding extractor, MiniFASNet PAD, AdaFace, MobileFaceNet, FIQA) are executed directly via ONNX Runtime inference sessions.
- Preprocessing (norm crop, affine alignment, RGB normalization) is implemented purely in Python using NumPy and Pillow, eliminating OpenCV runtime dependencies in production.
- Model weights must pass cryptographic SHA-256 validation against an immutable JSON manifest before session initialization.

## Consequences
- **Positive:** Deployment containers are lightweight, portable across CPU/GPU, free of C++ build toolchains, and strictly verifiable by SHA-256 digests.
- **Positive:** Complete programmatic control over input shapes, execution providers, and threading.
- **Negative:** Preprocessing math (affine transforms, NMS) must be maintained and regression-tested directly within the repository.
