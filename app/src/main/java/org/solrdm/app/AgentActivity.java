package org.solrdm.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.Toast;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** Packaged, offline-first agent UI. Only bundled assets receive the native bridge. */
public final class AgentActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final String START_URL = "https://" + HOST + "/index.html";
    private static final int PICK_FILES = 3101;
    private static final int SAVE_EXPORT = 3102;
    private static final int MAX_EXPORT_BYTES = 2 * 1024 * 1024;
    private static final String[] FILE_TYPES = {
        "text/plain", "text/markdown", "text/csv", "application/json", "application/pdf",
        "image/png", "image/jpeg", "image/webp", "video/mp4", "video/webm"
    };
    private static final ExecutorService EXPORT_WORKER = Executors.newSingleThreadExecutor();
    private WebView webView;
    private ValueCallback<Uri[]> fileCallback;
    private byte[] pendingExport;

    @SuppressLint("SetJavaScriptEnabled")
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        FrameLayout container = new FrameLayout(this);
        container.setBackgroundColor(0xfff8f9f5);
        container.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        webView = new WebView(this);
        webView.setBackgroundColor(0xfff8f9f5);
        WebView.setWebContentsDebuggingEnabled(false);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true); // User-selected document URIs only; navigation is blocked below.
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setGeolocationEnabled(false);
        settings.setSafeBrowsingEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(true);
        webView.addJavascriptInterface(new NativeActions(), "SolrdmAndroid");
        webView.setWebViewClient(new LocalClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view,
                    ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (!isTrustedDocument(view.getUrl())) { callback.onReceiveValue(null); return true; }
                finishFileChoice(null);
                fileCallback = callback;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*");
                pick.putExtra(Intent.EXTRA_MIME_TYPES, FILE_TYPES);
                pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                pick.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                try { startActivityForResult(pick, PICK_FILES); }
                catch (ActivityNotFoundException error) {
                    finishFileChoice(null);
                    Toast.makeText(AgentActivity.this, "No document picker is available.", Toast.LENGTH_LONG).show();
                }
                return true;
            }
        });
        container.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(container);
        webView.loadUrl(START_URL);
    }

    WebView getAgentWebView() { return webView; }

    private static boolean isLocalOrigin(Uri uri) {
        return "https".equals(uri.getScheme()) && HOST.equals(uri.getHost())
                && uri.getUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443);
    }

    private static boolean isTrustedDocument(String value) {
        if (value == null) return false;
        Uri uri = Uri.parse(value);
        return isLocalOrigin(uri) && ("/index.html".equals(uri.getPath()) || "/".equals(uri.getPath()));
    }

    private static boolean isSafeWebLink(Uri uri) {
        return ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme()))
                && uri.getHost() != null && uri.getUserInfo() == null;
    }

    private final class LocalClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (request.isForMainFrame() && isTrustedDocument(uri.toString())) return false;
            if (request.isForMainFrame() && request.hasGesture() && isSafeWebLink(uri) && !isLocalOrigin(uri)) {
                try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
                catch (ActivityNotFoundException error) {
                    Toast.makeText(AgentActivity.this, "No browser is available to open this link.", Toast.LENGTH_LONG).show();
                }
            }
            return true;
        }

        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (isLocalOrigin(uri)) {
                if (!"GET".equals(request.getMethod())) return errorResponse(405, "Method Not Allowed");
                String path = uri.getPath();
                String name;
                String mime;
                if ("/".equals(path) || "/index.html".equals(path)) { name = "index.html"; mime = "text/html"; }
                else if ("/style.css".equals(path)) { name = "style.css"; mime = "text/css"; }
                else if ("/app.js".equals(path)) { name = "app.js"; mime = "application/javascript"; }
                else if ("/android-adapter.js".equals(path)) { name = "android-adapter.js"; mime = "application/javascript"; }
                else return errorResponse(404, "Not Found");
                try {
                    InputStream bytes = getAssets().open("agent/" + name);
                    Map<String, String> headers = securityHeaders();
                    return new WebResourceResponse(mime, "UTF-8", 200, "OK", headers, bytes);
                } catch (IOException error) { return errorResponse(404, "Not Found"); }
            }
            // The only online tool in this APK retrieves public Crossref metadata.
            if ("GET".equals(request.getMethod()) && "https".equals(uri.getScheme())
                    && "api.crossref.org".equals(uri.getHost()) && "/works".equals(uri.getPath())
                    && uri.getUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443)) return null;
            return errorResponse(403, "Forbidden");
        }
    }

    private static Map<String, String> securityHeaders() {
        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", "no-store");
        headers.put("X-Content-Type-Options", "nosniff");
        headers.put("Referrer-Policy", "no-referrer");
        headers.put("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                + "img-src 'self' data: blob:; media-src blob:; connect-src 'self' https://api.crossref.org; "
                + "object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'self'");
        return headers;
    }

    private static WebResourceResponse errorResponse(int status, String reason) {
        return new WebResourceResponse("text/plain", "UTF-8", status, reason, securityHeaders(),
                new ByteArrayInputStream(reason.getBytes(StandardCharsets.UTF_8)));
    }

    public final class NativeActions {
        @JavascriptInterface public void openEngine() {
            runOnUiThread(() -> {
                if (!isFinishing() && !isDestroyed() && isTrustedDocument(webView.getUrl()))
                    startActivity(new Intent(AgentActivity.this, MainActivity.class));
            });
        }

        @JavascriptInterface public void saveExport(String filename, String mime, String text) {
            if (text == null || text.length() > MAX_EXPORT_BYTES || filename == null || filename.length() > 120) {
                exportResult(false, "The export is too large or has an invalid name."); return;
            }
            if (!"application/json".equals(mime) && !"text/markdown".equals(mime) && !"text/plain".equals(mime)) {
                exportResult(false, "This export format is unsupported."); return;
            }
            final byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
            if (bytes.length > MAX_EXPORT_BYTES) { exportResult(false, "Exports are limited to 2 MB."); return; }
            final String safeName = filename.replaceAll("[^A-Za-z0-9._-]", "_");
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed() || !isTrustedDocument(webView.getUrl())) return;
                if (pendingExport != null) { exportResult(false, "Finish or cancel the current export first."); return; }
                pendingExport = bytes;
                Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                save.addCategory(Intent.CATEGORY_OPENABLE);
                save.setType(mime);
                save.putExtra(Intent.EXTRA_TITLE, safeName.isEmpty() ? "solrdm-export.txt" : safeName);
                save.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                try { startActivityForResult(save, SAVE_EXPORT); }
                catch (ActivityNotFoundException error) {
                    pendingExport = null;
                    exportResult(false, "No document saver is available.");
                }
            });
        }
    }

    private void finishFileChoice(Uri[] uris) {
        if (fileCallback != null) {
            ValueCallback<Uri[]> callback = fileCallback;
            fileCallback = null;
            callback.onReceiveValue(uris);
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PICK_FILES) {
            Set<Uri> selected = new LinkedHashSet<>();
            if (resultCode == RESULT_OK && data != null) {
                ClipData clip = data.getClipData();
                if (clip != null) {
                    for (int i = 0; i < clip.getItemCount() && selected.size() < 3; i++) {
                        Uri uri = clip.getItemAt(i).getUri();
                        if (uri != null && "content".equals(uri.getScheme())) selected.add(uri);
                    }
                } else if (data.getData() != null && "content".equals(data.getData().getScheme())) selected.add(data.getData());
            }
            finishFileChoice(selected.isEmpty() ? null : selected.toArray(new Uri[0]));
        } else if (requestCode == SAVE_EXPORT) {
            final byte[] bytes = pendingExport;
            pendingExport = null;
            final Uri uri = data == null ? null : data.getData();
            if (resultCode != RESULT_OK || uri == null || !"content".equals(uri.getScheme()) || bytes == null) {
                exportResult(false, "Export cancelled. No file was saved."); return;
            }
            final android.content.ContentResolver resolver = getApplicationContext().getContentResolver();
            EXPORT_WORKER.execute(() -> {
                try (OutputStream output = resolver.openOutputStream(uri, "wt")) {
                    if (output == null) throw new IOException("No output stream");
                    output.write(bytes);
                    output.flush();
                    exportResult(true, "Conversation exported to the selected document.");
                } catch (IOException | SecurityException error) {
                    exportResult(false, "The selected document could not be written.");
                }
            });
        }
    }

    private void exportResult(boolean success, String message) {
        runOnUiThread(() -> {
            if (isFinishing() || isDestroyed() || webView == null || !isTrustedDocument(webView.getUrl())) return;
            webView.evaluateJavascript("if (typeof window.__solrdmExportResult === 'function') "
                    + "window.__solrdmExportResult(" + success + "," + JSONObject.quote(message) + ");", null);
        });
    }

    @Override protected void onDestroy() {
        finishFileChoice(null);
        pendingExport = null;
        if (webView != null) {
            webView.removeJavascriptInterface("SolrdmAndroid");
            webView.stopLoading();
            if (webView.getParent() instanceof FrameLayout) ((FrameLayout) webView.getParent()).removeView(webView);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
