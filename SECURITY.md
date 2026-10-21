# Security Policy

FRS handles sensitive biometric data and attendance records. We treat security, identity integrity, biometric privacy, and audit reliability as non-negotiable requirements of the system.

## Supported Versions

| Version | Supported | Notes |
|---|:---:|---|
| `v0.1.x` (`main`) | :white_check_mark: | Current active release branch with ongoing security and functional patches |
| `< v0.1.0` | :x: | Pre-alpha experimental tags and unreleased prototypes are unsupported |

## Reporting a Vulnerability

If you discover a security vulnerability or biometric integrity issue within FRS, please do **not** disclose it publicly via a GitHub issue, public discussion, or pull request.

### Preferred Reporting Method
- **GitHub Private Vulnerability Reporting:** Submit a report via the **Security** tab of this repository under **Advisories** (`Security > Advisories > Report a vulnerability`).

### Report Contents
To help us triage and resolve the issue efficiently, please include:
- **Type of issue:** (e.g., authentication bypass, biometric matching collision/bypass, sensitive data exposure, injection, replay vulnerability, audit log tampering).
- **Affected component:** (FastAPI backend, Flutter kiosk client, Admin web console, or ONNX vision pipeline).
- **Affected commit / release version.**
- **Reproduction steps:** Clear, step-by-step instructions with a minimal, sanitized proof of concept.
- **Biometric & Data Safety:** Do **not** include real employee or student facial photographs, unmasked embeddings, database backups, or production secrets in your report.

### Vulnerability Response Process
1. **Acknowledgement:** We aim to acknowledge receipt of security reports within 48 to 72 hours.
2. **Triage & Assessment:** The report is evaluated for exploitability, biometric impact, and architectural risk.
3. **Patch & Coordinated Disclosure:** A verified fix will be prepared and merged into `main`. Once patched, a security advisory will be published detailing the vulnerability and remediation steps.

## Core Security Architecture & Trust Boundaries

### 1. Fail-Closed Biometric Verification
- Any ambiguity during 1:N identification or 1:1 verification strictly fails closed. If the top match confidence margin is below the minimum decision threshold ($\Delta \ge 0.08$) or frame quality is degraded ($< 0.60$), the capture is flagged for human administrative review (`REVIEW_REQUIRED`) rather than granted access.
- Multiple faces detected within a verification bounding region trigger immediate rejection (`MULTIPLE_FACES`) to prevent spoofing or split-attention exploits.

### 2. Encryption at Rest & In Flight
- **Biometric Embeddings:** Facial feature vectors are encrypted using authenticated AES-256-GCM before persistence in the PostgreSQL database.
- **In-Flight Data:** All network communications between the Flutter kiosk, administrative web console, and backend API require TLS 1.3/HTTPS.
- **Ephemeral Probe Frames:** In-flight capture bursts stored temporarily in the batch processing queue are encrypted and automatically scrubbed immediately upon session resolution.
- **Private Audit Evidence:** Audit media is stored in private, authenticated cloud storage accessed exclusively through short-lived, HMAC-SHA256-signed URLs (5-minute expiration).

### 3. Separation of Privilege & Zero Trust
- **Device vs. Admin Tokens:** Kiosk terminals use scoped device bearer tokens restricted to session batch submission and status polling. Terminals cannot read student rosters, query audit logs, inspect biometric galleries, or invoke administrative endpoints.
- **Administrative Control Plane:** Institutional management, manual attendance punches, status overrides, and biometric enrollments require distinct, high-entropy administrative credentials.

### 4. Client & Network Hardening
- **Android Network Security Config:** The Flutter Android kiosk enforces strict HTTPS policies, disabling cleartext HTTP across physical network interfaces. Cleartext communication is permitted solely on local development loopback interfaces (`127.0.0.1`, `10.0.2.2`).
- **Hardware-Backed Storage:** Terminal credentials and device configuration on mobile devices are stored securely using platform keystores (`flutter_secure_storage`).

### 5. Model Supply Chain Integrity
- ONNX model weights (`det_10g.onnx`, `w600k_r50.onnx`) are validated against pinned SHA-256 cryptographic hashes prior to runtime initialization. Dynamic remote model deserialization or untrusted weight execution is prohibited.
