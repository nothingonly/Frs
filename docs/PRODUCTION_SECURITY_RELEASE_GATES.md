# Production Security Release Gates

This checklist is part of the release record for FRS. A passing CI run is not a production approval.

## Mandatory gates

- [ ] Replace Buffalo_L / InsightFace model artifacts whose manifest states academic, research-only, or non-commercial use with weights that are licensed for the institution's intended use. Do not set `FRS_MODEL_LICENSE_ATTESTED=true` as a workaround. Production startup rejects restrictive model manifest terms.
- [ ] Record provenance for every deployed model: publisher, source, exact SHA-256, license, permitted-use terms, training dataset disclosure where available, and approval by the institution's legal/licensing owner.
- [ ] Calibrate thresholds using representative campus data; record FAR/FRR and subgroup performance. `FRS_THRESHOLD_CALIBRATED` is not a substitute for the signed evaluation record.
- [ ] Complete an independent presentation-attack/liveness evaluation with replay, printed-photo, screen, mask, and camera-injection cases before relying on liveness as an attendance control.
- [ ] Run migrations against a staging PostgreSQL instance, including the append-only audit-event trigger; verify the application DB role cannot disable the trigger or mutate audit rows.
- [ ] Provision and test the dedicated `FRS_DELETION_CERTIFICATE_KEY`, kiosk-to-class scope map, and trusted LTI platform public key. Confirm backups and key rotation procedures.
- [ ] Verify object-level authorization with real signed JWTs and configured kiosk credentials, not only test dependency overrides.
- [ ] Require green backend, admin-web, and Flutter checks on the exact PR head. Investigate all skipped tests; model inference tests skipped because weights are not provisioned are not evidence of production model behavior.
- [ ] Complete physical Android kiosk testing, privacy/retention verification, and institutional CISO/legal approval.

## Current limitations

The repository cannot grant a commercial or institutional license to third-party model weights. That is a procurement/legal decision. Do not merge or deploy until permitted weights are provisioned and the manifest is updated with verifiable provenance.

Deletion certificates are signed with Ed25519 and include the public key and its SHA-256 fingerprint. The public key embedded in a certificate is not a trust anchor: the institution must distribute and pin the expected public key through a separate trusted channel, verify the signature over the canonical payload, and retain key-rotation history. The signature proves payload integrity, not remote erasure; deletion is complete only when the storage provider confirms deletion of every target. Production startup requires `FRS_DELETION_CERTIFICATE_KEY` to be URL-safe base64 encoding of a randomly generated 32-byte Ed25519 private-key seed; do not reuse JWT, admin, device or data-encryption material.

The alternative attendance endpoint deliberately fails closed with HTTP 503 until a server-side PIN/card/OTP verifier is implemented and provisioned. Do not re-enable attendance based only on a student number or a client-supplied method name.
