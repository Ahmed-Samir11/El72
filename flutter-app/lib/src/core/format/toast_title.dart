/// A scraped product title, made safe for a one-line snackbar.
///
/// Titles come from third-party store pages and are attacker-influenced: they
/// can be arbitrarily long and contain newlines or runs of tabs, which would
/// otherwise turn a two-line toast into a wall of text. Whitespace is folded
/// first so the cap cannot be spent on invisible characters.
///
/// Shared by the chat page (its toasts and its refusal messages) and the
/// search-result card (its own "can't open this" message), so a hostile title
/// cannot reach one snackbar bounded and another unbounded.
String toastTitle(String title) => _oneLine(title, maxToastTitleLength);

/// Copy that is not a title — the service's own explanation of a failed
/// "add to tracker" ("couldn't reach the store", "no results for that session"),
/// which is remote text just like a scraped title and reaches the same snackbar.
///
/// Bounding it here rather than at the call site keeps the two remote-text paths
/// in the chat page using one rule: whatever the service answers, the toast shows
/// at most a line of text and never the whole payload.
String toastMessage(String message) => _oneLine(message, maxToastTitleLength);

/// A storage bound for remote text that is not being shown as a headline.

/// Used by the model parsers, i.e. where text the chatbot service enters the
/// app. A compromised or runaway service can ignore its own token budget and
/// hand over a megabyte per field; every character of that then stays reachable
/// for as long as the signed-in session lives. Clipping at the boundary means
/// no later screen has to remember to do it, and it is what makes the chat
/// history cap honest - 'keep the last N turns' only bounds memory if a turn
/// itself is bounded.

/// No ellipsis: this is a size bound, not a display promise, and the limits
/// are far above anything the service can legitimately produce.
String clip(String value, int max) {
  if (max <= 0) {
    // Nothing fits; the surrogate check below would index below zero.
    return '';
  }
  if (value.length <= max) {
    return value;
  }
  var cut = max;
  final keptUnit = value.codeUnits[cut - 1];
  if ((keptUnit & 0xfc00) == 0xd800) {
    cut -= 1;
  }
  return value.substring(0, cut);
}

/// Length of a toast title, ellipsis included.
const maxToastTitleLength = 80;

/// Index of the first character in [value] that is not whitespace.
//
/// Done by removing the leading run and measuring what was lost, because this
/// Dart SDK exposes no `RegExp.match` and no `String.matchAll`. The payload is
/// walked a chunk at a time so a hostile title is never copied whole.
int _contentStart(String value, int chunkSize) {
  for (var start = 0; start < value.length; start += chunkSize) {
    final end = value.length - start < chunkSize
        ? value.length
        : start + chunkSize;
    final chunk = value.substring(start, end);
    // `^` anchors at the start of the chunk: the units it removes are the
    // padding in front of this chunk's content.
    final padding = chunk.length - chunk.replaceAll(RegExp(r'^\s+'), '').length;
    if (padding < chunk.length) return start + padding;
  }
  // Nothing but whitespace: there is no content to keep.
  return value.length;
}

/// Runs of whitespace, folded to a single space before any cap is measured.
final _whitespaceRuns = RegExp(r'\s+');

/// A remote string made safe to sit inside a line the app is laying out.
//
/// Whitespace runs collapse to one space and both ends are trimmed, so a title
/// that its source markup wrapped across lines cannot break whatever shows it.
/// No length bound here: the screens that need one call [toastTitle] or
/// [toastMessage], which fold first and then cut at the cap.
String foldWhitespace(String value) =>
    value.replaceAll(_whitespaceRuns, ' ').trim();

/// Whitespace-folded, cut to `max` characters with the tail replaced by "…".
String _oneLine(String value, int max) {
  // A line this short has no room for content plus an ellipsis, and indexing
  // before the start of the string is what a naive cut would do.
  if (max <= 1) {
    return max <= 0 ? '' : '\u2026';
  }

  // Only `max * 8` units are ever copied and folded: folding a whole payload
  // to decide on one line spends the work, and the copy, that the cap exists
  // to avoid. The window is anchored on the first character that is not
  // whitespace, so padding cannot push the product name out of it and cannot
  // break a word in half; finding that character is done a chunk at a time,
  // so no more than `max * 8` units of the payload are held at once.
  final start = _contentStart(value, max * 8);
  final end = value.length < start + max * 8 ? value.length : start + max * 8;
  final singleLine = value
      .substring(start, end)
      .replaceAll(_whitespaceRuns, ' ')
      .trim();
  if (singleLine.length <= max) return singleLine;

  // The cap is the whole line the user sees, so the cut leaves a slot for the
  // ellipsis that replaces everything after it: a cut at `max` plus "…" would
  // be one character over the documented limit.
  var cut = max - 1;

  // `substring` counts UTF-16 code units, so a cut can land between the two
  // halves of a surrogate pair — every emoji, and most non-BMP text — leaving
  // a lone surrogate that renders as a replacement glyph. The unit kept at
  // `cut - 1` is checked: a leading surrogate whose partner falls at `cut` is
  // dropped instead, which backs the line off by one unit and keeps the pair
  // whole. A cut may still fall between a base character and a combining mark
  // or inside a ZWJ sequence, which loses decoration but stays valid text;
  // grapheme-accurate boundaries would need an intl dependency.
  final keptUnit = singleLine.codeUnits[cut - 1];
  if ((keptUnit & 0xfc00) == 0xd800) cut -= 1;

  return '${singleLine.substring(0, cut)}…';
}
