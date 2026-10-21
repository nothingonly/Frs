# Real FRS model artifacts — operator provisioning is required

The application does not ship model weights, generate identity scores from placeholders, or silently download weights during backend startup.

Production readiness requires actual compatible inference files. The V5 model registry retains the full SHA-256, version, preprocessing, input/output contract, and verified license for each artifact.

## Required runtime portfolio

| FRS role | Required artifact | Execution |
|---|---|---|
| Primary detection | SCRFD from the selected, licensed model pack | Every candidate frame |
| Recovery detection | RetinaFace ONNX and sidecar | Only after the primary detector returns no face |
| Primary recognition | ArcFace from the selected, licensed model pack | Good-quality frames |
| Difficult-quality recognition | AdaFace ONNX and sidecar | When quality routing requests it |
| Lightweight independent recognition | MobileFaceNet ONNX and sidecar | Secondary checks or measured edge/throughput route |
| Presentation-attack detection | MiniFASNet ONNX and sidecar | When policy requires liveness |
| Learned face-image quality | FIQA ONNX and sidecar | After deterministic quality checks |

Model artifacts must match this implementation's declared interface. A filename alone does not establish model identity or compatibility.

## Runtime mount layout (Docker Compose)

Compose mounts `backend/model-artifacts/` read-only at `/models` and configures `FRS_MODEL_ROOT=/models/insightface`. The primary pack must therefore be laid out exactly as:

    backend/model-artifacts/
      insightface/
        models/
          buffalo_l/
            det_10g.onnx
            w600k_r50.onnx
            manifest.json
      retinaface.onnx
      retinaface.onnx.json
      adaface.onnx
      adaface.onnx.json
      mobilefacenet.onnx
      mobilefacenet.onnx.json
      minifasnet.onnx
      minifasnet.onnx.json
      fiqa.onnx
      fiqa.onnx.json

For `FRS_MODEL_PACK=buffalo_l`, the primary paths resolve to `<FRS_MODEL_ROOT>/models/buffalo_l/`. The filenames, checksums and manifest records must match the actual artifacts. Specialist paths in `.env` must resolve to the mounted `/models/...` paths. Keep actual model weights out of Git unless the project owner has explicitly reviewed the license and repository storage implications.

The InsightFace Python source package and publicly distributed pretrained weights have different licensing terms. The widely distributed pretrained weights are restricted to non-commercial research absent separate permission. Obtain and document rights for the institution's intended attendance use before deploying. The `FRS_MODEL_LICENSE_ATTESTED` flag is informational only; setting it to true does not grant rights and cannot bypass the production manifest license check.

## Separate ONNX specialists

Place artifacts under the mounted model-artifacts directory (or another configured directory):

- retinaface.onnx and retinaface.onnx.json
- adaface.onnx and adaface.onnx.json
- mobilefacenet.onnx and mobilefacenet.onnx.json
- minifasnet.onnx and minifasnet.onnx.json
- fiqa.onnx and fiqa.onnx.json

Each .json file is an artifact-specific contract, not an auto-filled mock. It must describe the exact weights. The generic ONNX adapters require non-empty verified values for:

- license_name: the actual license and permitted use
- source_url: immutable official release/artifact source or internal provenance record
- preprocessing_id: versioned preprocessing contract
- output_type: embedding, logits, or quality_score depending on task
- layout: NCHW or NHWC
- height, width, color_order, mean, std: values verified for the actual weight file
- output_name: exact ONNX graph output node if needed

MiniFASNet also needs live_class_index matching the published output class ordering. FIQA may specify score_activation as none or sigmoid only when that matches the trained model. Incorrect normalization or class mapping can make real inference misleading; validate against the original model documentation and held-out examples before promotion.

The RetinaFace integration uses the InsightFace detector interface and requires a compatible ONNX artifact that loads as a RetinaFace implementation, plus a sidecar declaring license_name, source_url, and preprocessing_id. Other RetinaFace export formats need a dedicated adapter rather than being forced through the wrong interface.

## Calibrate thresholds; do not guess them

Run python -m app.benchmark with a labeled validation manifest. Keep disjoint enrollment, known-probe and unknown-probe splits. Do not calibrate and report final performance using the same captures. A tiny test set cannot demonstrate a sufficiently low false-accept rate.

Production startup is deliberately blocked until thresholds are calibrated, model rights are attested, secrets are configured, and all required specialist assets are available.
