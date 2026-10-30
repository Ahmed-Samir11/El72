import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/core/url_guard.dart';
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
  }) async {
    calls.add(
      ResolvedCall(
        targetUrl: targetUrl,
        source: source,
        sku: sku,
        dealId: dealId,
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
  });

  final String targetUrl;
  final String source;
  final String? sku;
  final String? dealId;
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

    test('a server answer that is not a web url cannot block or steer the '
        'tap: the ORIGINAL url is opened', () async {
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
        true,
      );
      expect(launched.single.toString(), 'https://www.amazon.eg/dp/ABC123');
    });

    test(
      'a web Location off the merchant allowlist is ignored, not opened',
      () async {
        // The endpoint is asked to answer with a tagged merchant URL. A
        // misconfigured or hostile answer steering the OS launch onto another
        // domain must not be honored — the user gets the URL they tapped.
        final launched = <Uri>[];
        final link = MerchantLink(
          repository: _RecordingRepository(
            resolvesTo: 'https://evil.example/steer?tag=el72-20',
          ),
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
          true,
        );
        expect(launched.single.toString(), 'https://www.amazon.eg/dp/ABC123');
      },
    );

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

  group('isMerchantUrl — the gate on the server Location', () {
    test('supported merchants and their subdomains pass', () {
      expect(isMerchantUrl('https://www.amazon.eg/dp/X'), true);
      expect(isMerchantUrl('https://amazon.eg/dp/X'), true);
      expect(isMerchantUrl('https://www.noon.com/egypt-en/item/P9'), true);
      expect(isMerchantUrl('https://www.jumia.com.eg/ml-product/x'), true);
    });

    test('lookalikes, other hosts and non-web urls are refused', () {
      for (final url in const [
        'https://evil.example/x',
        'https://amazon.eg.attacker.com/x', // suffix-trap on the WRONG side
        'https://redirector.test/next?u=https://www.noon.com/x',
        'http://localhost/x',
        'app-store://noon.com',
        '/egypt-en/relative',
        '',
      ]) {
        expect(isMerchantUrl(url), false, reason: url);
      }
    });
  });
}
