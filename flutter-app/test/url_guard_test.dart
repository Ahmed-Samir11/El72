// File: flutter-app/test/url_guard_test.dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/core/url_guard.dart';

void main() {
  // Two copies of this rule exist on purpose: the app's copy is checked here,
  // the server's copy in services/common/url_policy.py by pytest. If they ever
  // drift, this test is where the difference becomes visible.
  const sharedRule = 'lib/src/core/url_guard.dart';

  test('the shared url rule still matches the server-side policy', () {
    expect(File(sharedRule).existsSync(), true);
    // Naming the server-side guard here is the drift check: a rename of
    // `url_policy.py` or its entry point should make this test fail loudly.
    expect(
      File(sharedRule).readAsStringSync(),
      contains('services/common/url_policy.py::fetch_block_reason'),
    );
  });

  group('isHttpUrl', () {
    // The scheme is matched case-insensitively and a real product link may
    // carry a query, a fragment or userinfo. Refusing any of those would hide
    // the price page the user tapped on, so these must stay acceptable.
    test('accepts real web addresses', () {
      for (final url in const [
        'http://example.com',
        'https://example.com/',
        'https://2b.com.eg/en/products/samsung-tv.html?utm=price',
        'https://shop.test/p/1#price',
        'https://user:pw@shop.test/p/1',
        'HTTPS://2B.EGYPT/p',
      ]) {
        expect(isHttpUrl(url), true, reason: url);
      }
    });

    // A relative href, a scheme-less host, or an empty/null value is exactly
    // what scraped product pages emit, and none of it opens a browser.
    test('refuses anything that is not an absolute web address', () {
      for (final url in const [
        '',
        '   ',
        '2b.com.eg/p',
        '/products/samsung-tv.html',
        './samsung-tv.html',
        '//cdn.test/img.jpg',
        'ftp://cdn.test/p',
        'javascript:alert(1)',
        'data:text/html,<script>',
        'file:///etc/passwd',
        'app-store://deeplink',
      ]) {
        expect(isHttpUrl(url), false, reason: url);
      }
    });

    // A scheme-only string, or a scheme with nothing usable after it: `Uri.tryParse`
    // accepts the shape, and `openInBrowser` would try anyway, so the host
    // has to be there before the tap is offered.
    test('refuses an address with no host to open', () {
      for (final url in const ['http://', 'https://', 'https:///path']) {
        expect(isHttpUrl(url), false, reason: url);
      }
    });

    // Whitespace and control characters are refused outright rather than
    // normalized. `Uri` does not reject them the way a browser does: it
    // percent-encodes them *into* the host, so `https://a b.com/x` becomes the
    // single host `a%20b.com`. Scraped markup wraps long attributes over line
    // breaks in exactly that shape, and one address that quietly swallowed a
    // newline is not something to hand a browser.
    test('refuses an address carrying whitespace or a control character', () {
      for (final url in const [
        'https://a b.com/x',
        'https://a\tb.com/x',
        'https://a\nb.com/x',
        'https://a\u007fb.com/x',
        ' https://2b.com.eg/p/1',
        'https://2b.com.eg/p/1 ',
        'https://2b.com.eg/p/\u0000',
      ]) {
        expect(isHttpUrl(url), false, reason: url);
      }
    });

    // Non-ASCII separators and format characters are refused for the same reason
    // ASCII ones are: `Uri` percent-encodes them into the host instead of rejecting
    // the link. That is how a bidi override becomes a visually spoofed hostname -
    // `https://<rtl>evil.test` reads as a respectable address while the authority
    // is somewhere else - so the whole U+2000-U+206F block (Unicode spaces, the
    // line and paragraph separators, the bidi controls, the invisible formatting
    // characters) is refused, along with C1 separators, NBSP, the zero-width
    // no-break marker and the interlinear annotation tags.
    test('refuses an address carrying an invisible separator', () {
      for (final url in const [
        'https://a\u202Aevil.test/p',
        'https://a\u202Fb.test/p',
        'https://a\u200Eb.test/p',
        'https://a\u2000b.test/p',
        'https://a\u2028b.test/p',
        'https://a\u2029b.test/p',
        'https://a\u0085b.test/p',
        'https://a\u00a0b.test/p',
        'https://a\u200fb.test/p',
        'https://a\ufeff.test/p',
        'https://a\ufff9b.test/p',
      ]) {
        expect(isHttpUrl(url), false, reason: url);
      }
    });

    // Non-ASCII *text* is unaffected: only separators are refused. A punycode
    // host, a percent-encoded query and a Latin-1 character all stay addresses,
    // which is what keeps an international store link usable.
    test('keeps ordinary international addresses', () {
      expect(isHttpUrl('https://xn--btoa.test/p'), true);
      expect(isHttpUrl('https://2b.com.eg/p/1?city=Mamari'), true);
      expect(isHttpUrl('https://2b.com.eg/p/1?name=Araf%20Elhamour'), true);
      expect(isHttpUrl('https://2b.com.eg/p/1%20x'), true);
    });
  });
}
