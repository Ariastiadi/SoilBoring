# Methods the web page calls through the JavaScript bridge
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
