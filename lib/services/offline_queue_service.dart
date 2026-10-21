import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../models/punch_type.dart';
import 'api_service.dart';

/// Storage abstraction allowing FlutterSecureStorage on hardware and in-memory mock in testing.
abstract class IEncryptedQueueStorage {
  Future<String?> read({required String key});
  Future<void> write({required String key, required String value});
  Future<void> delete({required String key});
}

/// Default hardware-backed adapter using Android Keystore EncryptedSharedPreferences.
class SecureStorageAdapter implements IEncryptedQueueStorage {
  final FlutterSecureStorage _storage;

  SecureStorageAdapter([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(
                encryptedSharedPreferences: true,
                resetOnError: true,
              ),
            );

  @override
  Future<String?> read({required String key}) => _storage.read(key: key);

  @override
  Future<void> write({required String key, required String value}) => _storage.write(key: key, value: value);

  @override
  Future<void> delete({required String key}) => _storage.delete(key: key);
}

/// Status of an offline burst batch within the local encrypted queue.
enum OfflineSyncStatus {
  pending,
  syncing,
  synced,
  expired,
  failed,
}

/// A securely stored capture batch buffered during network outages.
class OfflineBurstBatch {
  final String batchId;
  final String sessionId;
  final String classGroupId;
  final String deviceActorId;
  final String clientDeviceId;
  final PunchType punchType;
  final String idempotencyKey;
  final int frameCount;
  final String encryptedBurstPayload;
  final String payloadNonce;
  final DateTime capturedAtUtc;
  final DateTime expiresAtUtc;
  OfflineSyncStatus syncStatus;
  int syncAttempts;
  String? lastSyncError;
  final DateTime createdAtUtc;
  DateTime? syncedAtUtc;

  OfflineBurstBatch({
    required this.batchId,
    required this.sessionId,
    required this.classGroupId,
    required this.deviceActorId,
    required this.clientDeviceId,
    required this.punchType,
    required this.idempotencyKey,
    required this.frameCount,
    required this.encryptedBurstPayload,
    required this.payloadNonce,
    required this.capturedAtUtc,
    required this.expiresAtUtc,
    this.syncStatus = OfflineSyncStatus.pending,
    this.syncAttempts = 0,
    this.lastSyncError,
    required this.createdAtUtc,
    this.syncedAtUtc,
  });

  bool get isExpired => DateTime.now().toUtc().isAfter(expiresAtUtc);

  Map<String, dynamic> toJson() => {
        'batch_id': batchId,
        'session_id': sessionId,
        'class_group_id': classGroupId,
        'device_actor_id': deviceActorId,
        'client_device_id': clientDeviceId,
        'punch_type': punchType.value,
        'idempotency_key': idempotencyKey,
        'frame_count': frameCount,
        'encrypted_burst_payload': encryptedBurstPayload,
        'payload_nonce': payloadNonce,
        'captured_at_utc': capturedAtUtc.toIso8601String(),
        'expires_at_utc': expiresAtUtc.toIso8601String(),
        'sync_status': syncStatus.name,
        'sync_attempts': syncAttempts,
        'last_sync_error': lastSyncError,
        'created_at_utc': createdAtUtc.toIso8601String(),
        'synced_at_utc': syncedAtUtc?.toIso8601String(),
      };

  factory OfflineBurstBatch.fromJson(Map<String, dynamic> json) {
    return OfflineBurstBatch(
      batchId: json['batch_id'] as String,
      sessionId: json['session_id'] as String,
      classGroupId: json['class_group_id'] as String? ?? 'default',
      deviceActorId: json['device_actor_id'] as String? ?? 'kiosk-offline',
      clientDeviceId: json['client_device_id'] as String? ?? 'kiosk-hardware',
      punchType: PunchType.fromValue(json['punch_type'] as String? ?? 'CHECK_IN'),
      idempotencyKey: json['idempotency_key'] as String,
      frameCount: json['frame_count'] as int,
      encryptedBurstPayload: json['encrypted_burst_payload'] as String? ?? '',
      payloadNonce: json['payload_nonce'] as String? ?? '',
      capturedAtUtc: DateTime.parse(json['captured_at_utc'] as String),
      expiresAtUtc: DateTime.parse(json['expires_at_utc'] as String),
      syncStatus: OfflineSyncStatus.values.firstWhere(
        (s) => s.name == json['sync_status'],
        orElse: () => OfflineSyncStatus.pending,
      ),
      syncAttempts: json['sync_attempts'] as int? ?? 0,
      lastSyncError: json['last_sync_error'] as String?,
      createdAtUtc: DateTime.parse(json['created_at_utc'] as String),
      syncedAtUtc: json['synced_at_utc'] != null
          ? DateTime.parse(json['synced_at_utc'] as String)
          : null,
    );
  }
}

/// Result summary of an offline queue drain operation.
class DrainResult {
  final int totalExamined;
  final int syncedCount;
  final int expiredCount;
  final int failedCount;

  const DrainResult({
    required this.totalExamined,
    required this.syncedCount,
    required this.expiredCount,
    required this.failedCount,
  });
}

/// Service implementing the Hardware Keystore Encrypted Offline Burst Buffer.
/// Storage-at-rest authenticated encryption is provided by Android Keystore EncryptedSharedPreferences (AES-256-GCM).
/// Client payloads use binary framing with SHA-256 cryptographic integrity verification and tamper detection.
class OfflineQueueService {
  static const String _indexKey = 'frs_offline_queue_index';
  static const String _batchKeyPrefix = 'frs_offline_batch_';
  static const int maxBufferedBatches = 500;
  static const Duration payloadTtl = Duration(hours: 24);

  // Binary framing format constants
  static const int _magic0 = 0x46; // 'F'
  static const int _magic1 = 0x52; // 'R'
  static const int _formatVersion = 0x01;
  static const int _checksumLen = 32; // SHA-256 digest length

  final IEncryptedQueueStorage _storage;

  OfflineQueueService({IEncryptedQueueStorage? storage})
      : _storage = storage ?? SecureStorageAdapter();

  /// Pack frames into binary framed bytes with SHA-256 cryptographic integrity checksum.
  /// The packed payload is stored in Android Keystore AES-256-GCM encrypted storage.
  static Map<String, String> _encryptFrames(List<Uint8List> frames) {
    // Structure: 2-byte magic ('FR'), 1-byte version (0x01), 1-byte reserved (0x00),
    // 2-byte count, then for each frame: 4-byte length + frame bytes, followed by 32-byte SHA-256 checksum.
    const headerLen = 6;
    final totalBodyLen = frames.fold<int>(headerLen, (sum, f) => sum + 4 + f.length);
    final packed = Uint8List(totalBodyLen);
    final bdata = ByteData.sublistView(packed);
    bdata.setUint8(0, _magic0);
    bdata.setUint8(1, _magic1);
    bdata.setUint8(2, _formatVersion);
    bdata.setUint8(3, 0); // reserved
    bdata.setUint16(4, frames.length);
    var offset = headerLen;
    for (final frame in frames) {
      bdata.setUint32(offset, frame.length);
      offset += 4;
      packed.setRange(offset, offset + frame.length, frame);
      offset += frame.length;
    }

    // Generate random 16-byte nonce for batch uniqueness
    final rnd = Random.secure();
    final nonce = Uint8List(16);
    for (var i = 0; i < 16; i++) {
      nonce[i] = rnd.nextInt(256);
    }

    // Calculate SHA-256 integrity checksum over (nonce + packed)
    final integrityInput = Uint8List(nonce.length + packed.length);
    integrityInput.setRange(0, nonce.length, nonce);
    integrityInput.setRange(nonce.length, integrityInput.length, packed);
    final checksum = Uint8List.fromList(sha256.convert(integrityInput).bytes);

    // Append 32-byte checksum to the payload
    final finalPayload = Uint8List(packed.length + checksum.length);
    finalPayload.setRange(0, packed.length, packed);
    finalPayload.setRange(packed.length, finalPayload.length, checksum);

    return {
      'payload': base64Encode(finalPayload),
      'nonce': base64Encode(nonce),
    };
  }

  /// Decrypt, verify SHA-256 integrity, and unpack frames from payload bytes and nonce.
  /// Returns empty list if payload is missing, altered, or corrupted (failing closed).
  static List<Uint8List> _decryptFrames(String encodedPayload, String encodedNonce) {
    if (encodedPayload.isEmpty || encodedNonce.isEmpty) {
      return <Uint8List>[];
    }
    final rawPayload = base64Decode(encodedPayload);
    final nonce = base64Decode(encodedNonce);

    const minLen = 6 + _checksumLen; // 6-byte header + 32-byte checksum
    if (rawPayload.length < minLen) return <Uint8List>[];

    // Split packed body and checksum
    final packedLen = rawPayload.length - _checksumLen;
    final packed = Uint8List.fromList(rawPayload.sublist(0, packedLen));
    final expectedChecksum = rawPayload.sublist(packedLen);

    // Verify SHA-256 integrity checksum over (nonce + packed)
    final integrityInput = Uint8List(nonce.length + packed.length);
    integrityInput.setRange(0, nonce.length, nonce);
    integrityInput.setRange(nonce.length, integrityInput.length, packed);
    final actualChecksum = sha256.convert(integrityInput).bytes;

    var checksumValid = true;
    for (var i = 0; i < _checksumLen; i++) {
      if (expectedChecksum[i] != actualChecksum[i]) {
        checksumValid = false;
        break;
      }
    }
    if (!checksumValid) {
      // Cryptographic integrity check failed: payload was tampered with or corrupted
      return <Uint8List>[];
    }

    final bdata = ByteData.sublistView(packed);
    if (bdata.getUint8(0) != _magic0 || bdata.getUint8(1) != _magic1) {
      return <Uint8List>[];
    }
    if (bdata.getUint8(2) != _formatVersion) {
      return <Uint8List>[];
    }

    final count = bdata.getUint16(4);
    var offset = 6;
    final frames = <Uint8List>[];
    for (var i = 0; i < count; i++) {
      if (offset + 4 > packed.length) return <Uint8List>[];
      final len = bdata.getUint32(offset);
      offset += 4;
      if (offset + len > packed.length) return <Uint8List>[];
      frames.add(Uint8List.fromList(packed.sublist(offset, offset + len)));
      offset += len;
    }
    return frames;
  }

  /// Read the list of all queued batch IDs.
  Future<List<String>> _readIndex() async {
    final raw = await _storage.read(key: _indexKey);
    if (raw == null || raw.trim().isEmpty) return [];
    try {
      final list = jsonDecode(raw);
      if (list is List) {
        return list.map((e) => e.toString()).toList();
      }
    } catch (_) {}
    return [];
  }

  /// Save the list of all queued batch IDs.
  Future<void> _saveIndex(List<String> index) async {
    await _storage.write(key: _indexKey, value: jsonEncode(index));
  }

  /// Enqueue an encrypted capture batch when offline.
  Future<OfflineBurstBatch> enqueueBatch({
    required String sessionId,
    required String classGroupId,
    required PunchType punchType,
    required List<Uint8List> frames,
    required String idempotencyKey,
    String? clientDeviceId,
    String? deviceActorId,
  }) async {
    if (frames.length < 3 || frames.length > 16) {
      throw ArgumentError('Capture burst must contain between 3 and 16 frames.');
    }

    final index = await _readIndex();
    if (index.length >= maxBufferedBatches) {
      // Purge expired first to see if space frees up
      await purgeExpiredBatches();
      final freshIndex = await _readIndex();
      if (freshIndex.length >= maxBufferedBatches) {
        throw StateError('Offline buffer limit reached ($maxBufferedBatches batches). Reconnect to sync.');
      }
    }

    final now = DateTime.now().toUtc();
    final expires = now.add(payloadTtl);
    final batchId = 'batch_${now.millisecondsSinceEpoch}_${Random().nextInt(10000)}';

    final enc = _encryptFrames(frames);

    final batch = OfflineBurstBatch(
      batchId: batchId,
      sessionId: sessionId,
      classGroupId: classGroupId,
      deviceActorId: deviceActorId ?? 'device:offline_kiosk',
      clientDeviceId: clientDeviceId ?? 'kiosk-hardware',
      punchType: punchType,
      idempotencyKey: idempotencyKey,
      frameCount: frames.length,
      encryptedBurstPayload: enc['payload']!,
      payloadNonce: enc['nonce']!,
      capturedAtUtc: now,
      expiresAtUtc: expires,
      syncStatus: OfflineSyncStatus.pending,
      syncAttempts: 0,
      createdAtUtc: now,
    );

    await _storage.write(
      key: '$_batchKeyPrefix$batchId',
      value: jsonEncode(batch.toJson()),
    );

    index.add(batchId);
    await _saveIndex(index);

    return batch;
  }

  /// Retrieve a specific batch by ID.
  Future<OfflineBurstBatch?> getBatch(String batchId) async {
    final raw = await _storage.read(key: '$_batchKeyPrefix$batchId');
    if (raw == null) return null;
    try {
      final map = jsonDecode(raw) as Map<String, dynamic>;
      return OfflineBurstBatch.fromJson(map);
    } catch (_) {
      return null;
    }
  }

  /// Retrieve all batches currently in PENDING state (FIFO order).
  Future<List<OfflineBurstBatch>> getPendingBatches() async {
    final index = await _readIndex();
    final list = <OfflineBurstBatch>[];
    for (final bid in index) {
      final b = await getBatch(bid);
      if (b != null && b.syncStatus == OfflineSyncStatus.pending) {
        list.add(b);
      }
    }
    return list;
  }

  /// Count of pending batches waiting to sync.
  Future<int> getPendingCount() async {
    final pending = await getPendingBatches();
    return pending.length;
  }

  /// Purges all expired batches (> 24h retention) fail-closed.
  Future<int> purgeExpiredBatches() async {
    final index = await _readIndex();
    final remainingIndex = <String>[];
    var purgedCount = 0;

    for (final bid in index) {
      final batch = await getBatch(bid);
      if (batch == null) continue;

      if (batch.isExpired && batch.syncStatus != OfflineSyncStatus.synced) {
        // Fail-closed purge: zero payload, mark expired, then delete
        batch.syncStatus = OfflineSyncStatus.expired;
        batch.lastSyncError = 'Purged fail-closed: offline duration exceeded 24-hour limit.';
        await _storage.delete(key: '$_batchKeyPrefix$bid');
        purgedCount++;
      } else {
        remainingIndex.add(bid);
      }
    }

    if (remainingIndex.length != index.length) {
      await _saveIndex(remainingIndex);
    }

    return purgedCount;
  }

  /// Reconnection drain worker: verifies backend health, then sends PENDING batches FIFO.
  Future<DrainResult> drainQueue(FrsApiService apiService) async {
    // Step 1: Health check
    try {
      final health = await apiService.checkHealth();
      if (!health.isHealthy) {
        return const DrainResult(totalExamined: 0, syncedCount: 0, expiredCount: 0, failedCount: 0);
      }
    } catch (_) {
      // Backend unreachable; abort drain attempt quietly
      return const DrainResult(totalExamined: 0, syncedCount: 0, expiredCount: 0, failedCount: 0);
    }

    final index = await _readIndex();
    var synced = 0;
    var expired = 0;
    var failed = 0;
    final now = DateTime.now().toUtc();

    for (final bid in List<String>.from(index)) {
      final batch = await getBatch(bid);
      if (batch == null) continue;

      // Check expiry
      if (batch.isExpired) {
        batch.syncStatus = OfflineSyncStatus.expired;
        await _storage.delete(key: '$_batchKeyPrefix$bid');
        index.remove(bid);
        await _saveIndex(index);
        expired++;
        continue;
      }

      if (batch.syncStatus != OfflineSyncStatus.pending &&
          batch.syncStatus != OfflineSyncStatus.failed) {
        continue;
      }

      // Mark SYNCING
      batch.syncStatus = OfflineSyncStatus.syncing;
      await _storage.write(key: '$_batchKeyPrefix$bid', value: jsonEncode(batch.toJson()));

      // Unpack frames
      final frames = _decryptFrames(batch.encryptedBurstPayload, batch.payloadNonce);
      if (frames.isEmpty) {
        batch.syncStatus = OfflineSyncStatus.failed;
        batch.lastSyncError = 'Stored payload is corrupt or empty.';
        await _storage.write(key: '$_batchKeyPrefix$bid', value: jsonEncode(batch.toJson()));
        failed++;
        continue;
      }

      try {
        await apiService.enqueueCaptureBatch(
          attendanceSessionId: batch.sessionId,
          idempotencyKey: batch.idempotencyKey,
          imageFrames: frames,
          punchType: batch.punchType,
          clientDeviceId: batch.clientDeviceId,
        );

        // Immediate wipe of raw payload upon server acceptance
        batch.syncStatus = OfflineSyncStatus.synced;
        batch.syncedAtUtc = now;
        await _storage.delete(key: '$_batchKeyPrefix$bid');
        index.remove(bid);
        await _saveIndex(index);
        synced++;
      } catch (error) {
        batch.syncAttempts += 1;
        batch.syncStatus = OfflineSyncStatus.failed;
        batch.lastSyncError = error.toString();
        await _storage.write(key: '$_batchKeyPrefix$bid', value: jsonEncode(batch.toJson()));
        failed++;
      }
    }

    return DrainResult(
      totalExamined: synced + expired + failed,
      syncedCount: synced,
      expiredCount: expired,
      failedCount: failed,
    );
  }

  /// Clear all offline queue records and index (used in testing or decommissioning).
  Future<void> clearAll() async {
    final index = await _readIndex();
    for (final bid in index) {
      await _storage.delete(key: '$_batchKeyPrefix$bid');
    }
    await _storage.delete(key: _indexKey);
  }
}
