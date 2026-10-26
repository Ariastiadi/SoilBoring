plugins {
    // AGP 9 has built-in Kotlin: do NOT add org.jetbrains.kotlin.android
    id("com.android.application") version "9.4.0"
}

android {
    namespace = "io.github.ariastiadi.soilboring"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.github.ariastiadi.soilboring"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    // The release key comes from the SIGNING_KEY secret (see .github/workflows/android.yml).
    // Without it (forks, pull requests) the APK is signed with the debug key.
    signingConfigs {
        create("release") {
            val ks = System.getenv("KEYSTORE_FILE")
            if (ks != null) {
                storeFile = file(ks)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = "soilboring"
                keyPassword = System.getenv("KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (System.getenv("KEYSTORE_FILE") != null)
                signingConfigs.getByName("release")
            else
                signingConfigs.getByName("debug")
        }
    }

    // No Google-signed dependency metadata blob in the APK
    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }
}
