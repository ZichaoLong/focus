package org.focus.mobile;

import android.app.*;
import android.content.*;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.*;
import android.print.PrintManager;
import android.text.InputType;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import androidx.webkit.WebViewCompat;
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.util.*;
import org.json.*;

public class ClientActivity extends Activity {
    public static final class Third extends ClientActivity {}
    public static final class Fourth extends ClientActivity {}
    public static final class Fifth extends ClientActivity {}

    private static final String PROBE = "/focus-connect.txt";
    private final boolean legacy = this instanceof LegacyClientActivity;
    private String id, origin, name, link, ticket = "";
    private boolean sso, probe, attempted, rejected, foreground, retryNeeded, remember, manual;
    private int backoff, generation, renderFailures;
    private long lastReauth;
    private JSONObject supplied;
    private SharedPreferences presentation;
    private WebView web;
    private FrameLayout frame;
    private LinearLayout notice;
    private Button switcher;
    private boolean selected = true, switching;
    private FileExchange files;
    private InstanceDrawer drawer;
    private PageSlots pages;
    private ApkUpdate apkUpdate;
    private String switchTarget = "";
    private Object pendingBack;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable retry = () -> { if (foreground && retryNeeded) openProbe(false); };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            JSONObject site = new JSONObject(getIntent().getStringExtra("site"));
            id = UUID.fromString(site.getString("id")).toString(); origin = Site.entry(site.getString("origin"));
            name = site.getString("name"); sso = site.optBoolean("sso");
            link = getIntent().getStringExtra("link"); getIntent().removeExtra("link");
            if (!id.equals(getSharedPreferences("instances", MODE_PRIVATE).getString("active", ""))) { finish(); return; }
            if (legacy) WebView.setDataDirectorySuffix(id);
            else PageSlots.attached(this);
        } catch (Exception e) { finish(); return; }
        presentation = getSharedPreferences("page-" + id, MODE_PRIVATE);
        files = new FileExchange(this);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        switcher = Views.button(this, layout, name + " ▾", this::pickInstance);
        switcher.setContentDescription("切换实例");
        notice = Views.column(this); layout.addView(notice);
        frame = new FrameLayout(this); layout.addView(frame, new LinearLayout.LayoutParams(-1, 0, 1));
        FrameLayout root = new FrameLayout(this);
        root.addView(layout); Views.install(this, root);
        drawer = new InstanceDrawer(this, root); apkUpdate = new ApkUpdate(this);
        if (!legacy && !getSharedPreferences("instances", MODE_PRIVATE).getBoolean("named-" + id, false)) {
            if (ProfileTransfer.snapshot(this, id).getBaseFile().exists()) { importProfile(); return; }
            getSharedPreferences("instances", MODE_PRIVATE).edit().putBoolean("named-" + id, true).commit();
        }
        openProbe(false);
    }

    private WebView newProfileView() {
        WebView view = new WebView(this);
        if (!legacy) WebViewCompat.setProfile(view, id);
        return view;
    }

    private void importProfile() {
        retireView();
        int epoch = generation;
        web = newProfileView();
        banner("正在恢复此实例原有的网页数据…", null, null);
        ProfileTransfer.restore(web, this, id, origin, ok -> {
            if (epoch != generation) return;
            if (!ok) {
                Views.message(this, "此网页配置暂时无法迁移，继续使用原有数据。");
                PageSlots.continueInLegacy(this, id, getIntent().getStringExtra("site"), link);
                return;
            }
            getSharedPreferences("instances", MODE_PRIVATE).edit().putBoolean("named-" + id, true).commit();
            ProfileTransfer.snapshot(this, id).delete();
            openProbe(false);
        });
    }

    private void banner(String message, String action, Runnable click) {
        notice.removeAllViews(); notice.setVisibility(View.VISIBLE);
        TextView text = new TextView(this); text.setText(message); notice.addView(text);
        if (action != null) Views.button(this, notice, action, click);
    }

    private void networkFailure(String message) {
        if (rejected) return;
        retryNeeded = true;
        banner(message, "立即重试", () -> openProbe(false));
        main.removeCallbacks(retry);
        if (foreground) main.postDelayed(retry, Math.min(30000L, 1000L << Math.min(backoff++, 5)));
    }

    private void retireView() {
        generation++; ticket = ""; pendingBack = null;
        if (apkUpdate != null) apkUpdate.cancel();
        if (files != null) files.cancel();
        if (web != null) { frame.removeView(web); web.stopLoading(); web.destroy(); web = null; }
    }

    private void openProbe(boolean editPassword) {
        if (!selected) return;
        main.removeCallbacks(retry); retireView();
        retryNeeded = false; probe = true; attempted = false; rejected = false; manual = editPassword;
        supplied = null;
        notice.setVisibility(View.GONE);
        if (origin.startsWith("http://")) { showPage(); return; }
        createView(false);
        web.loadUrl(origin + PROBE);
    }

    private void showPage() {
        if (!selected || !probe || rejected || retryNeeded) return;
        if (supplied != null) {
            try { if (remember) BasicVault.store(this, id, supplied); else BasicVault.erase(this, id); }
            catch (Exception e) { Views.message(this, "安全存储不可用，本次凭据仅在内存中使用"); }
        }
        supplied = null; backoff = 0;
        retireView(); probe = false; createView(true);
        Uri.Builder target = Uri.parse(origin + "/").buildUpon().appendQueryParameter("focusApp", "1");
        String thread = presentation.getString("thread", "");
        if (!thread.isEmpty()) target.appendQueryParameter("thread", thread);
        if (Site.root(link, origin)) target.encodedFragment(Uri.parse(link).getEncodedFragment());
        link = null;
        web.loadUrl(target.build().toString());
    }

    private void createView(boolean page) {
        final int epoch = generation;
        WebView view = newProfileView(); web = view; frame.addView(view);
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(page); settings.setDomStorageEnabled(page); settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false); settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSaveFormData(false); settings.setGeolocationEnabled(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, false);
        if (!page) {
            settings.setLoadsImagesAutomatically(false);
            settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        }
        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                String url = req.getUrl().toString();
                if (epoch != generation) return true;
                if (!page) {
                    if (req.isForMainFrame() && !url.equals(origin + PROBE)) main.post(() -> { if (epoch == generation) showPage(); });
                    return !req.isForMainFrame() || !url.equals(origin + PROBE);
                }
                if (!req.isForMainFrame()) return false;
                if (Site.sameOrigin(url, origin)) return false;
                if (Site.httpsPage(url)) {
                    if (sso) return false;
                    if (req.hasGesture() && !req.isRedirect()) openExternal(url);
                    return true;
                }
                if (req.hasGesture() && !req.isRedirect() && "http".equals(req.getUrl().getScheme()) && req.getUrl().getUserInfo() == null) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, req.getUrl())); } catch (ActivityNotFoundException ignored) {}
                }
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
                if (!page && (!req.isForMainFrame() || !(origin + PROBE).equals(req.getUrl().toString())))
                    return new WebResourceResponse("text/plain", "utf-8", new ByteArrayInputStream(new byte[0]));
                return null;
            }
            @Override public void onPageStarted(WebView v, String url, Bitmap icon) {
                if (epoch != generation) return;
                ticket = ""; pendingBack = null; files.cancel(); apkUpdate.cancel(); drawer.dismiss();
                switcher.setVisibility(View.VISIBLE);
                if (!selected) main.post(() -> { if (!selected && epoch == generation) retireView(); });
            }
            @Override public void onPageCommitVisible(WebView v, String url) {
                if (epoch == generation && page && Site.root(url, origin)) offer(v);
            }
            @Override public void onPageFinished(WebView v, String url) {
                if (epoch != generation || retryNeeded || rejected) return;
                if (!page && url.equals(origin + PROBE) && !checkingChallenge) {
                    main.post(() -> { if (epoch == generation && !checkingChallenge) showPage(); });
                } else if (page && Site.root(url, origin)) {
                    offer(v); (legacy ? CookieManager.getInstance() : WebViewCompat.getProfile(v).getCookieManager()).flush();
                }
            }
            @Override public void onReceivedHttpAuthRequest(WebView v, HttpAuthHandler handler, String host, String realm) {
                if (!selected || epoch != generation || !origin.startsWith("https://") || !URI.create(origin).getHost().equalsIgnoreCase(host)) { handler.cancel(); return; }
                if (page) {
                    handler.cancel();
                    if (Site.root(v.getUrl(), origin)) reauthenticate(v, false);
                } else challenge(handler, realm, epoch);
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError error) {
                if (epoch == generation && req.isForMainFrame() && !checkingChallenge && !rejected)
                    networkFailure("无法连接入口 (" + error.getErrorCode() + ")，等待网络恢复。");
            }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest req, WebResourceResponse res) {
                if (epoch != generation || !req.isForMainFrame()) return;
                if (page && origin.startsWith("https://") && res.getStatusCode() == 401 && Site.root(req.getUrl().toString(), origin)) {
                    reauthenticate(v, true); return;
                }
                if (!page && res.getStatusCode() == 401 && attempted) {
                    rejected = true; supplied = null;
                    banner("入口未接受凭据。", "更新凭据", () -> openProbe(true)); return;
                }
                if (!page && res.getStatusCode() == 403) {
                    rejected = true; supplied = null;
                    banner("入口拒绝访问 (HTTP 403)。", null, null); return;
                }
                if (res.getStatusCode() >= 500) networkFailure("入口返回 HTTP " + res.getStatusCode() + "，等待服务恢复。");
            }
            @Override public boolean onRenderProcessGone(WebView v, RenderProcessGoneDetail detail) {
                if (epoch == generation) {
                    retireView();
                    if (!selected) return true;
                    if (++renderFailures <= 2) openProbe(false);
                    else banner("网页进程已退出", "重建页面", () -> openProbe(false));
                }
                return true;
            }
        });
        if (!page) { checkingChallenge = false; return; }
        view.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                if (selected && epoch == generation && "focus-host-request/1".equals(message.message()) && Site.root(view.getUrl(), origin)) offer(view);
                return super.onConsoleMessage(message);
            }
            @Override public boolean onJsPrompt(WebView v, String url, String msg, String value, JsPromptResult result) {
                if (!msg.startsWith("focus/1/")) return false;
                String prefix = "focus/1/" + ticket + "/";
                if (!selected || epoch != generation || ticket.isEmpty() || !Site.root(v.getUrl(), origin)
                    || !Site.root(url, origin) || !msg.startsWith(prefix)) { result.cancel(); return true; }
                String op = msg.substring(prefix.length());
                if ("external".equals(op)) {
                    result.confirm(openExternal(value) ? "ok" : "error");
                } else if ("instances".equals(op)) {
                    result.confirm("ok"); main.post(() -> { if (epoch == generation) showDrawer(value); });
                } else if ("apk-save".equals(op)) {
                    apkUpdate.save(files, result);
                } else if (op.startsWith("apk-")) {
                    result.confirm(apkUpdate.handle(op, value));
                } else if ("chrome".equals(op)) {
                    switcher.setVisibility("web".equals(value) ? View.GONE : View.VISIBLE);
                    result.confirm("ok");
                } else if ("thread".equals(op)) {
                    boolean saved = value != null && value.length() <= 256 && presentation.edit().putString("thread", value).commit();
                    result.confirm(saved ? "ok" : "error");
                } else if ("print".equals(op)) {
                    PrintManager printer = getSystemService(PrintManager.class);
                    if (printer == null || value == null || value.isEmpty() || value.length() > 255) result.confirm("error");
                    else {
                        try { printer.print(value, v.createPrintDocumentAdapter(value), null); result.confirm("ok"); }
                        catch (RuntimeException error) { result.confirm("error"); }
                    }
                } else files.handle(op, value == null ? "" : value, result);
                return true;
            }
            @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (!selected || epoch != generation || !Site.root(v.getUrl(), origin)) { cb.onReceiveValue(null); return true; }
                return files.upload(cb, params);
            }
        });
    }

    private void reauthenticate(WebView view, boolean failedMainRequest) {
        banner("入口要求 HTTP 认证。", "验证入口", () -> openProbe(false));
        if (!foreground || SystemClock.elapsedRealtime() - lastReauth < 60000 && lastReauth != 0) return;
        final int epoch = generation;
        Runnable verify = () -> {
            if (generation != epoch || probe) return;
            lastReauth = SystemClock.elapsedRealtime();
            openProbe(false);
        };
        if (failedMainRequest) { main.post(verify); return; }
        view.evaluateJavascript("window.__focusCanRebuild?.() === true && (dispatchEvent(new Event('focus-host-pause')),true)",
            value -> { if ("true".equals(value)) main.post(verify); });
    }

    private boolean checkingChallenge;
    private void challenge(HttpAuthHandler handler, String realm, int epoch) {
        if (rejected || attempted || checkingChallenge) {
            rejected = true; handler.cancel(); supplied = null;
            banner("入口未接受凭据。", "更新凭据", () -> openProbe(true)); return;
        }
        checkingChallenge = true;
        // Android exposes just host + realm. Verify the scheme on the exact inert
        // GET with redirects disabled before releasing anything to its handler.
        new Thread(() -> {
            boolean basic = false, unavailable = false;
            javax.net.ssl.HttpsURLConnection conn = null;
            try {
                conn = (javax.net.ssl.HttpsURLConnection) URI.create(origin + PROBE).toURL().openConnection();
                conn.setInstanceFollowRedirects(false); conn.setUseCaches(false);
                conn.setConnectTimeout(5000); conn.setReadTimeout(5000);
                int status = conn.getResponseCode();
                unavailable = status >= 500 || status == 408 || status == 429;
                basic = status == 401 && Site.basicRealm(conn.getHeaderField("WWW-Authenticate"), realm);
            } catch (Exception e) { unavailable = true; }
            finally { if (conn != null) conn.disconnect(); }
            final boolean valid = basic, failed = unavailable;
            main.post(() -> {
                if (epoch != generation) { handler.cancel(); return; }
                if (!valid) {
                    handler.cancel();
                    if (failed) { checkingChallenge = false; networkFailure("暂时无法核对入口认证。"); }
                    else { rejected = true; banner("入口没有匹配的标准 Basic 挑战。", null, null); }
                    return;
                }
                JSONObject saved = null;
                try { if (!manual) saved = BasicVault.read(this, id, origin, realm); }
                catch (Exception e) { Views.message(this, "无法读取已保存的凭据"); }
                if (saved != null) { provide(handler, saved, true); return; }
                LinearLayout form = Views.column(this);
                EditText user = Views.field(this, form, "用户名", "");
                EditText pass = Views.field(this, form, "密码", "");
                pass.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
                CheckBox keep = new CheckBox(this); keep.setText("安全保存凭据"); form.addView(keep);
                Runnable cancel = () -> {
                    handler.cancel(); rejected = true;
                    banner("已取消入口认证。", "重新输入", () -> openProbe(true));
                };
                new AlertDialog.Builder(this).setTitle("HTTP Basic · " + realm).setMessage(origin).setView(form)
                    .setNegativeButton("取消", (d,w) -> cancel.run()).setOnCancelListener(d -> cancel.run())
                    .setPositiveButton("登录", (d,w) -> {
                        if (generation != epoch) { handler.cancel(); return; }
                        try { provide(handler, new JSONObject().put("origin", origin).put("realm", realm)
                            .put("user", user.getText().toString()).put("password", pass.getText().toString()), keep.isChecked()); }
                        catch (JSONException e) { cancel.run(); }
                    }).show();
            });
        }, "focus-basic-challenge").start();
    }
    private void provide(HttpAuthHandler handler, JSONObject entry, boolean keep) {
        supplied = entry; attempted = true; remember = keep; checkingChallenge = false;
        handler.proceed(entry.optString("user"), entry.optString("password"));
    }

    private void offer(WebView view) {
        if (!selected) return;
        if (ticket.isEmpty()) ticket = UUID.randomUUID().toString();
        String printFeature = getPackageManager().hasSystemFeature(android.content.pm.PackageManager.FEATURE_PRINTING) ? ",'print'" : "";
        String js = "if(window===top && location.origin===" + JSONObject.quote(origin)
            + " && location.pathname==='/' && window.__focusMobile?.ticket!=='" + ticket + "' && document.querySelector('meta[name=focus-mobile-contract][content=\"1\"]')){"
            + "const url=new URL(location.href);if(!url.searchParams.has('focusApp') && !url.searchParams.has('print') && !url.hash){"
            + "url.searchParams.set('focusApp','1');location.replace(url.href)}else{"
            + "window.__focusMobile=Object.assign(window.__focusMobile||{},{version:1,instance:'" + id + "',name:" + JSONObject.quote(name) + ",ticket:'" + ticket + "',features:['wake','resume','save','thread','tabs','drawer','navigation','android-update'" + printFeature + "]});"
            + "dispatchEvent(new Event('focus-host-ready'))}}";
        view.evaluateJavascript(js, null);
    }
    private void signal(String event) {
        if (web != null && !probe && Site.root(web.getUrl(), origin))
            web.evaluateJavascript("if(window.__focusMobile)dispatchEvent(new Event('focus-host-" + event + "'))", null);
    }
    @Override protected void onResume() { super.onResume(); foreground = true; if (web != null) web.onResume(); signal("resume"); if (retryNeeded) main.post(retry); }
    @Override protected void onPause() { foreground = false; pendingBack = null; main.removeCallbacks(retry); signal("pause"); if (web != null) web.onPause(); super.onPause(); }
    @Override protected void onStop() {
        super.onStop();
        if (!selected && !isFinishing()) moveTaskToBack(true);
    }
    private void pickInstance() { showDrawer(""); }

    private void showDrawer(String theme) {
        if (!selected || switching) return;
        pendingBack = null;
        try {
            JSONArray sites = new JSONArray(getSharedPreferences("instances", MODE_PRIVATE).getString("list", "[]"));
            boolean dark = "dark".equals(theme) || (theme.isEmpty() && (getResources().getConfiguration().uiMode & 48) == 32);
            drawer.show(sites, id, dark, this::switchInstance, () -> switchInstance(""), this::about);
        } catch (JSONException e) { Views.message(this, "无法读取实例列表"); }
    }

    private void about() {
        if (!selected || probe || ticket.isEmpty() || web == null || !Site.root(web.getUrl(), origin)) {
            Views.message(this, "Focus Mobile · 连接实例后可检查客户端更新"); return;
        }
        web.evaluateJavascript("!dispatchEvent(new Event('focus-host-about',{cancelable:true}))", handled -> {
            if (!"true".equals(handled)) Views.message(this, "请先更新此实例的 Focus Web 以检查客户端更新。");
        });
    }

    private void switchInstance(String target) {
        if (!selected || switching) return;
        switchTarget = target; switching = true; selected = false; apkUpdate.cancel();
        main.removeCallbacks(retry);
        signal("pause");
        Runnable cold = () -> completeSwitch(false);
        main.postDelayed(cold, 800);
        if (legacy || web == null || probe || ticket.isEmpty() || !Site.root(web.getUrl(), origin)) { completeSwitch(false); return; }
        int epoch = generation;
        web.evaluateJavascript("window.__focusSetTabActive?.(false) === true", reply -> {
            main.removeCallbacks(cold);
            completeSwitch(epoch == generation && "true".equals(reply));
        });
    }

    private void completeSwitch(boolean retained) {
        if (!switching) return;
        switching = false;
        if (!retained) retireView();
        if (!legacy && !switchTarget.isEmpty()) {
            SharedPreferences prefs = getSharedPreferences("instances", MODE_PRIVATE);
            try {
                if (pages == null) pages = new PageSlots(this, prefs);
                if (pages.openNamedTarget(switchTarget, new JSONArray(prefs.getString("list", "[]")))) return;
            } catch (JSONException ignored) { /* The manager can recover the local entry list. */ }
        }
        startActivity(new Intent(this, MainActivity.class).setAction(MainActivity.PICK).putExtra("target", switchTarget).putExtra("return-instance", id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP));
        if (legacy) finishAndRemoveTask();
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        try {
            JSONObject site = new JSONObject(intent.getStringExtra("site"));
            if (!id.equals(site.getString("id")) || !origin.equals(Site.entry(site.getString("origin")))) { finish(); return; }
            boolean policyChanged = sso != site.optBoolean("sso");
            boolean renamed = !name.equals(site.getString("name"));
            name = site.getString("name"); sso = site.optBoolean("sso");
            link = intent.getStringExtra("link"); intent.removeExtra("link"); setIntent(intent);
            switcher.setText(name + " ▾");
            switching = false; boolean wasParked = !selected; selected = true;
            if (!legacy && ProfileTransfer.snapshot(this, id).getBaseFile().exists() &&
                    !getSharedPreferences("instances", MODE_PRIVATE).getBoolean("named-" + id, false)) { importProfile(); return; }
            if (web == null || policyChanged || Site.root(link, origin) || intent.getBooleanExtra("reload", false)) openProbe(false);
            else {
                if (renamed && !ticket.isEmpty() && Site.root(web.getUrl(), origin))
                    web.evaluateJavascript("if(window.__focusMobile?.ticket===" + JSONObject.quote(ticket) + "){window.__focusMobile.name=" + JSONObject.quote(name)
                        + ";dispatchEvent(new Event('focus-host-ready'))}", null);
                if (wasParked) web.evaluateJavascript("window.__focusSetTabActive?.(true)", null);
            }
        } catch (Exception e) { finish(); }
    }

    @Override public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        if (!selected && !switching && level != TRIM_MEMORY_UI_HIDDEN && level >= TRIM_MEMORY_RUNNING_LOW) retireView();
    }
    private boolean openExternal(String url) {
        if (!selected || !foreground || switching || !Site.httpsPage(url) || Site.sameOrigin(url, origin)) return false;
        startActivity(new Intent(this, ExternalPageActivity.class).setData(Uri.parse(url)));
        return true;
    }

    private void browserBack() {
        if (web != null && !probe && web.canGoBack()) web.goBack();
        else moveTaskToBack(true);
    }

    @Override public void onBackPressed() {
        if ((drawer != null && drawer.dismiss()) || !selected || switching || pendingBack != null) return;
        if (web == null || probe || ticket.isEmpty() || !Site.root(web.getUrl(), origin)) { browserBack(); return; }
        Object press = new Object(); pendingBack = press;
        // 0 is a confirmed older document. An absent/stale reply must never perform a second action.
        String script = "if(!window.__focusMobile){0}else if(window.__focusMobile.ticket===" + JSONObject.quote(ticket)
            + "){typeof window.__focusBack==='function'?window.__focusBack():0}";
        web.evaluateJavascript(script, reply -> {
            if (pendingBack != press) return;
            pendingBack = null;
            if ("false".equals(reply)) moveTaskToBack(true);
            else if ("0".equals(reply)) browserBack();
        });
    }
    @Override protected void onActivityResult(int code, int result, Intent data) { super.onActivityResult(code,result,data); if (code == ApkUpdate.INSTALL_PERMISSION) apkUpdate.permissionResult(); else files.result(code,result,data); }
    void releaseTask() { selected = false; retireView(); finishAndRemoveTask(); }

    @Override protected void onDestroy() {
        main.removeCallbacksAndMessages(null); retireView(); if (files != null) files.dispose();
        if (pages != null) pages.finishOpening();
        PageSlots.detached(this);
        super.onDestroy();
        if (legacy) android.os.Process.killProcess(android.os.Process.myPid());
    }
}
