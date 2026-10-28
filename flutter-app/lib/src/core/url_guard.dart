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
  final uri = Uri.tryParse(url);
  // `hasAuthority`, not `isAbsolute`: Uri.isAbsolute means "has a scheme and
  // no fragment", so it would reject a perfectly good scraped product link
  // that carries an anchor (`…/product#price`). hasAuthority requires the
  // `scheme://host` shape, which is what actually distinguishes a web address
  // from a relative path or a hostile scheme.
  if (uri == null || !uri.hasAuthority || uri.host.isEmpty) return false;
  return uri.scheme == 'http' || uri.scheme == 'https';
}
