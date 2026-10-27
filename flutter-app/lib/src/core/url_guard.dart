/// The one rule for "is this a url we are allowed to open or forward?".
///
/// Shared by the chat UI (which greys out the Add button and refuses the
/// snackbar path) and the chatbot repository (which refuses to POST a hostile
/// url to the tracker service). One copy of the rule keeps the UI promise and
/// the server-side guard from drifting apart.
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
