import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/data/repositories/affiliate_repository.dart';
import 'package:elhaq_tracker/src/ui/common/merchant_link.dart';

/// Records every resolve call and answers with a canned tagged URL (or
/// whatever [resolvesTo] says), so the test can assert the resolve happens
/// before any launch and carries the right surface/sku/deal context.
class _RecordingRepository extends AffiliateRepository {
  _RecordingRepository({String? resolvesTo, this.throwOnResolve = false})
    : _resolvesTo = resolvesTo;

  final String? _resolvesTo;
  final bool throwOnResolve;

  final List<ResolvedCall> calls = [];

  @override
  Future<String> resolve({
    required String targetUrl,
    required String source,
    String? sku,
    String? dealId,
    String? category,
  }) async {
    calls.add(
      ResolvedCall(
        targetUrl: targetUrl,
        source: source,
        sku: sku,
        dealId: dealId,
        category: category,
      ),
    );
    if (throwOnResolve) {
      // The real repository never throws; a broken subclass must still be
      // survivable for the card behind MerchantLink.
      throw Exception('repository exploded');
    }
    return _resolvesTo ?? 'https://www.amazon.eg/dp/ABC123?tag=el72-20';
  }
}

class ResolvedCall {
  ResolvedCall({
    required this.targetUrl,
    required this.source,
    this.sku,
    this.dealId,
    this.category,
  });

  final String targetUrl;
  final String source;
  final String? sku;
  final String? dealId;
  final String? category;
}

void main() {
  group('MerchantLink.open', () {
    test('resolves through the affiliate endpoint before launching, '
        'then launches the TAGGED URL', () async {
      final launched = <Uri>[];
      final repo = _RecordingRepository();
      final link = MerchantLink(
        repository: repo,
        launcher: (uri) async {
          launched.add(uri);
          return true;
        },
      );

      final opened = await link.open(
        targetUrl: 'https://www.amazon.eg/dp/ABC123?ref=search',
        source: 'deal_feed',
        sku: 'ABC123',
        dealId: 'deal-7',
      );

      expect(opened, true);
      expect(repo.calls, hasLength(1));
      expect(repo.calls.single.source, 'deal_feed');
      expect(repo.calls.single.sku, 'ABC123');
      expect(repo.calls.single.dealId, 'deal-7');
      // What the user opens is the server's tagged URL — that is the
      // monetized tap (plan p1 Definition of Done).
      expect(
        launched.single.toString(),
        'https://www.amazon.eg/dp/ABC123?tag=el72-20',
      );
    });

    test('a non-web url never reaches the endpoint or the launcher', () async {
      final launched = <Uri>[];
      final repo = _RecordingRepository();
      final link = MerchantLink(
        repository: repo,
        launcher: (uri) async {
          launched.add(uri);
          return true;
        },
      );

      for (final url in const [
        '',
        'file:///etc/passwd',
        'data:text/html,<script>alert(1)</script>',
        'javascript:alert(1)',
        'app-store://deeplink',
        'not a url',
      ]) {
        final opened = await link.open(targetUrl: url, source: 'web');
        expect(opened, false, reason: url);
      }
      expect(repo.calls, isEmpty);
      expect(launched, isEmpty);
    });

    test('a server answer that is not a web url is refused', () async {
      final launched = <Uri>[];
      final link = MerchantLink(
        repository: _RecordingRepository(resolvesTo: 'app-store://hijacked'),
        launcher: (uri) async {
          launched.add(uri);
          return true;
        },
      );

      expect(
        await link.open(
          targetUrl: 'https://www.amazon.eg/dp/ABC123',
          source: 'search_result',
        ),
        false,
      );
      expect(launched, isEmpty);
    });

    test('a throwing launcher is reported, not propagated', () async {
      final link = MerchantLink(
        repository: _RecordingRepository(),
        launcher: (uri) async => throw Exception('no handler installed'),
      );

      expect(
        await link.open(
          targetUrl: 'https://www.amazon.eg/dp/ABC123',
          source: 'tracker_card',
        ),
        false,
      );
    });

    test('the tap survives even a broken repository', () async {
      // Defensive: the real AffiliateRepository swallows everything, but a
      // card tap must never be able to throw whatever the repository
      // becomes. The card shows its unableToOpen snackbar instead.
      final launched = <Uri>[];
      final link = MerchantLink(
        repository: _RecordingRepository(throwOnResolve: true),
        launcher: (uri) async {
          launched.add(uri);
          return true;
        },
      );

      expect(
        await link.open(
          targetUrl: 'https://www.amazon.eg/dp/ABC123',
          source: 'tracker_card',
        ),
        // The tap still happens — the ORIGINAL URL is opened.
        true,
      );
      expect(launched.single.toString(), 'https://www.amazon.eg/dp/ABC123');
    });
  });
}
