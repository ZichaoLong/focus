package org.focus.mobile;

import android.content.Context;
import android.net.Uri;
import android.os.*;
import android.webkit.*;
import androidx.webkit.WebViewCompat;
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.util.function.Consumer;
import org.json.*;

/** One foreground operation in the entry's cookie and HTTP authentication profile. */
final class UpdateConnection {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Context context;
    private final String siteId, origin, probe, agent, id;
    private final JSONObject call;
    private final boolean named;
    private final Consumer<String> done;
    private final Runnable timeout = () -> fail("连接超时，稍后核对服务端记录");
    private WebView web;
    private boolean probing = true, challenged, sent;

    UpdateConnection(Context context, JSONObject site, JSONObject call, boolean named, Consumer<String> done) {
        this.context = context; this.call = call; this.named = named; this.done = done;
        siteId = site.optString("id"); origin = Site.entry(site.optString("origin")); id = call.optString("id");
        probe = origin + "/focus-connect.txt"; agent = origin + "/focus-update.html";
    }

    void start() {
        main.postDelayed(timeout, 15000);
        probing = origin.startsWith("https:");
        load();
    }

    private void load() {
        WebView v = new WebView(context); web = v;
        if (named) WebViewCompat.setProfile(v, siteId);
        WebSettings s = v.getSettings();
        s.setJavaScriptEnabled(!probing); s.setDomStorageEnabled(!probing); s.setAllowFileAccess(false);
        s.setAllowContentAccess(false); s.setLoadsImagesAutomatically(false); s.setSaveFormData(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptThirdPartyCookies(v, false);
        if (probing) s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        v.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView page, WebResourceRequest req) {
                if (web == page && req.isForMainFrame()) login("入口发生跳转，请打开实例完成登录");
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView page, WebResourceRequest req) {
                String url = req.getUrl().toString();
                if (req.isForMainFrame() ? url.equals(probing ? probe : agent) :
                    !probing && Site.sameOrigin(url, origin) && allowed(req.getUrl(), req.getMethod())) return null;
                return new WebResourceResponse("text/plain","utf-8",new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onReceivedHttpAuthRequest(WebView page, HttpAuthHandler handler, String host, String realm) {
                if (web != page || !probing || challenged || !URI.create(origin).getHost().equalsIgnoreCase(host)) {
                    handler.cancel(); if (web == page) login("请打开实例验证入口凭据"); return;
                }
                challenged = true;
                new Thread(() -> {
                    try {
                        JSONObject entry = Site.verifyBasic(origin, realm) ? BasicVault.read(context, siteId, origin, realm) : null;
                        main.post(() -> {
                            if (web != page || entry == null) {
                                handler.cancel(); if (web == page) login("请打开实例完成入口认证"); return;
                            }
                            handler.proceed(entry.optString("user"), entry.optString("password"));
                        });
                    } catch (Exception e) {
                        main.post(() -> { handler.cancel(); if (web == page) fail("暂时无法核验入口认证"); });
                    }
                }).start();
            }
            @Override public boolean onRenderProcessGone(WebView page, RenderProcessGoneDetail detail) {
                if (web == page) fail("网页进程已退出，请重新核对服务端状态");
                return true;
            }
            @Override public void onReceivedError(WebView page, WebResourceRequest req, WebResourceError error) {
                if (web == page && req.isForMainFrame()) fail("入口暂不可达，请核对网络");
            }
            @Override public void onReceivedHttpError(WebView page, WebResourceRequest req, WebResourceResponse res) {
                if (web != page || !req.isForMainFrame()) return;
                int status = res.getStatusCode();
                if (status == 404 && !probing) login("此服务端未提供批量管理，请在实例设置中查看服务端更新");
                else if (status == 401 || status == 403) login("请打开实例完成登录或授权");
                else if (status >= 400) fail("入口返回 HTTP " + status);
            }
            @Override public void onPageFinished(WebView page, String url) {
                if (web != page) return;
                if (probing && probe.equals(url)) {
                    main.post(() -> { if (web == page) { disposeView(); probing = false; load(); } });
                } else if (!probing && agent.equals(url) && !sent) {
                    sent = true; main.removeCallbacks(timeout);
                    main.postDelayed(timeout, call.optString("action").equals("prepare") ? 75000 : 15000);
                    String args = JSONObject.quote(id) + "," + JSONObject.quote(call.optString("action")) + ","
                        + call.optJSONObject("body").toString();
                    page.evaluateJavascript("location.href===" + JSONObject.quote(agent)
                        + " && !!document.querySelector('meta[name=focus-update-agent][content=\"1\"]')"
                        + " && window.focusUpdateAgent?.(" + args + ")===true", ack -> {
                            if (web != page) return;
                            if ("true".equals(ack)) poll(page); else login("请打开实例登录，或先更新该服务端");
                        });
                }
            }
        });
        v.loadUrl(probing ? probe : agent);
    }

    private boolean allowed(Uri uri, String method) {
        String path = uri.getPath();
        if ("GET".equals(method)) return path.startsWith("/assets/") || path.equals("/api/update/installation");
        return "POST".equals(method) && (path.equals("/api/client/register") ||
            (call.optString("action").equals("prepare") && path.equals("/api/update/prepare-latest")) ||
            (call.optString("action").equals("apply") && path.equals("/api/update/apply")));
    }

    private void poll(WebView page) {
        if (page != web) return;
        page.evaluateJavascript("location.href===" + JSONObject.quote(agent) + " && window.focusUpdateReply || null", raw -> {
            if (page != web) return;
            try {
                if (raw != null && !raw.equals("null") && raw.length() < 65536) {
                    String result = (String)new JSONTokener(raw).nextValue();
                    if (!id.equals(new JSONObject(result).getString("id"))) throw new JSONException("id");
                    (named ? WebViewCompat.getProfile(page).getCookieManager() : CookieManager.getInstance()).flush();
                    finish(result); return;
                }
                main.postDelayed(() -> poll(page), 200);
            } catch (Exception e) { fail("无法核验更新响应"); }
        });
    }

    private void login(String message) {
        if (web != null) finish("{\"needs_entry\":true,\"error\":" + JSONObject.quote(message) + "}");
    }
    static String error(String message) {
        return "{\"error\":" + JSONObject.quote(message) + "}";
    }
    private void fail(String message) { if (web != null) finish(error(message)); }
    private void finish(String result) { close(); done.accept(result); }
    private void disposeView() {
        WebView old = web; web = null;
        if (old != null) { old.stopLoading(); old.destroy(); }
    }
    void close() { main.removeCallbacksAndMessages(null); disposeView(); }
}
