import 'package:ai_trafficos/models/health_status.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('HealthStatus', () {
    test('parses ok status correctly and reports isHealthy = true', () {
      final json = {
        'status': 'ok',
        'service': 'ai-trafficos-backend',
        'version': '0.1.0',
        'timestamp': '2026-10-06T12:00:00Z',
      };

      final health = HealthStatus.fromJson(json);

      expect(health.status, 'ok');
      expect(health.service, 'ai-trafficos-backend');
      expect(health.version, '0.1.0');
      expect(health.isHealthy, isTrue);
      expect(health.timestamp, DateTime.parse('2026-10-06T12:00:00Z'));
    });

    test('parses healthy status correctly and reports isHealthy = true', () {
      final json = {
        'status': 'Healthy',
        'service': 'traffic-api',
        'version': '1.2.0',
      };

      final health = HealthStatus.fromJson(json);

      expect(health.status, 'Healthy');
      expect(health.isHealthy, isTrue);
    });

    test('parses degraded or error status and reports isHealthy = false', () {
      final json = {
        'status': 'degraded',
        'service': 'traffic-api',
        'version': '1.2.0',
      };

      final health = HealthStatus.fromJson(json);

      expect(health.isHealthy, isFalse);
    });

    test('copyWith updates properties properly', () {
      const original = HealthStatus(
        status: 'ok',
        service: 'test-svc',
        version: '1.0.0',
      );

      final updated = original.copyWith(status: 'offline', version: '2.0.0');

      expect(updated.status, 'offline');
      expect(updated.version, '2.0.0');
      expect(updated.service, 'test-svc');
    });
  });
}
