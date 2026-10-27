import 'package:flutter_test/flutter_test.dart';

import 'package:elhaq_tracker/src/core/format/toast_title.dart';

void main() {
  // Both the chat page's toasts and the result card's "Unable to open" snackbar
  // render this string, and a scraped title can be arbitrarily long or contain
  // newlines. Pinning the helper here is what keeps those surfaces from
  // re-inventing their own (drifting) truncation rule.
  test('a short title is passed through unchanged', () {
    expect(
      toastTitle('Samsung Odyssey G5 27" 2K Monitor'),
      'Samsung Odyssey G5 27" 2K Monitor',
    );
  });

  test('whitespace, including newlines, collapses to single spaces', () {
    expect(
      toastTitle('  Deal   Found!\n\nHuge price drop  '),
      'Deal Found! Huge price drop',
    );
  });

  test('a long title is cut at the cap and marked with an ellipsis', () {
    final title = toastTitle('x' * 300);
    expect(title.length, maxToastTitleLength + 1);
    expect(title, '${'x' * maxToastTitleLength}…');
  });

  test('a title is measured after folding, not before', () {
    // 90 raw characters, but only 59 once the newlines collapse: it must
    // survive intact rather than being cut at the cap.
    final out = toastTitle('a\n\n' * 30);
    expect(out, 'a ' * 29 + 'a');
    expect(out.length, 59);
    expect(out.endsWith('…'), false);
  });

  test('a title that is only whitespace becomes empty', () {
    expect(toastTitle('   \n\t  '), '');
  });
}
