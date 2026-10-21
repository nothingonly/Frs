# FRS Architecture Specification: Android Encrypted SQLCipher Offline Burst Buffer

## Document Control
- **Document ID**: FRS-SPEC-GATE05-01
- **Target Component**: Flutter Mobile Kiosk (`kiosk_app`) / Android Tablet
- **Architecture Gate**: Gate 5 — Device and Integrations
- **Status**: Approved Architectural Blueprint for Implementation

---

## 1. Executive Summary and Motivation

In typical collegiate deployment environments (lecture halls, auditoriums, remote workshops), campus Wi-Fi or cellular networks may experience intermittent degradation or total blackouts.

The FRS Kiosk must maintain reliable student throughput during network outages without violating biometric data protection principles:
1. **Never store raw face crops or photos in cleartext on flash storage.**
2. **Buffer encrypted burst frames securely using hardware-backed cryptographic keys.**
3. **Automatically drain queued capture batches to the backend once connectivity is restored, preserving exact timestamps and idempotency keys.**
4. **Purge buffered data fail-closed if the offline duration exceeds the 24-hour retention window.**

---

## 2. Cryptographic Key Management via Android Keystore

Offline storage encryption relies on a two-tier key hierarchy:

```
+-------------------------------------------------------------+
|               Android Keystore (TEE / StrongBox)            |
|  Master Key: alias "frs_kiosk_master_storage_key"          |
|  Algorithm: AES/GCM/NoPadding (256-bit)                     |
|  Protection: Hardware-backed, user-presence optional        |
+-------------------------------------------------------------+
                              |
                     Protects / Decrypts
                              v
+-------------------------------------------------------------+
|             flutter_secure_storage (EncryptedSharedPreferences)|
|  Database Passphrase (256-bit CSPRNG token)                |
|  Local Buffer Key (256-bit AES-GCM payload encryption)      |
+-------------------------------------------------------------+
                              |
                     Unlocks / Encrypts
                              v
+-------------------------------------------------------------+
|               SQLCipher Encrypted Local Database             |
|  Database file: `frs_offline_bursts.enc.db`                |
|  Cipher: 256-bit AES in CBC mode (SQLCipher v4 standard)    |
|  HMAC-SHA512 per page authentication                        |
+-------------------------------------------------------------+
```

### 2.1 Initialization Routine
```dart
// Pseudo-code implementation for Kiosk Database Service
final secureStorage = const FlutterSecureStorage(
  aOptions: AndroidOptions(
    encryptedSharedPreferences: true,
    resetOnError: true,
  ),
);

String? dbKey = await secureStorage.read(key: 'frs_sqlcipher_key');
if (dbKey == null) {
  final randomBytes = Uint8List(32);
  final secureRandom = Random.secure();
  for (int i = 0; i < 32; i++) {
    randomBytes[i] = secureRandom.nextInt(256);
  }
  dbKey = base64Url.encode(randomBytes);
  await secureStorage.write(key: 'frs_sqlcipher_key', value: dbKey);
}
```

---

## 3. Database Schema

The encrypted SQLite database uses SQLCipher v4 with SQLite PRAGMAs:
```sql
PRAGMA key = '<256-bit passphrase>';
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 64000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
PRAGMA cipher_default_kdf_algorithm = PBKDF2_HMAC_SHA512;
```

### 3.1 `offline_burst_batches` Table
```sql
CREATE TABLE offline_burst_batches (
    batch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    class_group_id TEXT NOT NULL,
    device_actor_id TEXT NOT NULL,
    client_device_id TEXT NOT NULL,
    punch_type TEXT NOT NULL CHECK (punch_type IN ('CHECK_IN', 'CHECK_OUT')),
    idempotency_key TEXT NOT NULL UNIQUE,
    request_sha256 TEXT NOT NULL,
    frame_count INTEGER NOT NULL CHECK (frame_count BETWEEN 3 AND 16),
    encrypted_burst_payload BLOB NOT NULL,
    payload_nonce BLOB NOT NULL,
    captured_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    sync_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (sync_status IN ('PENDING', 'SYNCING', 'SYNCED', 'EXPIRED', 'FAILED')),
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    last_sync_error TEXT,
    created_at_utc TEXT NOT NULL,
    synced_at_utc TEXT
);

CREATE INDEX idx_offline_sync ON offline_burst_batches (sync_status, captured_at_utc);
CREATE INDEX idx_offline_expiry ON offline_burst_batches (expires_at_utc);
```

### 3.2 `sync_audit_log` Table
```sql
CREATE TABLE sync_audit_log (
    log_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    http_status INTEGER,
    response_body_snippet TEXT,
    FOREIGN KEY(batch_id) REFERENCES offline_burst_batches(batch_id) ON DELETE CASCADE
);
```

---

## 4. Reconnection and Sync Drain Protocol

```
   Offline Kiosk                   Connectivity Listener              Backend /api/v1
        |                                    |                               |
        | [Network drops]                    |                               |
        | Capture frames -> Encrypt ->       |                               |
        | Store in SQLCipher (PENDING)       |                               |
        | Show: "Captured Offline (Queued)"  |                               |
        |                                    |                               |
        |                                    | [Network returns ONLINE]      |
        |                                    +------------------------------>|
        |                                    | GET /health (Verify backend)  |
        |                                    |<------------------------------+
        |                                    | HTTP 200 OK                   |
        |                                    |                               |
        | Trigger Drain Worker <-------------+                               |
        |                                                                    |
        | Fetch oldest PENDING batch (FIFO)                                  |
        | Check: if now_utc > expires_at_utc -> Mark EXPIRED, drop payload   |
        |                                                                    |
        | If valid: Mark SYNCING                                             |
        | POST /api/v1/attendance/capture-batches -------------------------->|
        | (Headers: Idempotency-Key, Device Auth)                            |
        |                                                                    |
        | <------------------------------------------------------------------+
        | HTTP 202 Accepted / 200 OK                                         |
        |                                                                    |
        | Mark SYNCED                                                        |
        | Wipe encrypted_burst_payload & nonce from SQLCipher                |
        | Audit log entry recorded                                           |
```

### 4.1 Anti-Tamper and Expiry Rules
1. **24-Hour Expiration**: Batches older than 24 hours from `captured_at_utc` are marked `EXPIRED` locally and their payload BLOBs are securely overwritten with zeros (`PRAGMA secure_delete=ON`).
2. **Idempotency Preservation**: The `idempotency_key` generated on the physical device at capture time is preserved throughout offline storage and sent to the server. If the server already received the batch before a connection drop, the server returns the cached response without creating duplicate attendance events.
3. **Immediate Wipe on Acceptance**: Once the backend returns `HTTP 202` (or `SUCCEEDED` status), the kiosk wipes the payload immediately from local storage.

---

## 5. Verification Checklist (Gate 5 Sign-off)

- [x] Architecture schema and cryptographic key storage defined.
- [x] Fail-closed 24-hour expiration rule established.
- [x] Backend idempotency deduplication verified.
- [ ] Integration of `sqflite_sqlcipher` package into `pubspec.yaml` on Android hardware target.
- [ ] Physical network interruption test on Android tablet (Airplane mode toggle test).
