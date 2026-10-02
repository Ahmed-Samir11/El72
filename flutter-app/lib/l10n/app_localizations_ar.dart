// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class AppLocalizationsAr extends AppLocalizations {
  AppLocalizationsAr([String locale = 'ar']) : super(locale);

  @override
  String get appTitle => 'إلحق';

  @override
  String get login => 'تسجيل الدخول';

  @override
  String get register => 'التسجيل';

  @override
  String get phoneNumber => 'رقم الهاتف';

  @override
  String get password => 'كلمة المرور';

  @override
  String get fillAllFields => 'يرجى ملء جميع الحقول';

  @override
  String get invalidCredentials =>
      'بيانات اعتماد غير صالحة. يرجى المحاولة مرة أخرى.';

  @override
  String loginFailed(String error) {
    return 'فشل تسجيل الدخول: $error';
  }

  @override
  String get cancel => 'إلغاء';

  @override
  String get registrationFailed => 'فشل التسجيل. يرجى المحاولة مرة أخرى.';

  @override
  String get haveAccountLogin => 'لديك حساب بالفعل؟ سجّل الدخول';

  @override
  String get otpVerification => 'تحقق رمز OTP';

  @override
  String get deliveryMethod => 'طريقة الإرسال';

  @override
  String get sms => 'رسالة نصية';

  @override
  String get email => 'البريد الإلكتروني';

  @override
  String get enterOtp => 'أدخل رمز التحقق';

  @override
  String get verify => 'تحقق';

  @override
  String get splashStatusOpening => 'جارٍ فتح التطبيق...';

  @override
  String get splashStatusConnecting => 'جارٍ الاتصال بالسحابة...';

  @override
  String get splashStatusLoading => 'جارٍ تحميل بيانات المستخدم...';

  @override
  String get splashStatusReady => 'على وشك الجاهزية...';

  @override
  String failedToLoadTrackers(String error) {
    return 'فشل في تحميل متتبعاتك.\n$error';
  }

  @override
  String get noTrackersEmpty =>
      'لا توجد متتبعات نشطة بعد.\nاضغط + لبدء تتبع منتج.';

  @override
  String get liveMarketFeed => 'بث السوق المباشر';

  @override
  String failedToLoadDeals(String error) {
    return 'فشل في تحميل الصفقات.\n$error';
  }

  @override
  String get noLiveDeals => 'لا توجد صفقات حية الآن. عد لاحقًا.';

  @override
  String get myAccount => 'حسابي';

  @override
  String get demoAccount => 'حساب تجريبي';

  @override
  String get fullAccount => 'حساب كامل';

  @override
  String get currentPlan => 'الخطة الحالية';

  @override
  String get freePlan => 'الخطة المجانية';

  @override
  String get manage => 'إدارة';

  @override
  String get demoMode => 'الوضع التجريبي';

  @override
  String get usingSampleData => 'استخدام بيانات تجريبية دون اتصال';

  @override
  String get usingLiveData => 'استخدام حساب مباشر وبيانات الـ API';

  @override
  String get logOut => 'تسجيل الخروج';

  @override
  String get activeAlerts => 'تنبيهات نشطة';

  @override
  String get dealsToday => 'صفقات اليوم';

  @override
  String get savings => 'التوفير';

  @override
  String get createPriceTracker => 'إنشاء متتبع أسعار';

  @override
  String get productUrlHint => 'رابط المنتج (أي متجر مدعوم)';

  @override
  String get targetPriceHint => 'السعر المستهدف (اختياري)';

  @override
  String get trackerCreated =>
      '✅ تم إنشاء المتتبع! ستصلك رسالة واتساب عند العثور على صفقة.';

  @override
  String get startTracking => 'ابدأ التتبع';

  @override
  String errorPrefix(String error) {
    return 'خطأ: $error';
  }

  @override
  String unableToOpen(String title) {
    return 'تعذر فتح $title';
  }

  @override
  String get priceHistory => 'سجل الأسعار';

  @override
  String get noPriceHistory => 'لا يوجد سجل أسعار لهذا المنتج بعد.';

  @override
  String failedToLoadPriceHistory(String message) {
    return 'فشل في تحميل سجل الأسعار.\n$message';
  }

  @override
  String get subscriptionPlans => 'خطط الاشتراك';

  @override
  String get freePlanShort => 'مجاني';

  @override
  String get proPlan => 'احترافي';

  @override
  String get businessPlan => 'أعمال';

  @override
  String get basicTracking => 'تتبع أساسي لـ 3 منتجات';

  @override
  String get unlimitedTracking => 'تتبع غير محدود + إشعارات';

  @override
  String get advancedAnalytics => 'تحليلات متقدمة + وصول API';

  @override
  String egpPerMonth(String amount) {
    return '$amount ج.م/شهر';
  }

  @override
  String get statCurrent => 'الحالي';

  @override
  String get statLow90d => 'أدنى 90 يوم';

  @override
  String get statHigh90d => 'أعلى 90 يوم';

  @override
  String get statChange => 'التغير';

  @override
  String get close => 'إغلاق';

  @override
  String targetLabel(String price) {
    return 'المستهدف: $price';
  }

  @override
  String currentLabel(String price) {
    return 'الحالي: $price';
  }

  @override
  String get fetchingPrice => 'جارٍ جلب السعر المباشر...';

  @override
  String get priceFetchFailed => 'تعذّر جلب السعر - اضغط للمحاولة مرة أخرى.';

  @override
  String get notAProductPage =>
      'هذه الصفحة لا تبدو كصفحة منتج - تحقق من الرابط.';

  @override
  String get priceRefreshFailed =>
      'تعذّر تحديث السعر الآن - حاول مرة أخرى بعد قليل.';

  @override
  String genericLoadError(String error) {
    return 'فشل في التحميل.\n$error';
  }

  @override
  String get liveDeals => 'الصفقات الحية';

  @override
  String creditsRemaining(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'لديك $count متتبعًا متبقية',
      many: 'لديك $count متتبعًا متبقية',
      few: 'لديك $count متتبعات متبقية',
      two: 'لديك متتبعان متبقيان',
      one: 'لديك متتبع واحد متبقٍ',
      zero: 'لا توجد متتبعات متبقية لديك',
    );
    return '$_temp0';
  }

  @override
  String get reachedLimitTitle => 'لقد وصلت إلى الحد الأقصى';

  @override
  String get reachedLimitBody =>
      'لقد استنفدت جميع متتبعات الأسعار المتاحة لديك. قم بترقية خطتك لمواصلة تتبع الأسعار والحصول على متتبعات إضافية.';

  @override
  String get upgradePlan => 'قم بالترقية';

  @override
  String get notNow => 'ليس الآن';
}
