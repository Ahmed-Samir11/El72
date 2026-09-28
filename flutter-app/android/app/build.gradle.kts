plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

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
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}
