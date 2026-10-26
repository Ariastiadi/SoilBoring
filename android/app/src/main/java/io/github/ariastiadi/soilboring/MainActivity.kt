package io.github.ariastiadi.soilboring

import android.Manifest
import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Typeface
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.print.PrintAttributes
import android.print.PrintManager
import android.provider.MediaStore
import android.util.Base64
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.JavascriptInterface
import android.webkit.MimeTypeMap
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * SoilBoring for Android: the web app (https://soilboring.vercel.app) in a WebView, with what a
 * browser tab cannot do well on a phone in the field:
 *
 * - photos straight from the camera or the gallery for logs and lab sheets;
 * - the GPS position for boreholes and survey points;
 * - exports (CSV, KML, AGS4, recovery codes) saved to Download/SoilBoring;
 * - "Print / save as PDF" through the Android print dialog (A4);
 * - the back button, and a retry screen when there is no connection and nothing is cached.
 *
 * Offline logging is the web app's own (service worker + browser storage), which the WebView keeps.
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private lateinit var topBar: View
    private lateinit var bottomBar: View
    private lateinit var offline: View

    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var cameraUri: Uri? = null
    private var geoOrigin: String? = null
    private var geoCallback: GeolocationPermissions.Callback? = null
    private var pendingSave: PendingFile? = null
    private var mainFrameFailed = false
    private var backCallback: Any? = null

    /** Host of the page now shown; the bridge answers only our own pages. */
    @Volatile
    private var currentHost: String? = null

    private class PendingFile(val bytes: ByteArray, val name: String, val mime: String)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        web = WebView(this)
        topBar = View(this).apply { setBackgroundColor(getColor(R.color.sunken)) }
        bottomBar = View(this).apply { setBackgroundColor(getColor(R.color.surface)) }
        offline = buildOfflineView()

        val content = FrameLayout(this).apply {
            addView(web, FrameLayout.LayoutParams(MATCH, MATCH))
            addView(offline, FrameLayout.LayoutParams(MATCH, MATCH))
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(getColor(R.color.sunken))
            addView(topBar, LinearLayout.LayoutParams(MATCH, 0))
            addView(content, LinearLayout.LayoutParams(MATCH, 0, 1f))
            addView(bottomBar, LinearLayout.LayoutParams(MATCH, 0))
        }
        setContentView(root)
        setUpEdgeToEdge(root)

        val settings = web.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.setGeolocationEnabled(true)
        settings.allowFileAccess = false
        settings.allowContentAccess = true
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        settings.mediaPlaybackRequiresUserGesture = true
        settings.userAgentString = settings.userAgentString + " SoilBoringAndroid/" + appVersion()
        CookieManager.getInstance().setAcceptCookie(true)

        web.addJavascriptInterface(Bridge(), BRIDGE)
        web.webViewClient = Client()
        web.webChromeClient = Chrome()
        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            download(url, userAgent, contentDisposition, mimeType)
        }

        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) {
            web.loadUrl(HOME)
        }
    }

    // ---------------------------------------------------------------- layout

    @TargetApi(30)
    private fun setUpEdgeToEdge(root: View) {
        if (Build.VERSION.SDK_INT < 30) return // the window keeps clear of the bars and the keyboard
        window.setDecorFitsSystemWindows(false)
        window.insetsController?.setSystemBarsAppearance(
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
        )
        root.setOnApplyWindowInsetsListener { _, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            root.setPadding(bars.left, 0, bars.right, 0)
            setHeight(topBar, bars.top)
            setHeight(bottomBar, maxOf(bars.bottom, ime.bottom))
            WindowInsets.CONSUMED
        }
    }

    private fun setHeight(view: View, height: Int) {
        val lp = view.layoutParams
        if (lp.height != height) {
            lp.height = height
            view.layoutParams = lp
        }
    }

    private fun buildOfflineView(): View {
        val pad = dp(24)
        val title = TextView(this).apply {
            text = getString(R.string.offline_title)
            setTextColor(getColor(R.color.ink))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            typeface = Typeface.DEFAULT_BOLD
        }
        val body = TextView(this).apply {
            text = getString(R.string.offline_body)
            setTextColor(getColor(R.color.ink2))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setPadding(0, dp(8), 0, dp(20))
        }
        val retry = Button(this).apply {
            text = getString(R.string.retry)
            isAllCaps = false
            setOnClickListener { retry() }
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(pad, pad, pad, pad)
            setBackgroundColor(getColor(R.color.paper))
            addView(title)
            addView(body)
            addView(retry, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            visibility = View.GONE
            isClickable = true
        }
    }

    private fun retry() {
        offline.visibility = View.GONE
        val url = web.url
        if (url.isNullOrBlank() || url.startsWith("about:") || url.startsWith("data:")) web.loadUrl(HOME) else web.reload()
    }

    // ---------------------------------------------------------------- web view clients

    private inner class Client : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val uri = request.url
            if (isOurs(uri)) return false
            if (uri.scheme == "blob" || uri.scheme == "data" || uri.scheme == "about") return false
            openExternally(uri)
            return true
        }

        override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) {
            currentHost = url?.let { Uri.parse(it).host }
            mainFrameFailed = false
        }

        override fun onPageFinished(view: WebView, url: String?) {
            currentHost = url?.let { Uri.parse(it).host }
            if (!mainFrameFailed) offline.visibility = View.GONE
            if (url != null && isOurs(Uri.parse(url))) view.evaluateJavascript(SHIM, null)
            CookieManager.getInstance().flush()
        }

        override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) {
            currentHost = url?.let { Uri.parse(it).host }
            updateBackCallback()
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (request.isForMainFrame) {
                mainFrameFailed = true
                offline.visibility = View.VISIBLE
            }
        }

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            // The page's renderer crashed or was killed for memory: start again instead of closing the app.
            recreate()
            return true
        }
    }

    private inner class Chrome : WebChromeClient() {
        override fun onShowFileChooser(
            view: WebView,
            callback: ValueCallback<Array<Uri>>,
            params: FileChooserParams,
        ): Boolean {
            fileCallback?.onReceiveValue(null)
            fileCallback = callback
            discardCameraPhoto()

            val pick = params.createIntent()
            if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)

            val accept = params.acceptTypes.map { it.trim().lowercase(Locale.ROOT) }.filter { it.isNotEmpty() }
            val wantsImage = accept.isEmpty() || accept.any {
                it.startsWith("image/") || it == "*/*" || it in listOf(".jpg", ".jpeg", ".png", ".heic", ".webp")
            }
            val camera = if (wantsImage) cameraIntent() else null

            val intent = if (camera != null && params.isCaptureEnabled) camera else
                Intent.createChooser(pick, getString(R.string.choose_file)).apply {
                    if (camera != null) putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(camera))
                }
            return try {
                startActivityForResult(intent, REQ_FILE)
                true
            } catch (e: ActivityNotFoundException) {
                fileCallback = null
                discardCameraPhoto()
                false
            }
        }

        override fun onGeolocationPermissionsShowPrompt(origin: String, callback: GeolocationPermissions.Callback) {
            if (!isOurs(Uri.parse(origin))) {
                callback.invoke(origin, false, false)
            } else if (hasLocationPermission()) {
                callback.invoke(origin, true, false)
            } else {
                geoOrigin = origin
                geoCallback = callback
                requestPermissions(
                    arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                    REQ_LOCATION,
                )
            }
        }

        override fun onPermissionRequest(request: PermissionRequest) {
            request.deny() // the app needs no camera stream or microphone in the page
        }
    }

    // ---------------------------------------------------------------- JavaScript bridge

    private inner class Bridge {
        @JavascriptInterface
        fun print(title: String?) {
            if (!bridgeAllowed()) return
            runOnUiThread { printPage(title) }
        }

        @JavascriptInterface
        fun saveFile(dataUrl: String?, name: String?, mime: String?) {
            if (!bridgeAllowed() || dataUrl == null) return
            val fileName = safeName(name)
            val comma = dataUrl.indexOf(',')
            val bytes = try {
                if (comma < 0) throw IllegalArgumentException("not a data URL")
                val header = dataUrl.substring(0, comma)
                val payload = dataUrl.substring(comma + 1)
                if (header.endsWith(";base64")) Base64.decode(payload, Base64.DEFAULT)
                else Uri.decode(payload).toByteArray(Charsets.UTF_8)
            } catch (e: IllegalArgumentException) {
                runOnUiThread { toast(getString(R.string.save_failed, fileName)) }
                return
            }
            val type = mime?.substringBefore(';')?.trim().takeUnless { it.isNullOrEmpty() } ?: guessMime(fileName)
            runOnUiThread { saveToDownloads(PendingFile(bytes, fileName, type)) }
        }

        @JavascriptInterface
        fun saveFailed(name: String?) {
            if (!bridgeAllowed()) return
            runOnUiThread { toast(getString(R.string.save_failed, safeName(name))) }
        }
    }

    private fun bridgeAllowed(): Boolean = currentHost == HOST

    private fun printPage(title: String?) {
        val job = title?.trim().takeUnless { it.isNullOrEmpty() } ?: getString(R.string.print_job)
        val manager = getSystemService(PrintManager::class.java) ?: return
        val attributes = PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build()
        manager.print(job, web.createPrintDocumentAdapter(job), attributes)
    }

    // ---------------------------------------------------------------- downloads

    private fun download(url: String, userAgent: String?, contentDisposition: String?, mimeType: String?) {
        val name = safeName(URLUtil.guessFileName(url, contentDisposition, mimeType))
        if (url.startsWith("blob:") || url.startsWith("data:")) {
            // A download link the page did not route through the shim: read it in the page.
            web.evaluateJavascript("window.__sbSave && window.__sbSave(${jsString(url)}, ${jsString(name)})", null)
            return
        }
        val uri = Uri.parse(url)
        if (uri.scheme != "https" && uri.scheme != "http") return
        if (Build.VERSION.SDK_INT < 29 && !hasStoragePermission()) {
            openExternally(uri) // let the browser fetch it
            return
        }
        try {
            val request = DownloadManager.Request(uri)
                .setMimeType(mimeType)
                .addRequestHeader("User-Agent", userAgent ?: web.settings.userAgentString)
                .setTitle(name)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "$FOLDER/$name")
            CookieManager.getInstance().getCookie(url)?.let { request.addRequestHeader("Cookie", it) }
            getSystemService(DownloadManager::class.java)?.enqueue(request)
            toast(getString(R.string.downloading, name))
        } catch (e: Exception) {
            toast(getString(R.string.save_failed, name))
        }
    }

    private fun saveToDownloads(file: PendingFile) {
        if (Build.VERSION.SDK_INT < 29 && !hasStoragePermission()) {
            pendingSave = file
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), REQ_STORAGE)
            return
        }
        val uri: Uri? = try {
            if (Build.VERSION.SDK_INT >= 29) writeWithMediaStore(file) else writeToPublicFolder(file)
        } catch (e: Exception) {
            null
        }
        if (uri == null) {
            toast(getString(R.string.save_failed, file.name))
            return
        }
        toast(getString(R.string.saved_to, file.name))
        if (Build.VERSION.SDK_INT >= 29) openSaved(uri, file)
    }

    @TargetApi(29)
    private fun writeWithMediaStore(file: PendingFile): Uri? {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, file.mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + FOLDER)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return null
        try {
            resolver.openOutputStream(uri)?.use { it.write(file.bytes) } ?: throw IllegalStateException("no stream")
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        } catch (e: Exception) {
            resolver.delete(uri, null, null)
            throw e
        }
        return uri
    }

    @Suppress("DEPRECATION")
    private fun writeToPublicFolder(file: PendingFile): Uri {
        val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), FOLDER)
        if (!dir.isDirectory && !dir.mkdirs()) throw IllegalStateException("cannot create $dir")
        var target = File(dir, file.name)
        var n = 1
        val stem = file.name.substringBeforeLast('.')
        val ext = file.name.substringAfterLast('.', "")
        while (target.exists()) {
            target = File(dir, if (ext.isEmpty()) "$stem ($n)" else "$stem ($n).$ext")
            n++
        }
        target.writeBytes(file.bytes)
        MediaScannerConnection.scanFile(this, arrayOf(target.absolutePath), arrayOf(file.mime), null)
        return Uri.fromFile(target)
    }

    private fun openSaved(uri: Uri, file: PendingFile) {
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, file.mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            startActivity(view)
        } catch (e: ActivityNotFoundException) {
            toast(getString(R.string.no_app, file.name))
        }
    }

    // ---------------------------------------------------------------- camera and files

    @TargetApi(29)
    private fun cameraIntent(): Intent? {
        if (Build.VERSION.SDK_INT < 29) return null // would need storage permission; the gallery still works
        if (!packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) return null
        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(Date())
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, "SoilBoring_$stamp.jpg")
            put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/" + FOLDER)
        }
        val uri = try {
            contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
        } catch (e: Exception) {
            null
        } ?: return null
        cameraUri = uri
        return Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            .putExtra(MediaStore.EXTRA_OUTPUT, uri)
            .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }

    private fun photoTaken(uri: Uri): Boolean = try {
        contentResolver.openFileDescriptor(uri, "r")?.use { it.statSize > 0 } ?: false
    } catch (e: Exception) {
        false
    }

    private fun discardCameraPhoto() {
        val uri = cameraUri ?: return
        cameraUri = null
        try {
            contentResolver.delete(uri, null, null)
        } catch (e: Exception) {
            // nothing to clean up
        }
    }

    @Deprecated("Activity result API of the platform Activity")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != REQ_FILE) {
            @Suppress("DEPRECATION")
            super.onActivityResult(requestCode, resultCode, data)
            return
        }
        val callback = fileCallback
        fileCallback = null
        var result: Array<Uri>? = null
        if (resultCode == RESULT_OK) {
            val picked = mutableListOf<Uri>()
            data?.clipData?.let { clip -> for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let(picked::add) }
            if (picked.isEmpty()) data?.data?.let(picked::add)
            val photo = cameraUri
            if (picked.isEmpty() && photo != null && photoTaken(photo)) {
                picked.add(photo)
                cameraUri = null // keep the photo in Pictures/SoilBoring
            }
            if (picked.isNotEmpty()) result = picked.toTypedArray()
        }
        discardCameraPhoto()
        callback?.onReceiveValue(result)
    }

    // ---------------------------------------------------------------- permissions

    private fun hasLocationPermission() =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun hasStoragePermission() =
        Build.VERSION.SDK_INT >= 29 ||
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val granted = grantResults.any { it == PackageManager.PERMISSION_GRANTED }
        when (requestCode) {
            REQ_LOCATION -> {
                val origin = geoOrigin
                val callback = geoCallback
                geoOrigin = null
                geoCallback = null
                if (origin != null && callback != null) callback.invoke(origin, granted, false)
            }
            REQ_STORAGE -> {
                val file = pendingSave
                pendingSave = null
                if (file != null) {
                    if (granted) saveToDownloads(file) else toast(getString(R.string.storage_denied))
                }
            }
        }
    }

    // ---------------------------------------------------------------- back button and lifecycle

    @TargetApi(33)
    private fun updateBackCallback() {
        if (Build.VERSION.SDK_INT < 33) return
        val canGoBack = web.canGoBack()
        val registered = backCallback as OnBackInvokedCallback?
        if (canGoBack && registered == null) {
            val callback = OnBackInvokedCallback { if (web.canGoBack()) web.goBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback)
            backCallback = callback
        } else if (!canGoBack && registered != null) {
            onBackInvokedDispatcher.unregisterOnBackInvokedCallback(registered)
            backCallback = null
        }
    }

    @Deprecated("Used before Android 13; later versions use OnBackInvokedCallback")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else moveTaskToBack(true)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
    }

    override fun onPause() {
        web.onPause()
        CookieManager.getInstance().flush()
        super.onPause()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        web.requestApplyInsets()
    }

    override fun onDestroy() {
        fileCallback?.onReceiveValue(null)
        fileCallback = null
        web.destroy()
        super.onDestroy()
    }

    // ---------------------------------------------------------------- helpers

    private fun isOurs(uri: Uri) = uri.scheme == "https" && uri.host == HOST

    private fun openExternally(uri: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: ActivityNotFoundException) {
            toast(getString(R.string.no_app, uri.toString()))
        }
    }

    private fun appVersion(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "1"
    } catch (e: PackageManager.NameNotFoundException) {
        "1"
    }

    private fun safeName(name: String?): String {
        val cleaned = (name ?: "").replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_").trim().trim('.')
        return cleaned.ifEmpty { "soilboring-download" }.take(120)
    }

    private fun guessMime(name: String): String {
        val ext = name.substringAfterLast('.', "").lowercase(Locale.ROOT)
        return when (ext) {
            "ags" -> "text/plain"
            "kml" -> "application/vnd.google-earth.kml+xml"
            else -> MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
        }
    }

    private fun jsString(value: String): String =
        "'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "") + "'"

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val HOST = "soilboring.vercel.app"
        private const val HOME = "https://$HOST/"
        private const val BRIDGE = "SoilBoringAndroid"
        private const val FOLDER = "SoilBoring"
        private const val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        private const val REQ_FILE = 1
        private const val REQ_LOCATION = 2
        private const val REQ_STORAGE = 3

        /**
         * Runs in every page of the app once it has loaded:
         * - window.print() opens the Android print dialog (a WebView ignores it otherwise);
         * - links with a download attribute to blob: or data: URLs (CSV, KML, AGS4, recovery codes)
         *   are read in the page and handed to the app, which saves them to Download/SoilBoring;
         * - URL.revokeObjectURL is delayed a minute so such a link can still be read.
         */
        private val SHIM = """
            (function () {
              if (window.__sbAndroid) return;
              window.__sbAndroid = true;
              var bridge = window.$BRIDGE;
              window.print = function () { bridge.print(document.title || ''); };
              var revoke = URL.revokeObjectURL.bind(URL);
              URL.revokeObjectURL = function (u) { setTimeout(function () { revoke(u); }, 60000); };
              function save(href, name) {
                fetch(href).then(function (r) { return r.blob(); }).then(function (b) {
                  var reader = new FileReader();
                  reader.onload = function () { bridge.saveFile(String(reader.result), name || '', b.type || ''); };
                  reader.onerror = function () { bridge.saveFailed(name || ''); };
                  reader.readAsDataURL(b);
                }).catch(function () { bridge.saveFailed(name || ''); });
              }
              window.__sbSave = save;
              function local(a) {
                var h = a.href || '';
                return a.hasAttribute('download') && (h.indexOf('blob:') === 0 || h.indexOf('data:') === 0);
              }
              var click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                if (local(this)) { save(this.href, this.getAttribute('download')); return; }
                return click.apply(this, arguments);
              };
              document.addEventListener('click', function (e) {
                var a = e.target && e.target.closest ? e.target.closest('a[download]') : null;
                if (a && local(a)) { e.preventDefault(); save(a.href, a.getAttribute('download')); }
              }, true);
            })();
        """.trimIndent()
    }
}
