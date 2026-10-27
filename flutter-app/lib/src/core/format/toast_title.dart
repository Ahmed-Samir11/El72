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
String toastTitle(String title) {
  final singleLine = title.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (singleLine.length <= maxToastTitleLength) return singleLine;
  return '${singleLine.substring(0, maxToastTitleLength)}…';
}

/// Length of a toast title, including the ellipsis that replaces the tail.
const maxToastTitleLength = 80;
