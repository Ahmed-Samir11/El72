import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// MS4 release signing: reads android/key.properties when present (created
// locally via scripts/make-release-keystore.sh, or injected by CI from the
// KEY_STORE secret). Absent file => debug signing, so local
// `flutter run --release` keeps working out of the box.
val keystorePropertiesFile = rootProject.file("android/key.properties")
val keystoreProperties: Properties? =
    if (keystorePropertiesFile.exists()) {
        Properties().also { p -> keystorePropertiesFile.inputStream().use { p.load(it) } }
    } else {
        null
    }

// MS4 versioning: CI may override versionCode via the VERSION_CODE env var
// (auto-incremented in the flutter-ci job); defaults to the pubspec value.
val ciVersionCode: Int? = System.getenv("VERSION_CODE")?.toIntOrNull()

android {
    // Play Store package identity. If `com.elhaq.tracker` turns out to be
    // taken, switch to the fallback `com.el72.elhaq` (owner verification).
    namespace = "com.elhaq.tracker"
    // Pinned explicitly (WS3): compileSdk == targetSdk so the SDK levels are
    // deterministic and never depend on the Flutter template defaults.
    compileSdk = 35

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        applicationId = "com.elhaq.tracker"
        // Pinned explicitly (WS3): minSdk 24 drops legacy API 21-23 devices;
        // targetSdk 35 is the current Play requirement.
        minSdk = 24
        targetSdk = 35
        versionCode = ciVersionCode ?: flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            keystoreProperties?.let { kp ->
                keyAlias = kp["keyAlias"] as String
                keyPassword = kp["keyPassword"] as String
                storeFile = kp["storeFile"]?.let { f -> rootProject.file(f) }
                storePassword = kp["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // MS4: release signing when key.properties is present, debug
            // signing locally when it is not.
            signingConfig = signingConfigs.getByName(
                if (keystoreProperties == null) "debug" else "release",
            )
        }
    }
}

flutter {
    source = "../.."
}
