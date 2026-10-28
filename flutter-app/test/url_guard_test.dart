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
    // A scheme is folded to lower case by `Uri`, so an uppercase product link
    // scraped from a page is still openable.
    expect(isHttpUrl('HTTPS://noon.com/p/1'), true);
  });

  test('whitespace or a control character inside an address is refused', () {
    // `Uri.tryParse` does not reject these: it percent-encodes the character
    // into the host, so `https://a b.com/x` becomes the single host
    // `a%20b.com`. Scraped markup wraps long attributes over line breaks in
    // exactly that shape, and one address that quietly swallowed a newline is
    // not something to hand a browser.
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

    // A real link percent-encodes its own spaces, and stays acceptable.
    expect(isHttpUrl('https://2b.com.eg/p/1%20x'), true);

    // Non-ASCII separators and zero-width characters are refused for the same
    // reason: `Uri` percent-encodes them into the host instead of rejecting the
    // link, so a scraped value that carried one becomes one odd address.
    for (final url in const [
      'https://a\u2028b.test/p',
      'https://a\u2029b.test/p',
      'https://a\u0085b.test/p',
      'https://a\u00a0b.test/p',
      'https://a\u200fb.test/p',
      'https://a\ufeff.test/p',
    ]) {
      expect(isHttpUrl(url), false, reason: url);
    }

    // Ordinary international hostnames are unaffected: they are percent-encoded
    // by the parser and stay real addresses.
    expect(isHttpUrl('https://xn--btoa.test/p'), true);
    expect(isHttpUrl('https://2b.com.eg/p/1?name=Araf%20Elhamour'), true);
  });
}
