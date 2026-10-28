import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/ui/widgets/product_image.dart';

Widget _shell(String url) => MaterialApp(
  home: Scaffold(
    body: Center(child: ProductImage(imageUrl: url, size: 40)),
  ),
);

void main() {
  testWidgets('only absolute http/https images are fetched', (tester) async {
    // Image urls are scraped out of third-party pages. Anything that is not a
    // web address becomes the themed placeholder, so the app never requests a
    // data: blob, a local file, or a path a bare `httpfoo` prefix pretends to
    // be absolute.
    for (final url in const [
      '',
      'data:image/svg+xml,<svg onload="bad()">',
      'file:///etc/passwd',
      'httpfoo/bar.png',
      'https://',
      '/relative.png',
    ]) {
      await tester.pumpWidget(_shell(url));
      expect(find.byType(CachedNetworkImage), findsNothing, reason: url);
      expect(find.byType(Icon), findsOneWidget, reason: url);
    }

    await tester.pumpWidget(_shell('https://cdn.example.com/product.png'));
    expect(find.byType(CachedNetworkImage), findsOneWidget);
  });
}
