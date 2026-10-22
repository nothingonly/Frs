import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:kiosk_app/config/app_config.dart';
import 'package:kiosk_app/models/punch_type.dart';
import 'package:kiosk_app/services/api_service.dart';
import 'package:kiosk_app/services/offline_queue_service.dart';

class FakeEncryptedStorage implements IEncryptedQueueStorage {
  final Map<String, String> _data = {};

  @override
  Future<String?> read({required String key}) async => _data[key];

  @override
  Future<void> write({required String key, required String value}) async => _data[key] = value;

  @override
  Future<void> delete({required String key}) async => _data.remove(key);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late FakeEncryptedStorage fakeStorage;
  late OfflineQueueService queueService;

  setUp(() {
    fakeStorage = FakeEncryptedStorage();
    queueService = OfflineQueueService(storage: fakeStorage);
  });

  group('OfflineQueueService', () {
    test('enforces backend-compatible frame count validation (between 3 and 8 frames)', () async {
      final oneFrame = [Uint8List.fromList([1, 2, 3])];
      expect(
        () => queueService.enqueueBatch(
          sessionId: 'sess-1',
          classGroupId: 'cg-1',
          punchType: PunchType.checkIn,
          frames: oneFrame,
          idempotencyKey: 'idemp-123456789012',
        ),
        throwsA(isA<ArgumentError>()),
      );
      final nineFrames = List<Uint8List>.generate(
        9, (index) => Uint8List.fromList([index + 1, index + 2, index + 3]),
      );
      await expectLater(
        queueService.enqueueBatch(
          sessionId: 'sess-too-many',
          classGroupId: 'cg-1',
          punchType: PunchType.checkIn,
          frames: nineFrames,
          idempotencyKey: 'idemp-too-many-123456',
        ),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('enqueues encrypted batch and preserves idempotency key', () async {
      final frames = [
        Uint8List.fromList([1, 2, 3, 4]),
        Uint8List.fromList([5, 6, 7, 8]),
        Uint8List.fromList([9, 10, 11, 12]),
      ];

      final batch = await queueService.enqueueBatch(
        sessionId: 'sess-cse-101',
        classGroupId: 'cg-cse-3a',
        punchType: PunchType.checkIn,
        frames: frames,
        idempotencyKey: 'idemp-offline-987654321',
      );

      expect(batch.batchId, startsWith('batch_'));
      expect(batch.sessionId, equals('sess-cse-101'));
      expect(batch.classGroupId, equals('cg-cse-3a'));
      expect(batch.idempotencyKey, equals('idemp-offline-987654321'));
      expect(batch.frameCount, equals(3));
      expect(batch.encryptedBurstPayload, isNotEmpty);
      expect(batch.payloadNonce, isNotEmpty);
      expect(batch.syncStatus, equals(OfflineSyncStatus.pending));

      // Batch is stored in secure storage
      final storedBatch = await queueService.getBatch(batch.batchId);
      expect(storedBatch, isNotNull);
      expect(storedBatch!.idempotencyKey, equals('idemp-offline-987654321'));

      final pending = await queueService.getPendingBatches();
      expect(pending.length, equals(1));
    });

    test('fail-closed 24-hour expiration purges old batches', () async {
      final frames = [
        Uint8List.fromList([1, 2, 3]),
        Uint8List.fromList([4, 5, 6]),
        Uint8List.fromList([7, 8, 9]),
      ];

      final batch = await queueService.enqueueBatch(
        sessionId: 'sess-old',
        classGroupId: 'cg-old',
        punchType: PunchType.checkIn,
        frames: frames,
        idempotencyKey: 'idemp-expired-123456',
      );

      // Artificially age the batch past 24 hours
      final oldJson = batch.toJson();
      oldJson['expires_at_utc'] = DateTime.now().toUtc().subtract(const Duration(hours: 2)).toIso8601String();
      await fakeStorage.write(
        key: 'frs_offline_batch_${batch.batchId}',
        value: jsonEncode(oldJson),
      );

      final agedBatch = await queueService.getBatch(batch.batchId);
      expect(agedBatch!.isExpired, isTrue);

      final purged = await queueService.purgeExpiredBatches();
      expect(purged, equals(1));

      // Key should now be purged from storage
      final postPurge = await queueService.getBatch(batch.batchId);
      expect(postPurge, isNull);

      final pendingAfter = await queueService.getPendingBatches();
      expect(pendingAfter.isEmpty, isTrue);
    });

    test('clearAll wipes index and all buffered batches', () async {
      final frames = [
        Uint8List.fromList([1, 2, 3]),
        Uint8List.fromList([4, 5, 6]),
        Uint8List.fromList([7, 8, 9]),
      ];

      await queueService.enqueueBatch(
        sessionId: 'sess-1',
        classGroupId: 'cg-1',
        punchType: PunchType.checkIn,
        frames: frames,
        idempotencyKey: 'idemp-clear-12345678',
      );

      expect(await queueService.getPendingCount(), equals(1));
      await queueService.clearAll();
      expect(await queueService.getPendingCount(), equals(0));
    });

    test('drainQueue recovers a batch left syncing by a crash and wipes local payload', () async {
      final frames = [
        Uint8List.fromList([1, 2, 3]),
        Uint8List.fromList([4, 5, 6]),
        Uint8List.fromList([7, 8, 9]),
      ];

      final batch = await queueService.enqueueBatch(
        sessionId: 'sess-drain-1',
        classGroupId: 'cg-1',
        punchType: PunchType.checkIn,
        frames: frames,
        idempotencyKey: 'idemp-drain-12345678',
      );

      expect(await queueService.getPendingCount(), equals(1));

      // Simulate process death after the persisted status changed to SYNCING but before
      // the HTTP request completed. A future drain must replay the request idempotently.
      final storedRaw = await fakeStorage.read(key: 'frs_offline_batch_${batch.batchId}');
      final stuckMap = jsonDecode(storedRaw!) as Map<String, dynamic>;
      stuckMap['sync_status'] = 'syncing';
      await fakeStorage.write(
        key: 'frs_offline_batch_${batch.batchId}',
        value: jsonEncode(stuckMap),
      );

      // Mock API service using custom http client
      var enqueuedSession = '';
      var enqueuedIdempotency = '';

      final client = _MockHttpClient((request) async {
        if (request.url.path == '/health') {
          return http.Response(
            jsonEncode({
              'status': 'online',
              'database': 'healthy',
              'ready_for_attendance': true,
              'environment': 'development',
              'model_version': 'v5',
              'similarity_threshold': 0.72,
              'threshold_status': 'CALIBRATED',
              'liveness_required': true,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path.contains('/batches')) {
          final multipart = request as http.MultipartRequest;
          enqueuedIdempotency = multipart.fields['idempotency_key'] ?? '';
          enqueuedSession = request.url.pathSegments[4]; // /api/v1/attendance/sessions/{id}/batches
          return http.Response(
            jsonEncode({
              'batch_id': 'server_batch_999',
              'attendance_session_id': enqueuedSession,
              'class_group_id': 'cg-1',
              'status': 'QUEUED',
              'punch_type': 'CHECK_IN',
              'frame_count': 3,
              'attempts': 0,
              'payload_available': true,
              'session_open': true,
              'created_at': DateTime.now().toIso8601String(),
              'updated_at': DateTime.now().toIso8601String(),
            }),
            202,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final api = FrsApiService(
        config: const AppConfig(
          apiBaseUrl: 'http://localhost:8000',
          apiKeySecret: 'test-device-credential-32chars-min',
          clientDeviceId: 'TEST_KIOSK_01',
          allowInsecureDevelopmentHttp: true,
        ),
        client: client,
      );

      final drainResult = await queueService.drainQueue(api);

      expect(drainResult.syncedCount, equals(1));
      expect(drainResult.failedCount, equals(0));
      expect(enqueuedSession, equals('sess-drain-1'));
      expect(enqueuedIdempotency, equals('idemp-drain-12345678'));

      // Queue is now empty, payload was purged immediately
      expect(await queueService.getPendingCount(), equals(0));
      final syncedBatch = await queueService.getBatch(batch.batchId);
      expect(syncedBatch, isNull);
    });

    test('drainQueue aborts quietly when backend is unhealthy', () async {
      final frames = [
        Uint8List.fromList([1, 2, 3]),
        Uint8List.fromList([4, 5, 6]),
        Uint8List.fromList([7, 8, 9]),
      ];

      await queueService.enqueueBatch(
        sessionId: 'sess-drain-unhealthy',
        classGroupId: 'cg-1',
        punchType: PunchType.checkIn,
        frames: frames,
        idempotencyKey: 'idemp-unhealthy-12345678',
      );

      final client = _MockHttpClient((request) async {
        return http.Response('Service Unavailable', 503);
      });

      final api = FrsApiService(
        config: const AppConfig(
          apiBaseUrl: 'http://localhost:8000',
          apiKeySecret: 'test-device-credential-32chars-min',
          clientDeviceId: 'TEST_KIOSK_01',
          allowInsecureDevelopmentHttp: true,
        ),
        client: client,
      );

      final drainResult = await queueService.drainQueue(api);
      expect(drainResult.syncedCount, equals(0));
      expect(drainResult.totalExamined, equals(0));

      // Batch remains safely pending in encrypted offline queue
      expect(await queueService.getPendingCount(), equals(1));
    });

    test('tampered payload fails SHA-256 integrity verification and fails closed', () async {
      final frames = [
        Uint8List.fromList([1, 2, 3]),
        Uint8List.fromList([4, 5, 6]),
        Uint8List.fromList([7, 8, 9]),
      ];

      final batch = await queueService.enqueueBatch(
        sessionId: 'sess-tamper',
        classGroupId: 'cg-1',
        punchType: PunchType.checkIn,
        frames: frames,
        idempotencyKey: 'idemp-tamper-12345678',
      );

      // Tamper with the raw bytes in storage
      final storedRaw = await fakeStorage.read(key: 'frs_offline_batch_${batch.batchId}');
      final map = jsonDecode(storedRaw!) as Map<String, dynamic>;
      final bytes = base64Decode(map['encrypted_burst_payload'] as String);
      bytes[10] ^= 0xFF; // Alter payload byte
      map['encrypted_burst_payload'] = base64Encode(bytes);
      await fakeStorage.write(key: 'frs_offline_batch_${batch.batchId}', value: jsonEncode(map));

      // Attempt drain: must fail because the payload is corrupt/tampered
      final client = _MockHttpClient((request) async {
        if (request.url.path == '/health') {
          return http.Response(
            jsonEncode({
              'status': 'online',
              'database': 'healthy',
              'ready_for_attendance': true,
              'environment': 'development',
              'model_version': 'v5',
              'similarity_threshold': 0.72,
              'threshold_status': 'CALIBRATED',
              'liveness_required': true,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('OK', 200);
      });
      final api = FrsApiService(
        config: const AppConfig(
          apiBaseUrl: 'http://localhost:8000',
          apiKeySecret: 'test-device-credential-32chars-min',
          clientDeviceId: 'TEST_KIOSK_01',
          allowInsecureDevelopmentHttp: true,
        ),
        client: client,
      );

      final result = await queueService.drainQueue(api);
      expect(result.failedCount, equals(1));
      expect(result.syncedCount, equals(0));

      final failedBatch = await queueService.getBatch(batch.batchId);
      expect(failedBatch!.syncStatus, equals(OfflineSyncStatus.failed));
      expect(failedBatch.lastSyncError, contains('corrupt'));
    });
  });
}

class _MockHttpClient extends http.BaseClient {
  final Future<http.Response> Function(http.BaseRequest request) _handler;

  _MockHttpClient(this._handler);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final response = await _handler(request);
    return http.StreamedResponse(
      Stream.value(response.bodyBytes),
      response.statusCode,
      headers: response.headers,
    );
  }
}
