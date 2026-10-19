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

## Primary model-pack directory

For FRS_MODEL_PACK=buffalo_l, place the separately licensed and verified det_10g.onnx and w600k_r50.onnx files in:

    <FRS_MODEL_ROOT>/models/buffalo_l/

The InsightFace Python source package and publicly distributed pretrained weights have different licensing terms. The widely distributed pretrained weights are restricted to non-commercial research absent separate permission. Obtain and document the appropriate rights for actual attendance deployment before setting FRS_MODEL_LICENSE_ATTESTED=true.

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
