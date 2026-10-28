/// The one rule for "is this a url we are allowed to open or forward?".
///
/// Shared by the chat UI (which greys out the Add button and refuses the
/// snackbar path) and the chatbot repository (which refuses to POST a hostile
/// url to the tracker service). One copy of the rule keeps the UI promise and
/// the server-side guard from drifting apart.
///
/// Not the SSRF boundary — see the server.
///
/// The whole rule runs in the user's own app: it decides which link a tap may
/// hand to a browser, and which url the client is willing to forward to the
/// tracker service. The component that actually goes and *fetches* a url is the
/// API service, and its boundary is `services/common/url_policy.py::fetch_block_reason`,
/// applied by `POST /tracked-items/from-url` before any row is written or credit
/// spent. A client-side check can be bypassed by anyone who builds their own
/// request, so this guard is defence in depth and never the thing that keeps
/// the server's own network off the target list — changing it here must not be
/// read as changing what the server will visit.
bool isHttpUrl(String url) {
  // A url carrying a space, a newline or a control character is refused. `Uri`
  // would not reject it: it percent-encodes the character *into the host*, so
  // `https://a b.com/x` parses as the single host `a%20b.com`. Scraped markup
  // wraps long attributes across line breaks for exactly that shape, and one
  // broken-looking address is not something to hand a browser. A legitimate link
  // never needs it: real urls percent-encode their own spaces.
  if (url.split(_urlControlChars).length > 1) return false;

  final uri = Uri.tryParse(url);
  // `hasAuthority`, not `isAbsolute`: Uri.isAbsolute means "has a scheme and
  // no fragment", so it would reject a perfectly good scraped product link
  // that carries an anchor (`…/product#price`). hasAuthority requires the
  // `scheme://host` shape, which is what actually distinguishes a web address
  // from a relative path or a hostile scheme.
  if (uri == null || !uri.hasAuthority || uri.host.isEmpty) return false;
  return uri.scheme == 'http' || uri.scheme == 'https';
}

/// Characters no real url contains: ASCII control characters and space, the
/// delete character, C1 separators, the Unicode line and paragraph separators,
/// and the zero-width or format characters used to hide and reorder text.
//
/// Matched through `String.split` because this Dart SDK exposes no `RegExp.test`
/// and no `RegExp.match`. Anything left in is percent-encoded by `Uri`, which
/// hides it inside the host rather than rejecting the link.
final _urlControlChars = RegExp(
  r'[\x00-\x20\x7f\x85\xa0\u200b-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff]',
);
