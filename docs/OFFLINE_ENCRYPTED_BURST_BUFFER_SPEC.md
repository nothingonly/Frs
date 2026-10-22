# FRS Android Offline Burst Buffer — Current Implementation

**Document ID:** FRS-SPEC-GATE05-01  
**Component:** Flutter Android kiosk (kiosk_app)  
**Status:** Implementation description and acceptance checklist — not a SQLCipher implementation

## 1. Purpose

The kiosk buffers camera bursts during network outages and submits them to the FRS backend after connectivity returns. Every batch has a stable idempotency key and expires after 24 hours. A successful server acceptance causes the local batch record to be deleted.

## 2. Current storage boundary

The current code uses flutter_secure_storage configured with Android encryptedSharedPreferences: true. Each queue record, including the serialized capture-frame payload and its metadata, is stored as a value under a frs_offline_batch_<id> key. The ordered key list is stored under frs_offline_queue_index.

Important accuracy note: **the current implementation does not use SQLCipher, an encrypted SQLite queue database, or a separately managed application AES key for each burst**. Those mechanisms were in an earlier proposed blueprint but are not implemented by the current queue code. The secure-storage plugin manages its own at-rest protection. Actual device/OS key protection must be checked on the target tablet fleet; the code alone does not prove StrongBox/TEE availability.

## 3. Frame format and validation

The queue packs a burst into a binary frame:

- Magic bytes: FR
- Format version: 0x01
- Reserved byte: 0x00
- Frame count: unsigned 16-bit integer
- Repeated frames: unsigned 32-bit byte length followed by frame bytes
- Trailing SHA-256 checksum over a random 16-byte integrity nonce followed by the packed frame body

The nonce above is a checksum input, **not an encryption nonce**. The SHA-256 checksum is unkeyed and is used for detecting accidental corruption/invalid framing; it is not a standalone message-authentication scheme. Confidentiality and at-rest authentication depend on the encrypted secure-storage value.

The client accepts 3–8 frames per batch to match the backend's default configured limit, limits each frame to 5 MiB, and caps a burst at 40 MiB. The decoder rejects invalid Base64, wrong nonce lengths, unsupported versions, unexpected reserved bits, invalid frame counts/lengths, excessive payload sizes, and trailing bytes. Invalid queue payloads are never uploaded.

## 4. Queue and retry behavior

- Maximum indexed batches: 500.
- Queue retention: 24 hours.
- Queue order: FIFO by index order.
- States: pending, syncing, synced, expired, failed.
- A persisted syncing state is retryable after process death because the previous network request may not have completed.
- The same idempotency key is reused when retrying an uncertain request.
- Missing records in the index are removed during queue scans/drains.
- A corrupt payload is marked failed and its unusable frame bytes are wiped from the stored record.
- The record and queue index are written in an order intended to avoid leaving unindexed biometric payloads after a process interruption.
- Expired batches and server-accepted batches are deleted from secure storage.

## 5. Required demo/device acceptance

Before relying on the queue for real attendance, test on the supported Android tablet(s):

1. Capture a burst while online, then with the network disabled.
2. Kill the app between index and batch writes, during sync-state persistence, during upload, and after server acceptance but before local deletion.
3. Restore network and verify no lost or duplicate attendance records.
4. Validate a full queue, a corrupted/malformed record, an inaccessible secure-storage key, and an expired batch.
5. Confirm expired and accepted frames are removed from the device's secure storage.
6. Verify lock-task / kiosk recovery and camera permissions on actual managed hardware.

A passing unit test or the use of encrypted SharedPreferences does not by itself establish secure device provisioning, durable synchronization on every Android version, or institutional production acceptance.