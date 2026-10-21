# FRS — Model Weight Commercial Licensing and Permissive Alternatives

**Document Reference:** FRS-ENG-DOC-002
**Target Gate:** Gate 1 (Reproducible Vision Baseline)
**Status:** Actionable Legal & Technical Decision Framework

---

## 1. Executive Summary

The Face Recognition Attendance System (FRS) uses pure ONNX Runtime models for face detection (SCRFD) and embedding extraction (ArcFace). While the upstream software repositories (InsightFace) provide MIT-licensed source code, the pretrained **Buffalo_L model weights** (`det_10g.onnx`, `w600k_r50.onnx`) were trained on datasets (such as WebFace600K) whose terms explicitly restrict usage to non-commercial academic research and evaluation.

Before deploying FRS in commercial or production environments, the institution must select and execute one of two concrete pathways:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Candidate Resolution Pathways for Model Weight Licensing                    │
├───────────────────────────────────┬─────────────────────────────────────────┤
│ Pathway A: InsightFace Commercial │ Pathway B: Permissive Open-Source       │
│ License Authorization             │ Checkpoint Migration                    │
├───────────────────────────────────┼─────────────────────────────────────────┤
│ Retain Buffalo_L weights          │ Replace Buffalo_L weights with          │
│ Apply for commercial license from │ Apache-2.0 or BSD-licensed alternatives │
│ DeepInsight / InsightFace         │ (e.g. SFace or MobileFaceNet)           │
│ Preserves current 512-D vectors   │ Requires re-enrolling gallery embeddings│
└───────────────────────────────────┴─────────────────────────────────────────┘
```

---

## 2. Pathway A: InsightFace Commercial License Application

### 2.1 Scope and Terms
- **Models:** SCRFD detector (`det_10g.onnx`), ArcFace recognizer (`w600k_r50.onnx`).
- **Licensor:** DeepInsight / InsightFace project maintainers.
- **Licensing Channel:** Official commercial authorization via DeepInsight (contact: contact@insightface.ai).

### 2.2 Application Checklist
1. [ ] Institutional procurement review of enterprise pricing and terms.
2. [ ] Execution of bilateral Commercial Use Agreement covering university campus deployments.
3. [ ] Deposit of signed license certificate in `docs/legal/insightface_commercial_license.pdf`.
4. [ ] Configuration of environment variable:
   ```bash
   FRS_MODEL_LICENSE_ATTESTED=true
   ```
5. [ ] Verification that `engine.py` passes production startup checks without raising `ValueError`.

---

## 3. Pathway B: Permissive Open-Source Checkpoint Migration

If commercial licensing of Buffalo_L is not approved by institutional procurement, FRS is pre-architected to seamlessly switch to permissive-weight alternatives:

### 3.1 Approved Permissive Candidate Models

| Model Name | Architecture | License | Training Data Terms | Input Resolution | Embedding Dim | Checkpoint Source |
|---|---|:---:|---|:---:|:---:|---|
| **SFace** | ResNet-based | **Apache 2.0** | CASIA-WebFace (research) / Synthetic | $112 \times 112$ | 128-D | OpenCV Model Zoo (`sface.onnx`) |
| **MobileFaceNet** | MobileNetV2-ArcFace | **BSD 3-Clause** | Glint360k / Permissive Checkpoint | $112 \times 112$ | 512-D | InsightFace Model Zoo (BSD export) |
| **YuNet** | Face Detector | **Apache 2.0** | WIDER FACE (Permissive) | Variable | N/A (Detector) | OpenCV Model Zoo (`face_detection_yunet.onnx`) |

### 3.2 Technical Migration Procedure
1. **Download and Verify Checkpoint:**
   Download the target model and verify its SHA-256 hash using `provision_models.py`.
2. **Register in `primary-model-manifest.json`:**
   ```json
   {
     "recognizers": {
       "SFace": {
         "version": "1.0.0",
         "license": "Apache-2.0",
         "permitted_use": "COMMERCIAL_AND_RESEARCH",
         "sha256": "<computed_sha256_hash>",
         "embedding_dim": 128
       }
     }
   }
   ```
3. **Configure Environment Variables:**
   ```bash
   FRS_MODEL_PACK=sface
   FRS_MODEL_LICENSE_ATTESTED=true
   FRS_SIMILARITY_THRESHOLD=0.36
   ```
4. **Re-enroll Student Biometrics:**
   Run enrollment script across enrolled students to compute new 128-D or 512-D vectors.

---

## 4. Production Startup Gate Enforcement

FRS enforces runtime compliance in [backend/app/vision/engine.py](file:///c:/frs/backend/app/vision/engine.py#L170-L186). If `settings.env == "production"`, the application strictly refuses to start unless:
```python
if not settings.model_license_attested:
    raise ValueError("Production requires explicit verification of every model-weight license")
```
This guarantees zero legal ambiguity in live campus production deployments.
