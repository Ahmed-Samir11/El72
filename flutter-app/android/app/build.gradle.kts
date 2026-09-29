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
// The Gradle root project is flutter-app/android/, so the file is relative
// to that directory.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties: Properties? =
    if (keystorePropertiesFile.exists()) {
        Properties().also { p -> keystorePropertiesFile.inputStream().use { p.load(it) } }
    } else {
        null
    }

// MS4 versioning: CI may override versionCode via the VERSION_CODE env var.
// A set-but-invalid value fails the build instead of silently falling back,
// so a mistyped version can never ship.
val ciVersionCode: Int? = System.getenv("VERSION_CODE")?.let { raw ->
    val v = raw.toIntOrNull()
    if (v == null || v < 1) {
        error("VERSION_CODE env var '$raw' is not a positive integer")
    }
    v
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
        versionCode = ciVersionCode ?: flutter.versionCode
        versionName = flutter.versionName
    }

    // The release signing config is only created when key.properties is
    // present, so a missing file can never leave a half-configured release
    // signing block behind.
    if (keystoreProperties != null) {
    signingConfigs {
        create("release") {
            keystoreProperties?.let { kp ->
                // Fail with a clear message if the file exists but is
                // incomplete (MS4): a half-filled key.properties must never
                // silently produce a debug-signed bundle.
                // Locals are deliberately named so they cannot shadow the
                // SigningConfig properties being assigned below.
                val alias = kp.getProperty("keyAlias")
                    ?: error("android/key.properties exists but is missing 'keyAlias'")
                val kpass = kp.getProperty("keyPassword")
                    ?: error("android/key.properties exists but is missing 'keyPassword'")
                val sfile = kp.getProperty("storeFile")
                    ?: error("android/key.properties exists but is missing 'storeFile'")
                val spass = kp.getProperty("storePassword")
                    ?: error("android/key.properties exists but is missing 'storePassword'")
                keyAlias = alias
                this.keyPassword = kpass
                this.storeFile = rootProject.file(sfile)
                this.storePassword = spass
            }
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
