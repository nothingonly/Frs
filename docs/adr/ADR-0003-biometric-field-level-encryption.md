# ADR-0003: Biometric Field-Level Encryption, Redaction, and Privacy Lifecycle

## Status
Accepted

## Context
Biometric facial vectors and raw probe images are sensitive personally identifiable information (PII) subject to legal privacy frameworks (FERPA, GDPR, CCPA). Storing plaintext facial embeddings in a relational database or leaving probe images indefinitely in persistent storage exposes students to long-term identity theft risks if the database or backups are compromised.

## Decision
FRS enforces strict end-to-end field-level cryptographic protections and lifecycle controls:
1. **AES-256-GCM Encryption at Rest:**
   - All enrolled 512-D float vectors (`ciphertext` and `nonce` in `embedding_records`) are encrypted using a 256-bit server key (`data_encryption_key`) before database commit.
   - Raw queued camera burst frames (`encrypted_payload` and `payload_nonce` in `capture_batch_jobs`) are encrypted upon submission and decrypted only in-memory during worker inference.
2. **Privacy-Safe Log Redaction:**
   - An automated logging filter (`RedactingFilter` in `logging_config.py`) redacts Bearer tokens, base64 payloads, and raw float vectors from console output and diagnostic logs.
3. **Automated Data Minimization & Retention Purge:**
   - Raw queued image payloads are purged automatically after a configurable retention window (e.g. 30 days) while preserving non-biometric attendance event records and audit trails.
4. **Verifiable Biometric De-enrollment:**
   - When a student de-enrolls, all associated embedding records and cloud media assets are permanently purged, and an HMAC-SHA256 authenticated digital deletion certificate is issued to the operator and recorded in the immutable audit log.

## Consequences
- **Positive:** Cryptographically robust compliance with global biometric data minimization standards; zero exposure of plaintext vectors in database backups.
- **Positive:** Deletion events produce non-repudiable audit certificates.
- **Negative:** Search operations cannot perform SQL-native cosine similarity in the database; embeddings must be decrypted in-memory for gallery matching (mitigated by class-group scoped indexing and memoization).
