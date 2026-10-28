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

  // `clip` is public and takes its bound from the caller, so a caller asking
  // for "no room" must not get an index error out of the surrogate check.
  test('clipping to a tiny limit returns nothing rather than throwing', () {
    expect(clip('abcdef', 0), '');
    // A negative bound is the same request from a caller that has no room at
    // all; the old code indexed `codeUnits[-1]` here and threw.
    expect(clip('abcdef', -3), '');
    expect(clip('abcdef', 1), 'a');
    expect(clip('', 5), '');
  });

  test('clipping to one character never splits a pair', () {
    // The single kept unit is the leading half of the pair, so the pair is
    // dropped whole instead of leaving a lone surrogate behind.
    final pair = '\u{1f600}';
    expect(clip(pair, 1), '');
    expect(clip('$pair-tail', 2), pair);
  });

  // The fold that turns a title into one line used to run over the entire
  // payload before anything was thrown away, so a megabyte title spent a
  // megabyte of work (and a full copy of the text) to decide on 80 characters.
  test('the fold only ever reads a bounded window of a hostile title', () {
    final out = toastTitle('x' * 1000000);
    expect(out.length, maxToastTitleLength);
    expect(out.contains('\n'), false);

    // Observable proof the window is applied rather than merely measured: content
    // that starts past the window (8x the cap = 640 units) never reaches the
    // fold, so a payload front-loaded with whitespace yields nothing. Without
    // the window the whole 100k units would be folded and "Real title" would
    // survive.
    final buried = '${'\n' * 100000}Real title';
    expect(toastTitle(buried), '');
  });

  test('the window is generous enough for ordinary whitespace padding', () {
    // 400 units of newlines is well inside the window, so the fold still
    // collapses them and the title is shown whole.
    final padded = '${'\n\t' * 200}Samsung Odyssey G5';
    expect(toastTitle(padded), 'Samsung Odyssey G5');
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
