import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en'),
  ];

  /// App name shown in the dashboard app bar.
  ///
  /// In en, this message translates to:
  /// **'El72'**
  String get appTitle;

  /// No description provided for @login.
  ///
  /// In en, this message translates to:
  /// **'Log In'**
  String get login;

  /// No description provided for @register.
  ///
  /// In en, this message translates to:
  /// **'Register'**
  String get register;

  /// No description provided for @phoneNumber.
  ///
  /// In en, this message translates to:
  /// **'Phone Number'**
  String get phoneNumber;

  /// No description provided for @password.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get password;

  /// No description provided for @fillAllFields.
  ///
  /// In en, this message translates to:
  /// **'Please fill all fields'**
  String get fillAllFields;

  /// No description provided for @invalidCredentials.
  ///
  /// In en, this message translates to:
  /// **'Invalid credentials. Please try again.'**
  String get invalidCredentials;

  /// No description provided for @loginFailed.
  ///
  /// In en, this message translates to:
  /// **'Login failed: {error}'**
  String loginFailed(String error);

  /// No description provided for @cancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancel;

  /// No description provided for @registrationFailed.
  ///
  /// In en, this message translates to:
  /// **'Registration failed. Please try again.'**
  String get registrationFailed;

  /// No description provided for @haveAccountLogin.
  ///
  /// In en, this message translates to:
  /// **'Already have an account? Login'**
  String get haveAccountLogin;

  /// No description provided for @otpVerification.
  ///
  /// In en, this message translates to:
  /// **'OTP Verification'**
  String get otpVerification;

  /// No description provided for @deliveryMethod.
  ///
  /// In en, this message translates to:
  /// **'Delivery Method'**
  String get deliveryMethod;

  /// No description provided for @sms.
  ///
  /// In en, this message translates to:
  /// **'SMS'**
  String get sms;

  /// No description provided for @email.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get email;

  /// No description provided for @enterOtp.
  ///
  /// In en, this message translates to:
  /// **'Enter OTP'**
  String get enterOtp;

  /// No description provided for @verify.
  ///
  /// In en, this message translates to:
  /// **'Verify'**
  String get verify;

  /// No description provided for @splashStatusOpening.
  ///
  /// In en, this message translates to:
  /// **'Opening application...'**
  String get splashStatusOpening;

  /// No description provided for @splashStatusConnecting.
  ///
  /// In en, this message translates to:
  /// **'Connecting to cloud...'**
  String get splashStatusConnecting;

  /// No description provided for @splashStatusLoading.
  ///
  /// In en, this message translates to:
  /// **'Loading user data...'**
  String get splashStatusLoading;

  /// No description provided for @splashStatusReady.
  ///
  /// In en, this message translates to:
  /// **'Almost ready...'**
  String get splashStatusReady;

  /// No description provided for @failedToLoadTrackers.
  ///
  /// In en, this message translates to:
  /// **'Failed to load your trackers.\n{error}'**
  String failedToLoadTrackers(String error);

  /// No description provided for @noTrackersEmpty.
  ///
  /// In en, this message translates to:
  /// **'No active trackers yet.\nTap + to start tracking a product.'**
  String get noTrackersEmpty;

  /// No description provided for @liveMarketFeed.
  ///
  /// In en, this message translates to:
  /// **'Live Market Feed'**
  String get liveMarketFeed;

  /// No description provided for @failedToLoadDeals.
  ///
  /// In en, this message translates to:
  /// **'Failed to load deals.\n{error}'**
  String failedToLoadDeals(String error);

  /// No description provided for @noLiveDeals.
  ///
  /// In en, this message translates to:
  /// **'No live deals right now. Check back soon.'**
  String get noLiveDeals;

  /// No description provided for @myAccount.
  ///
  /// In en, this message translates to:
  /// **'My account'**
  String get myAccount;

  /// No description provided for @demoAccount.
  ///
  /// In en, this message translates to:
  /// **'Demo account'**
  String get demoAccount;

  /// No description provided for @fullAccount.
  ///
  /// In en, this message translates to:
  /// **'Full account'**
  String get fullAccount;

  /// No description provided for @currentPlan.
  ///
  /// In en, this message translates to:
  /// **'Current plan'**
  String get currentPlan;

  /// No description provided for @freePlan.
  ///
  /// In en, this message translates to:
  /// **'Free plan'**
  String get freePlan;

  /// No description provided for @manage.
  ///
  /// In en, this message translates to:
  /// **'Manage'**
  String get manage;

  /// No description provided for @demoMode.
  ///
  /// In en, this message translates to:
  /// **'Demo mode'**
  String get demoMode;

  /// No description provided for @usingSampleData.
  ///
  /// In en, this message translates to:
  /// **'Using sample data offline'**
  String get usingSampleData;

  /// No description provided for @usingLiveData.
  ///
  /// In en, this message translates to:
  /// **'Using live account and API data'**
  String get usingLiveData;

  /// No description provided for @logOut.
  ///
  /// In en, this message translates to:
  /// **'Log out'**
  String get logOut;

  /// No description provided for @activeAlerts.
  ///
  /// In en, this message translates to:
  /// **'Active Alerts'**
  String get activeAlerts;

  /// No description provided for @dealsToday.
  ///
  /// In en, this message translates to:
  /// **'Deals Today'**
  String get dealsToday;

  /// No description provided for @savings.
  ///
  /// In en, this message translates to:
  /// **'Savings'**
  String get savings;

  /// No description provided for @createPriceTracker.
  ///
  /// In en, this message translates to:
  /// **'Create Price Tracker'**
  String get createPriceTracker;

  /// No description provided for @productUrlHint.
  ///
  /// In en, this message translates to:
  /// **'Product URL (any supported store)'**
  String get productUrlHint;

  /// No description provided for @targetPriceHint.
  ///
  /// In en, this message translates to:
  /// **'Target Price (Optional)'**
  String get targetPriceHint;

  /// No description provided for @trackerCreated.
  ///
  /// In en, this message translates to:
  /// **'✅ Tracker created! You\'ll get a WhatsApp notification when we find a deal.'**
  String get trackerCreated;

  /// No description provided for @startTracking.
  ///
  /// In en, this message translates to:
  /// **'Start Tracking'**
  String get startTracking;

  /// No description provided for @errorPrefix.
  ///
  /// In en, this message translates to:
  /// **'Error: {error}'**
  String errorPrefix(String error);

  /// No description provided for @unableToOpen.
  ///
  /// In en, this message translates to:
  /// **'Unable to open {title}'**
  String unableToOpen(String title);

  /// No description provided for @priceHistory.
  ///
  /// In en, this message translates to:
  /// **'Price History'**
  String get priceHistory;

  /// No description provided for @noPriceHistory.
  ///
  /// In en, this message translates to:
  /// **'No price history available for this product yet.'**
  String get noPriceHistory;

  /// No description provided for @failedToLoadPriceHistory.
  ///
  /// In en, this message translates to:
  /// **'Failed to load price history.\n{message}'**
  String failedToLoadPriceHistory(String message);

  /// No description provided for @subscriptionPlans.
  ///
  /// In en, this message translates to:
  /// **'Subscription Plans'**
  String get subscriptionPlans;

  /// No description provided for @freePlanShort.
  ///
  /// In en, this message translates to:
  /// **'Free'**
  String get freePlanShort;

  /// No description provided for @proPlan.
  ///
  /// In en, this message translates to:
  /// **'Pro'**
  String get proPlan;

  /// No description provided for @businessPlan.
  ///
  /// In en, this message translates to:
  /// **'Business'**
  String get businessPlan;

  /// No description provided for @basicTracking.
  ///
  /// In en, this message translates to:
  /// **'Basic tracking for 3 products'**
  String get basicTracking;

  /// No description provided for @unlimitedTracking.
  ///
  /// In en, this message translates to:
  /// **'Unlimited tracking + notifications'**
  String get unlimitedTracking;

  /// No description provided for @advancedAnalytics.
  ///
  /// In en, this message translates to:
  /// **'Advanced analytics + API access'**
  String get advancedAnalytics;

  /// No description provided for @egpPerMonth.
  ///
  /// In en, this message translates to:
  /// **'EGP {amount}/month'**
  String egpPerMonth(String amount);

  /// No description provided for @statCurrent.
  ///
  /// In en, this message translates to:
  /// **'Current'**
  String get statCurrent;

  /// No description provided for @statLow90d.
  ///
  /// In en, this message translates to:
  /// **'90d Low'**
  String get statLow90d;

  /// No description provided for @statHigh90d.
  ///
  /// In en, this message translates to:
  /// **'90d High'**
  String get statHigh90d;

  /// No description provided for @statChange.
  ///
  /// In en, this message translates to:
  /// **'Change'**
  String get statChange;

  /// No description provided for @close.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get close;

  /// No description provided for @targetLabel.
  ///
  /// In en, this message translates to:
  /// **'Target: {price}'**
  String targetLabel(String price);

  /// No description provided for @currentLabel.
  ///
  /// In en, this message translates to:
  /// **'Current: {price}'**
  String currentLabel(String price);

  /// No description provided for @fetchingPrice.
  ///
  /// In en, this message translates to:
  /// **'Fetching live price...'**
  String get fetchingPrice;

  /// No description provided for @priceFetchFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t fetch the price - tap to retry.'**
  String get priceFetchFailed;

  /// No description provided for @notAProductPage.
  ///
  /// In en, this message translates to:
  /// **'This page doesn\'t look like a product - check the link.'**
  String get notAProductPage;

  /// No description provided for @priceRefreshFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn\'t refresh the price right now - try again in a moment.'**
  String get priceRefreshFailed;

  /// No description provided for @genericLoadError.
  ///
  /// In en, this message translates to:
  /// **'Failed to load.\n{error}'**
  String genericLoadError(String error);

  /// No description provided for @liveDeals.
  ///
  /// In en, this message translates to:
  /// **'Live Deals'**
  String get liveDeals;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['ar', 'en'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar':
      return AppLocalizationsAr();
    case 'en':
      return AppLocalizationsEn();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
