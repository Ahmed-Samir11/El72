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

  test('a long title is cut to the cap, ellipsis included', () {
    final title = toastTitle('x' * 300);
    // The cap is the whole line the user sees. Cutting at the cap and *appending*
    // an ellipsis used to make the toast one character longer than the limit
    // every caller and the doc comment promise.
    expect(title.length, maxToastTitleLength);
    expect(title, '${'x' * (maxToastTitleLength - 1)}…');
  });

  test('a title at exactly the cap is left whole', () {
    final exact = 'y' * maxToastTitleLength;
    expect(toastTitle(exact), exact);
  });

  test('a title is measured after folding, not before', () {
    // 90 raw characters, but only 59 once the newlines collapse: it must
    // survive intact rather than being cut at the cap.
    final out = toastTitle('a\n\n' * 30);
    expect(out, 'a ' * 29 + 'a');
    expect(out.length, 59);
    expect(out.endsWith('…'), false);
  });

  test('truncating never splits a surrogate pair', () {
    // substring counts UTF-16 code units, so the cut can land between the halves
    // of a pair — every emoji and most non-BMP text — and a lone surrogate
    // renders as the replacement glyph at the end of the toast.
    const emoji = '👁️'; // ZWJ sequence, three code units.
    final filler = 'A' * (maxToastTitleLength - 2);
    final title = '$filler${emoji}tail';
    final out = toastTitle(title);

    // The cut would land between the halves of the emoji's first pair, so that
    // pair is dropped whole: the line sits one character under the cap, which
    // beats shipping a lone surrogate that renders as the replacement glyph.
    expect(out, '$filler…');
    expect(out.length, maxToastTitleLength - 1);

    // Whatever was kept must be valid text: no unpaired surrogate anywhere.
    // `codeUnits` is the only way to see the halves at all, since a lone
    // surrogate cannot be written as a string literal here.
    final units = out.codeUnits;
    for (var i = 0; i < units.length; i++) {
      final unit = units[i];
      if ((unit & 0xfc00) != 0xd800) continue;
      final next = i + 1 < units.length ? units[i + 1] : 0;
      expect(
        (next & 0xfc00) == 0xdc00,
        true,
        reason: 'surrogate pair split at $i',
      );
    }
  });

  test('a title that is only whitespace becomes empty', () {
    expect(toastTitle('   \n\t  '), '');
  });

  // The service's own explanation of a failed add-to-tracker is remote text too,
  // and it reaches the same snackbar; it is bounded here so the chat page does
  // not grow a second, drifting copy of the rule.
  test('a page-sized failure message becomes one bounded line', () {
    final hostile = "couldn't reach ${'store\n' * 400}";
    final out = toastMessage(hostile);
    expect(out.length, maxToastTitleLength);
    expect(out.contains('\n'), false);
    expect(out.endsWith('…'), true);
  });

  test('a short failure message keeps its wording and loses padding', () {
    expect(
      toastMessage('  no results for that session  '),
      'no results for that session',
    );
  });
}
