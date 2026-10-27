import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/core/url_guard.dart';

void main() {
  // This is the single rule shared by SearchResultModel.isLaunchable (which
  // greys out the Add to Feed button) and ChatbotRepository._requireHttpUrl
  // (which refuses to POST a hostile url to the tracker service). Pinning it
  // here is what stops the two call sites from drifting apart again.
  test('absolute web addresses are accepted', () {
    for (final url in const [
      'https://2b.com.eg/en/product-1.html',
      'http://example.com/product',
      'https://jiji.co.eg/deals/phone',
    ]) {
      expect(isHttpUrl(url), true, reason: url);
    }
  });

  test('everything else is refused', () {
    for (final url in const [
      '',
      ' ',
      '/products/1',
      'products/1',
      '2b.com.eg/en/product.html',
      'https://',
      'https:///no-host',
      'file:///etc/passwd',
      'data:text/html,<script>alert(1)</script>',
      'javascript:alert(1)',
      'tel:12345',
      'ftp://2b.com.eg/p/1',
      'app-store://deeplink',
      'not a url',
      'about:blank',
      'mailto:support@el72.com',
      '//2b.com.eg/p/1',
      'https:/2b.com.eg/p/1',
    ]) {
      expect(isHttpUrl(url), false, reason: url);
    }
  });

  test('a url with credentials or a fragment is still just an address', () {
    // The guard classifies, it does not sanitize: these are valid addresses
    // whose *content* the tracker service treats as an opaque string.
    expect(isHttpUrl('https://2b.com.eg/p/1?ref=affiliate'), true);
    expect(isHttpUrl('https://2b.com.eg/p/1#section'), true);
  });
}
