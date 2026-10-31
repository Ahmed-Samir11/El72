import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Hardcoded-string guard for the i18n rule in `.agents/AGENTS.md`.
///
/// `l10n_coverage_test.dart` proves the two ARB files stay in step, but it says
/// nothing about a widget that never goes through `AppLocalizations` at all —
/// which is what a review pass found. This scan flags a string literal handed
/// directly to a text-producing widget or a text-named parameter and pins every
/// existing offender in an allow-list: adding a new hardcoded string fails, and
/// so does leaving a now-fixed entry behind, so the list can only ever shrink.
///
/// Deliberately narrow (a literal on the same expression as `Text(` or a
/// `hintText:`/`label:`/`message:`-style parameter, comment lines ignored). It is
/// a ratchet, not a whole-app audit: strings assembled further down a call chain
/// are out of reach and still need a reviewer.
void main() {
  const l10nDir = 'lib/l10n';

  // A raw *triple*-quoted literal is required for `["']`: a raw single-quoted
  // string still ends at the escaped quote, which cost a parse error the first
  // time this was written. Group 1 is the opening quote (reused by `(?!\1)` so a
  // literal may contain the other quote unescaped), group 2 the text.
  final userFacingText = RegExp(
    r'''(?:\bText\s*\(|'''
    r'''\b(?:hintText|label|title|subtitle|message|body|tooltip|semanticLabel'''
    r'''|errorText|helperText|alt|content)\s*[:=])'''
    r'''\s*(?:const\s+)?r?(["\'])((?:\\.|(?!\1)[^\n]){1,120})''',
  );

  // What is left after interpolations are folded away decides whether a literal
  // carries prose: `'-$pct%'` is punctuation around a number, `'EGP $x'` is not.
  final interpolations = RegExp(r'\$\{[^}]*\}|\$[A-Za-z_$][A-Za-z0-9_]*');
  final hasWords = RegExp(r'[A-Za-z]{2}');
  final arabicScript = RegExp('[\u0600-\u06FF]');

  // A comment line becomes an empty line: prose that mentions `Text('like this')`
  // must not read as a widget, and blanking (rather than deleting) stops a comment
  // from splicing two statements together.
  String blankComments(String source) {
    final lines = source.split('\n');
    for (var i = 0; i < lines.length; i++) {
      final trimmed = lines[i].trim();
      if (trimmed.startsWith('//') ||
          trimmed.startsWith('*') ||
          trimmed.startsWith('/*')) {
        lines[i] = '';
      }
    }
    return lines.join('\n');
  }

  String normalize(String path) => path.replaceAll('\\', '/');

  Iterable<File> dartFiles(String root) {
    return Directory(
      root,
    ).listSync(recursive: true, followLinks: false).whereType<File>();
  }

  // Offenders are reported as `path|literal` — the same shape as the allow-list
  // below, so a failure names the file *and* the string to localize.
  List<String> offendersIn(String path, String source) {
    final found = <String>[];
    for (final match in userFacingText.allMatches(blankComments(source))) {
      final literal = match[2]!;
      final prose = literal.replaceAll(interpolations, '');
      if (!hasWords.hasMatch(prose) || literal.startsWith(r'$')) continue;
      found.add('$path|$literal');
    }
    return found;
  }

  // `root` is walked with forward-slash paths either way, so the allow-list reads
  // the same on Windows and on CI.
  Map<String, List<String>> scan(String root) {
    final byFile = <String, List<String>>{};
    for (final file in dartFiles(root)) {
      final path = normalize(file.path);
      if (path.startsWith('$l10nDir/')) continue;
      final found = offendersIn(path, file.readAsStringSync());
      if (found.isNotEmpty) byFile[path] = found;
    }
    return byFile;
  }

  group('the scan itself', () {
    const fixture = r'''
class _Fixture {
  // Text('prose in a line comment is not a widget')
  /* Text('prose in a block comment') */
  /// [Text('prose in a doc comment')]
  final a = const Text('Cancel');
  final b = Text(AppLocalizations.of(context).addToFeed);
  final c = Text(r'$tracked');
  final d = Text(
    'Forgot Password?',
  );
  final e = Semantics(label: 'El72 logo', child: Container());
  final f = Text('Monitor $x items');
  final g = TextField(hintText: '-${value.toStringAsFixed(0)}%');
  final h = "don't do this";
}
''';
    const file = 'lib/src/ui/fixture.dart';
    // Lets the expectations below name a `$` without tripping interpolation in
    // this very file.
    const dollar = r'$';

    test('catches a literal handed to a text producer, same line or not', () {
      final found = offendersIn(file, fixture);
      for (final expected in <String>[
        '$file|Cancel',
        '$file|Forgot Password?',
        '$file|El72 logo',
        '$file|Monitor ${dollar}x items',
      ]) {
        expect(found.contains(expected), isTrue, reason: 'missed: $found');
      }
    });

    test('ignores comments, localized calls and wordless text', () {
      final found = offendersIn(file, fixture);
      expect(
        found.where((o) => o.contains('prose in')),
        isEmpty,
        reason: '$found',
      );
      expect(
        found.where((o) => o.contains('AppLocalizations')),
        isEmpty,
        reason: '$found',
      );
      expect(
        found.contains('$file|${dollar}tracked'),
        isFalse,
        reason: '$found',
      );
      expect(
        found.contains('$file|-$dollar{value.toStringAsFixed(0)}%'),
        isFalse,
        reason: '$found',
      );
    });

    test('the walk reaches the real tree and finds the known debt', () {
      // A broken walk would make every assertion below vacuously true, which is
      // the exact failure mode this file exists to prevent.
      final found = scan('lib');
      expect(found.length, greaterThan(5), reason: 'scan found: ${found.keys}');
      expect(
        found['lib/src/ui/auth/login_page.dart'],
        contains('lib/src/ui/auth/login_page.dart|Cancel'),
      );
    });
  });

  group('hardcoded user-facing strings', () {
    // Debt: pending the maintainer's Arabic wording — never authored here, since
    // `app_ar.arb` is written by a native speaker and an English key with no Arabic
    // twin fails `l10n_coverage_test.dart`. To fix one: add the key to both ARB
    // files in the same commit and delete its entry below.
    const allowList = <String>{
      // The chatbot tab — the strings a review pass flagged, blocked on Arabic.
      r"lib/src/ui/chatbot/chat_page.dart|Sorry, I couldn\'t process your request. Please try again.",
      'lib/src/ui/chatbot/chat_page.dart|An error occurred. Please try again.',
      // Sign-in screen.
      'lib/src/ui/auth/login_page.dart|Cancel',
      'lib/src/ui/auth/login_page.dart|Forgot Password?',
      // Deal-notification card.
      'lib/src/ui/widgets/deal_notification_card.dart|WhatsApp notification sent',
      'lib/src/ui/widgets/deal_notification_card.dart|Current Price',
      'lib/src/ui/widgets/deal_notification_card.dart|Got it!',
      'lib/src/ui/widgets/deal_notification_card.dart|\uD83C\uDF89 Deal Found!',
      'lib/src/ui/widgets/deal_notification_card.dart|'
          r'EGP ${currentPrice.toStringAsFixed(0)}',
      // Tracker status text shown while a tracker is being created.
      'lib/src/data/providers/tracking_status_provider.dart|Creating tracker...',
      // Brand mark: image alt text and the tagline are debt; the wordmarks below
      // are exempt, the same allowance `l10n_coverage_test.dart` grants `appTitle`
      // — nobody should "fix" a trademark by inventing Arabic for it.
      'lib/src/ui/common/el72_brand_mark.dart|El72 logo',
      'lib/src/ui/common/el72_brand_mark.dart|Real-time price intelligence',
      'lib/src/ui/common/el72_brand_mark.dart|El72',
      'lib/src/ui/common/el72_brand_mark.dart|EL72',
    };

    // Files whose text is not app copy, exempted as a whole so a fixture rename
    // cannot churn the list above.
    const exemptFiles = <String>{
      // Fake store content shown only in demo mode; product names are data, and
      // this file is what the sample cards are built from.
      'lib/src/data/demo_data.dart',
      // `DioException(message: …)` — diagnostics for the log/error mapper, not a
      // string a widget renders.
      'lib/src/data/repositories/credits_repository.dart',
      'lib/src/data/repositories/payment_repository.dart',
      // Same shape as the two above: the fair-use balance of MS1's `GET /usage/limits`
      // transport error, never rendered to the user.
      'lib/src/data/repositories/usage_limits_repository.dart',
    };

    final scanned = scan('lib');
    final found = {for (final list in scanned.values) ...list};
    final exemptLiterals = {
      for (final file in exemptFiles) ...(scanned[file] ?? const <String>[]),
    };
    final allowed = {...allowList, ...exemptLiterals};

    test('nothing outside the allow-list hardcodes a user-facing string', () {
      final unexpected = found.difference(allowed).toList()..sort();
      expect(
        unexpected,
        isEmpty,
        reason:
            'needs an app_en.arb key *and* a native Arabic value in app_ar.'
            'arb, in the same commit: $unexpected',
      );
    });

    test('the allow-list holds no entry that no longer exists', () {
      final obsolete = allowList.difference(found).toList()..sort();
      expect(
        obsolete,
        isEmpty,
        reason:
            'these strings are gone; shrink the list instead of leaving them '
            'behind: $obsolete',
      );
    });

    test('every exempt file still needs exempting', () {
      final stale = exemptFiles.where((f) => !scanned.containsKey(f)).toList();
      expect(
        stale,
        isEmpty,
        reason: 'no text-producing literals left in $stale; drop the exemption',
      );
    });
  });

  group('Arabic stays out of code', () {
    test('no Arabic script outside comments in lib/', () {
      // Comments may quote Arabic; user-facing Arabic belongs in app_ar.arb so
      // the RTL work and the coverage test can see it. `main.dart` currently
      // hardcodes the Arabic wordmark as the web document title — real debt,
      // pinned here so new widgets cannot add more of it.
      const knownFiles = <String>{'lib/main.dart'};

      final offenders = <String>[];
      for (final file in dartFiles('lib')) {
        final path = normalize(file.path);
        if (path.startsWith('$l10nDir/')) continue;
        if (arabicScript.hasMatch(blankComments(file.readAsStringSync()))) {
          offenders.add(path);
        }
      }
      expect(
        offenders,
        knownFiles,
        reason:
            'Arabic belongs in lib/l10n/app_ar.arb; either $offenders is new '
            'debt or $knownFiles is stale — fix the list and the code together',
      );
    });
  });
}
