// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'El72';

  @override
  String get login => 'Log In';

  @override
  String get register => 'Register';

  @override
  String get phoneNumber => 'Phone Number';

  @override
  String get password => 'Password';

  @override
  String get fillAllFields => 'Please fill all fields';

  @override
  String get invalidCredentials => 'Invalid credentials. Please try again.';

  @override
  String loginFailed(String error) {
    return 'Login failed: $error';
  }

  @override
  String get cancel => 'Cancel';

  @override
  String get registrationFailed => 'Registration failed. Please try again.';

  @override
  String get haveAccountLogin => 'Already have an account? Login';

  @override
  String get otpVerification => 'OTP Verification';

  @override
  String get deliveryMethod => 'Delivery Method';

  @override
  String get sms => 'SMS';

  @override
  String get email => 'Email';

  @override
  String get enterOtp => 'Enter OTP';

  @override
  String get verify => 'Verify';

  @override
  String get splashStatusOpening => 'Opening application...';

  @override
  String get splashStatusConnecting => 'Connecting to cloud...';

  @override
  String get splashStatusLoading => 'Loading user data...';

  @override
  String get splashStatusReady => 'Almost ready...';

  @override
  String failedToLoadTrackers(String error) {
    return 'Failed to load your trackers.\n$error';
  }

  @override
  String get noTrackersEmpty =>
      'No active trackers yet.\nTap + to start tracking a product.';

  @override
  String get liveMarketFeed => 'Live Market Feed';

  @override
  String failedToLoadDeals(String error) {
    return 'Failed to load deals.\n$error';
  }

  @override
  String get noLiveDeals => 'No live deals right now. Check back soon.';

  @override
  String get myAccount => 'My account';

  @override
  String get demoAccount => 'Demo account';

  @override
  String get fullAccount => 'Full account';

  @override
  String get currentPlan => 'Current plan';

  @override
  String get freePlan => 'Free plan';

  @override
  String get manage => 'Manage';

  @override
  String get demoMode => 'Demo mode';

  @override
  String get usingSampleData => 'Using sample data offline';

  @override
  String get usingLiveData => 'Using live account and API data';

  @override
  String get logOut => 'Log out';

  @override
  String get activeAlerts => 'Active Alerts';

  @override
  String get dealsToday => 'Deals Today';

  @override
  String get savings => 'Savings';

  @override
  String get createPriceTracker => 'Create Price Tracker';

  @override
  String get productUrlHint => 'Product URL (any supported store)';

  @override
  String get targetPriceHint => 'Target Price (Optional)';

  @override
  String get trackerCreated =>
      '✅ Tracker created! You\'ll get a WhatsApp notification when we find a deal.';

  @override
  String get startTracking => 'Start Tracking';

  @override
  String errorPrefix(String error) {
    return 'Error: $error';
  }

  @override
  String unableToOpen(String title) {
    return 'Unable to open $title';
  }

  @override
  String get priceHistory => 'Price History';

  @override
  String get noPriceHistory =>
      'No price history available for this product yet.';

  @override
  String failedToLoadPriceHistory(String message) {
    return 'Failed to load price history.\n$message';
  }

  @override
  String get subscriptionPlans => 'Subscription Plans';

  @override
  String get freePlanShort => 'Free';

  @override
  String get proPlan => 'Pro';

  @override
  String get businessPlan => 'Business';

  @override
  String get basicTracking => 'Basic tracking for 3 products';

  @override
  String get unlimitedTracking => 'Unlimited tracking + notifications';

  @override
  String get advancedAnalytics => 'Advanced analytics + API access';

  @override
  String egpPerMonth(String amount) {
    return 'EGP $amount/month';
  }

  @override
  String get creditPackages => 'Credit Packages';

  @override
  String get standardPackage => 'Standard';

  @override
  String get premiumPackage => 'Premium';

  @override
  String get standardPackageDesc => '10 credits for price trackers';

  @override
  String get premiumPackageDesc => '30 credits for price trackers';

  @override
  String creditsLabel(int count) {
    return '$count credits';
  }

  @override
  String egpOnce(String amount) {
    return 'EGP $amount (one-time)';
  }

  @override
  String get buyNow => 'Buy now';

  @override
  String get freeCreditsDesc => '3 free credits included';

  @override
  String get selectWallet => 'Choose your wallet';

  @override
  String get walletVodafoneCash => 'Vodafone Cash';

  @override
  String get walletOrangeMoney => 'Orange Money';

  @override
  String get walletEtisalatCash => 'Etisalat Cash';

  @override
  String get walletFawry => 'Fawry';

  @override
  String get walletNumberLabel => 'Wallet phone number';

  @override
  String get walletNumberHint => '01X XXXXXXXX';

  @override
  String get invalidWalletNumber =>
      'Enter a valid Egyptian mobile number (010/011/012/015 + 8 digits)';

  @override
  String get confirmPaymentButton => 'Confirm payment';

  @override
  String get walletConfirmTitle => 'Confirm your wallet';

  @override
  String walletConfirmMessage(String number) {
    return 'You\'re paying to wallet $number. Confirm?';
  }

  @override
  String get enterOtpTitle => 'Enter OTP';

  @override
  String get enterOtpDesc => 'Enter the code sent to your wallet';

  @override
  String get otpInvalid => 'Enter the digits from the code';

  @override
  String otpAttemptsLeft(int count) {
    return '$count attempts remaining';
  }

  @override
  String get verifyOtpButton => 'Verify code';

  @override
  String get paymentProcessing => 'Processing your payment…';

  @override
  String get paymentPending => 'Waiting for payment confirmation…';

  @override
  String get paymentSucceededTitle => 'Payment successful!';

  @override
  String get paymentSucceededDesc => 'Your credits have been added.';

  @override
  String get paymentFailedTitle => 'Payment failed';

  @override
  String get paymentFailedDesc => 'No credits were granted. You can try again.';

  @override
  String get paymentCanceledTitle => 'Payment canceled';

  @override
  String get paymentError => 'Something went wrong. Please try again.';

  @override
  String get retryPayment => 'Try again';

  @override
  String get selectPaymentMethod => 'Choose how you\'d like to pay';

  @override
  String get paymentMethodWallet => 'Mobile wallet';

  @override
  String get paymentMethodWalletDesc =>
      'Pay with a mobile wallet (Vodafone Cash, Orange Money, Etisalat Cash)';

  @override
  String get paymentMethodCash => 'Cash (Fawry / bank)';

  @override
  String get paymentMethodCashDesc =>
      'Get a payment code and pay at a Fawry point or bank branch';

  @override
  String get selectCashChannel => 'Choose your cash channel';

  @override
  String get cashChannelFawry => 'Fawry';

  @override
  String get cashChannelBank => 'Bank branch';

  @override
  String get cashCodeTitle => 'Your payment code';

  @override
  String get cashCodeDesc =>
      'Show this code at the cash point or bank branch. It expires in 24 hours.';

  @override
  String cashExpiresAt(String time) {
    return 'Expires $time';
  }

  @override
  String get copyCode => 'Copy';

  @override
  String get codeCopied => 'Code copied';

  @override
  String get statCurrent => 'Current';

  @override
  String get statLow90d => '90d Low';

  @override
  String get statHigh90d => '90d High';

  @override
  String get statChange => 'Change';

  @override
  String get close => 'Close';

  @override
  String targetLabel(String price) {
    return 'Target: $price';
  }

  @override
  String get openProduct => 'Open product';

  @override
  String currentLabel(String price) {
    return 'Current: $price';
  }

  @override
  String get fetchingPrice => 'Fetching live price...';

  @override
  String get priceFetchFailed => 'Couldn\'t fetch the price - tap to retry.';

  @override
  String get notAProductPage =>
      'This page doesn\'t look like a product - check the link.';

  @override
  String get priceRefreshFailed =>
      'Couldn\'t refresh the price right now - try again in a moment.';

  @override
  String get deleteTrackerTitle => 'Delete tracker?';

  @override
  String deleteTrackerBody(String title) {
    return 'Stop tracking \"$title\"? Its price history will be removed.';
  }

  @override
  String get deleteTrackerConfirm => 'Delete';

  @override
  String get trackerDeleted => 'Tracker deleted';

  @override
  String get retry => 'Retry';

  @override
  String get trackerDeleteFailed => 'Couldn\'t delete the tracker - try again.';

  @override
  String genericLoadError(String error) {
    return 'Failed to load.\n$error';
  }

  @override
  String get liveDeals => 'Live Deals';

  @override
  String creditsRemaining(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'You have $count trackers left',
      one: 'You have 1 tracker left',
    );
    return '$_temp0';
  }

  @override
  String get reachedLimitTitle => 'You\'ve reached your limit';

  @override
  String get reachedLimitBody =>
      'You\'ve used all your available price trackers. Upgrade your plan to keep tracking prices and get more trackers.';

  @override
  String get upgradePlan => 'Upgrade plan';

  @override
  String get notNow => 'Not now';

  @override
  String get navTrackers => 'Trackers';

  @override
  String get navDeals => 'Deals';

  @override
  String get navChat => 'Chat';

  @override
  String get navProfile => 'Profile';

  @override
  String get addToFeed => 'Add to Feed';

  @override
  String get searchHint =>
      'Search for products (e.g. \"gaming laptop under 50000 EGP\")';

  @override
  String get searchResults => 'Search Results';

  @override
  String get botTyping => 'Bot is typing...';

  @override
  String get newChat => 'New Chat';

  @override
  String get chatTitle => 'Chat';

  @override
  String get noMessagesYet => 'No messages yet. Start a conversation.';

  @override
  String get fairUseTitle => 'Your trackers';

  @override
  String fairUseChip(int count, int cap) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Tracking $count of up to $cap',
      one: 'Tracking 1 of up to $cap',
      zero: 'No trackers yet. Up to $cap at once',
    );
    return '$_temp0';
  }

  @override
  String fairUseUncapped(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Tracking $count trackers, no limit in this build',
      one: 'Tracking 1 tracker, no limit in this build',
      zero: 'No trackers yet',
    );
    return '$_temp0';
  }

  @override
  String fairUseCapBody(int cap) {
    return 'You already have $cap trackers running, which is the maximum. Delete one to make room, or tap Not now.';
  }

  @override
  String get creationWaitTitle => 'One tracker at a time';

  @override
  String creationWaitBody(int seconds) {
    return 'You just added a tracker. Wait $seconds seconds before adding the next one.';
  }

  @override
  String get creationWaitBodyNoCount =>
      'One tracker at a time. Tap Start Tracking again when you are ready.';
}
