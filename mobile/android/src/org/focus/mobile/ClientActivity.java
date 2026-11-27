package org.focus.mobile;

import android.app.*;
import android.content.*;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.*;
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
    private Runnable pendingSwitcher;
    private boolean selected = true, switching;
    private FileExchange files;
    private InstanceDrawer drawer;
    private PageSlots pages;
    private ApkUpdate apkUpdate;
    private RecordsStore records;
    private RecordsPanel reader;
    private ConversationStore conversation;
    private SavedConversation savedChat;
    private LinearLayout opening;
    private TextView openingMessage;
    private Button retryEntry, savedRecords;
    private String firstScreen;
    private boolean checkingScreen;
    private boolean recordScopeConfirmed, basicIdentityChanged;
    private FrameLayout surface;
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
        switcher = new Button(this, null, android.R.attr.borderlessButtonStyle);
        switcher.setText("切换实例");
        switcher.setVisibility(View.GONE);
        switcher.setOnClickListener(v -> showDrawer("", false));
        layout.addView(switcher, ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        notice = Views.column(this); layout.addView(notice);
        frame = new FrameLayout(this); layout.addView(frame, new LinearLayout.LayoutParams(-1, 0, 1));
        FrameLayout root = new FrameLayout(this);
        surface = root; root.addView(layout); Views.install(this, root);
        drawer = new InstanceDrawer(this, root); apkUpdate = new ApkUpdate(this);
        try {
            String requested = new JSONObject(getIntent().getStringExtra("site")).optString("recordThread");
            records = new RecordsStore(this);
            records.call("register",id,origin,new JSONObject());
            conversation=new ConversationStore(this,records,id,origin);
            if (!requested.isEmpty()) openRecords(requested);
        } catch (Exception unavailable) { /* The online client works without a readable disk. */ }
        try (java.util.Scanner scanner=new java.util.Scanner(getAssets().open("first-screen.js"),"UTF-8").useDelimiter("\\A")) {
            firstScreen=scanner.next();
        } catch (java.io.IOException missing) { firstScreen="true"; }
        showOpening();
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

    // The probe, redirects and the Focus document share one wait for a usable drawer.
    private void awaitWebSwitcher() {
        if (pendingSwitcher != null || switcher.getVisibility() == View.VISIBLE) return;
        pendingSwitcher = () -> setNativeSwitcher(true);
        main.postDelayed(pendingSwitcher, 2500);
    }

    private void setNativeSwitcher(boolean visible) {
        if (pendingSwitcher != null) main.removeCallbacks(pendingSwitcher);
        pendingSwitcher = null;
        switcher.setVisibility(visible && savedChat == null ? View.VISIBLE : View.GONE);
    }

    private void banner(String message, String action, Runnable click) {
        setNativeSwitcher(true);
        notice.removeAllViews(); notice.setVisibility(View.VISIBLE);
        TextView text = new TextView(this); text.setText(message); notice.addView(text);
        if (action != null) Views.button(this, notice, action, click);
    }

    private void showOpening() {
        if (opening != null) return;
        opening = Views.column(this);
        opening.setGravity(Gravity.CENTER);
        opening.setBackgroundColor(new ManagerStyle(this).canvas);
        openingMessage = new TextView(this);
        openingMessage.setText("正在打开「" + name + "」…");
        opening.addView(openingMessage);
        retryEntry = Views.button(this, opening, "立即重试", () -> openProbe(false));
        savedRecords = Views.button(this, opening, "查看离线副本", this::openSavedRecords);
        retryEntry.setVisibility(View.INVISIBLE);
        savedRecords.setVisibility(View.INVISIBLE);
        if (web != null) web.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        frame.addView(opening, new FrameLayout.LayoutParams(-1,-1));
        String thread=presentation.getString("thread","");
        if (conversation!=null && !Site.root(link,origin) && conversation.available(thread)) {
            savedChat=new SavedConversation(this,frame,records,conversation,id,origin,name,thread,(op,target) -> {
                if ("instances".equals(op)) showDrawer("",false);
                else if ("records".equals(op)) openRecords(target);
                else if ("retry".equals(op)) openProbe(false);
                else if ("select".equals(op)) {
                    presentation.edit().putString("thread",target).apply();
                    openProbe(false);
                }
            });
            setNativeSwitcher(false);
            opening.setVisibility(View.INVISIBLE);
        }
        final LinearLayout cover = opening;
        main.postDelayed(() -> {
            if (opening == cover) savedRecords.setVisibility(View.VISIBLE);
        }, 3500);
    }
    private void openSavedRecords() { openRecords(presentation.getString("thread","")); }
    private void revealScreen(int epoch, WebView view) {
        if (opening==null || checkingScreen || epoch!=generation || web!=view || retryNeeded || rejected) return;
        checkingScreen=true;
        String ready=firstScreen;
        if (savedChat!=null) ready="("+firstScreen+"\n"+") && (!document.querySelector('.focus-shell') || document.querySelector('.focus-shell').dataset.onlineConversation !== 'pending')";
        view.evaluateJavascript(ready, value -> {
            if (epoch!=generation || web!=view) return;
            checkingScreen=false;
            if (retryNeeded || rejected || opening==null) return;
            if (!"true".equals(value)) { main.postDelayed(() -> revealScreen(epoch,view),150); return; }
            if (savedChat!=null && savedChat.waitingForPosition(view)) { main.postDelayed(() -> revealScreen(epoch,view),100); return; }
            view.postVisualStateCallback(epoch,new WebView.VisualStateCallback() {
                @Override public void onComplete(long request) {
                    if (generation!=epoch || web!=view || opening==null || retryNeeded || rejected) return;
                    if (savedChat!=null && savedChat.waitingForPosition(view)) { revealScreen(epoch,view); return; }
                    closeSavedChat(); frame.removeView(opening); opening=null;
                    openingMessage=null; retryEntry=null; savedRecords=null;
                    view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
                    notice.setVisibility(View.GONE);
                }
            });
        });
    }
    private void networkFailure(String message) {
        if (rejected) return;
        retryNeeded = true;
        showOpening(); setNativeSwitcher(true);
        if (savedChat!=null) savedChat.networkFailure();
        notice.setVisibility(View.GONE);
        openingMessage.setText(message);
        retryEntry.setVisibility(View.VISIBLE);
        savedRecords.setVisibility(View.VISIBLE);
        main.removeCallbacks(retry);
        if (foreground) main.postDelayed(retry, Math.min(30000L, 1000L << Math.min(backoff++, 5)));
    }

    private void closeSavedChat() {
        if(savedChat!=null) {
            savedChat.close(); savedChat=null;
            if (opening!=null) opening.setVisibility(View.VISIBLE);
        }
    }
    private void checkSavedAccess() {
        if(savedChat!=null && !savedChat.hasAccess(conversation)) {
            closeSavedChat(); setNativeSwitcher(true);
        }
    }
    private void retireView() {
        if(savedChat!=null) savedChat.reconnect();
        checkingScreen=false; generation++; ticket = ""; pendingBack = null;
        if (apkUpdate != null) apkUpdate.cancel();
        if (files != null) files.cancel();
        if (web != null) { frame.removeView(web); web.stopLoading(); web.destroy(); web = null; }
    }

    private void openProbe(boolean editPassword) {
        if (!selected) return;
        awaitWebSwitcher();
        main.removeCallbacks(retry); retireView();
        retryNeeded = false; probe = true; attempted = false; rejected = false; manual = editPassword;
        supplied = null; basicIdentityChanged = false;
        notice.setVisibility(View.GONE);
        showOpening();
        if (origin.startsWith("http://")) { showPage(); return; }
        createView(false);
        web.loadUrl(origin + PROBE);
    }

    private void showPage() {
        if (!selected || !probe || rejected || retryNeeded) return;
        if (savedChat != null) savedChat.networkReachable();
        if (supplied != null) {
            if (basicIdentityChanged) lockRecords("reauthorize");
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
        WebView view = newProfileView(); web = view; frame.addView(view,0);
        if (opening != null) view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
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
                ticket = ""; recordScopeConfirmed = false; pendingBack = null; files.cancel(); apkUpdate.cancel();
                if (page && sso && Site.httpsPage(url) && !Site.sameOrigin(url, origin)) lockRecords("reauthorize");
                if (selected) awaitWebSwitcher();
                else main.post(() -> { if (!selected && epoch == generation) retireView(); });
            }
            @Override public void onPageCommitVisible(WebView v, String url) {
                if (epoch == generation && page) {
                    if (Site.root(url, origin)) offer(v);
                    revealScreen(epoch,v);
                }
            }
            @Override public void onPageFinished(WebView v, String url) {
                if (epoch != generation || retryNeeded || rejected) return;
                if (!page && url.equals(origin + PROBE) && !checkingChallenge) {
                    main.post(() -> { if (epoch == generation && !checkingChallenge) showPage(); });
                } else if (page && Site.root(url, origin)) {
                    revealScreen(epoch,v);
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
                    rejected = true; supplied = null; lockRecords();
                    banner("入口未接受凭据。", "更新凭据", () -> openProbe(true)); return;
                }
                if (!page && res.getStatusCode() == 403) {
                    rejected = true; supplied = null; lockRecords();
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
                if (op.startsWith("records-")) {
                    try {
                        if (!foreground || switching) { result.cancel(); return true; }
                        JSONObject data = new JSONObject(value);
                        String operation = op.substring(8);
                        if ("positioned".equals(operation)) {
                            if(savedChat!=null) savedChat.positioned(data.optString("position"));
                            result.confirm("ok");
                        } else if ("layout".equals(operation)) {
                            if (!recordScopeConfirmed || data.optString("scope").length()!=64 || !presentation.getString("thread","").equals(data.getString("thread"))) { result.cancel(); return true; }
                            conversation.rememberLayout(data);
                            result.confirm("ok");
                        } else if ("readwindow".equals(operation) || "putwindow".equals(operation)) {
                            if (!recordScopeConfirmed || data.optString("scope").length()!=64) { result.cancel(); return true; }
                            if ("putwindow".equals(operation)) result.confirm(conversation.enqueue(data)?"ok":"");
                            else {
                                JSONObject cached=conversation.read(data.getString("thread"),data.getString("scope"),data);
                                result.confirm(cached==null?"null":cached.toString());
                            }
                        } else if ("show".equals(operation)) {
                            result.confirm("ok"); main.post(() -> { if (epoch == generation) openRecords(data.optString("thread")); });
                        } else if ("ready".equals(operation) || "result".equals(operation)) {
                            result.confirm("ok"); if (reader != null) reader.notify(data.put("event",operation).toString());
                        } else if ("bookmark".equals(operation) && (reader != null || savedChat!=null)) {
                            result.confirm("[]");
                        } else {
                            if (data.has("thread") && !"lifecycle".equals(operation) && !"closed".equals(operation) && !"revert".equals(operation)
                                && !presentation.getString("thread","").equals(data.getString("thread"))) { result.cancel(); return true; }
                            result.confirm(records.request(false,id,origin,operation,data));
                            if ("auth".equals(operation)) recordScopeConfirmed = true;
                            if ("lock".equals(operation) || "revoke".equals(operation)) recordScopeConfirmed=false;
                            if ("auth".equals(operation) || "lock".equals(operation) || "revoke".equals(operation) || "revert".equals(operation)) checkSavedAccess();
                            if (reader != null && ("lifecycle".equals(operation) || "closed".equals(operation) || "revert".equals(operation)))
                                reader.notify(data.put("event",operation).toString());
                            if (reader != null && ("auth".equals(operation) || "lock".equals(operation) || "revoke".equals(operation)))
                                reader.notify("{\"event\":\"access\"}");
                        }
                    } catch (Exception unavailable) { result.cancel(); }
                } else if ("external".equals(op)) {
                    result.confirm(openExternal(value) ? "ok" : "error");
                } else if ("instances".equals(op)) {
                    result.confirm("ok"); main.post(() -> { if (epoch == generation) showDrawer(value, false); });
                } else if ("apk-save".equals(op)) {
                    apkUpdate.save(files, result);
                } else if (op.startsWith("apk-")) {
                    result.confirm(apkUpdate.handle(op, value));
                } else if ("chrome".equals(op)) {
                    if ("web".equals(value) && !recordScopeConfirmed) lockRecords();
                    setNativeSwitcher(!"web".equals(value));
                    result.confirm("ok");
                } else if ("thread".equals(op)) {
                    boolean saved = value != null && value.length() <= 256 && presentation.edit().putString("thread", value).commit();
                    result.confirm(saved ? "ok" : "error");
                } else if ("print".equals(op)) {
                    result.confirm(AndroidPrinting.print(ClientActivity.this, v, value));
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
            rejected = true; handler.cancel(); supplied = null; lockRecords();
            banner("入口未接受凭据。", "更新凭据", () -> openProbe(true)); return;
        }
        checkingChallenge = true;
        // Android exposes just host + realm. Verify the scheme on the exact inert
        // GET with redirects disabled before releasing anything to its handler.
        new Thread(() -> {
            boolean basic = false, unavailable = false;
            try { basic = Site.verifyBasic(origin, realm); }
            catch (Exception e) { unavailable = true; }
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
                try { saved = BasicVault.read(this, id, origin, realm); }
                catch (Exception e) { Views.message(this, "无法读取已保存的凭据"); }
                if (saved != null && !manual) { provide(handler, saved, true); return; }
                lockRecords();
                final String previousUser = saved == null ? null : saved.optString("user");
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
                        basicIdentityChanged = !user.getText().toString().equals(previousUser);
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
            + "window.__focusMobile=Object.assign(window.__focusMobile||{},{version:1,instance:'" + id + "',name:" + JSONObject.quote(name) + ",ticket:'" + ticket + "',features:['wake','resume','save','thread','tabs','drawer','navigation','records-v1','record-states','conversation-windows','conversation-layout','android-update'" + printFeature + "]});"
            + "dispatchEvent(new Event('focus-host-ready'))}}";
        view.evaluateJavascript(js, null);
    }
    private void signal(String event) {
        if (web != null && !probe && Site.root(web.getUrl(), origin))
            web.evaluateJavascript("if(window.__focusMobile)dispatchEvent(new Event('focus-host-" + event + "'))", null);
    }
    @Override protected void onResume() { super.onResume(); foreground = true; checkSavedAccess(); if (web != null) web.onResume(); signal("resume"); if (retryNeeded) main.post(retry); }
    @Override protected void onPause() { if(reader!=null) reader.cancelCheck(); foreground = false; pendingBack = null; if (drawer != null) drawer.disarmExit(); main.removeCallbacks(retry); signal("pause"); if (web != null) web.onPause(); super.onPause(); }
    @Override protected void onStop() {
        super.onStop();
        if (!selected && !isFinishing()) moveTaskToBack(true);
    }
    private void showDrawer(String theme, boolean fromRootBack) {
        if (!foreground || !selected || switching) return;
        pendingBack = null;
        try {
            JSONArray sites = new JSONArray(getSharedPreferences("instances", MODE_PRIVATE).getString("list", "[]"));
            boolean dark = "dark".equals(theme) || (theme.isEmpty() && (getResources().getConfiguration().uiMode & 48) == 32);
            drawer.show(sites, id, dark, fromRootBack, this::switchInstance, () -> switchInstance(""), this::about);
        } catch (JSONException e) { Views.message(this, "无法读取实例列表"); }
    }

    private void openRecords(String thread) {
        closeRecords();
        try {
            JSONObject site = new JSONObject().put("id",id).put("name",name).put("origin",origin);
            reader = new RecordsPanel(this,surface,records,new JSONArray().put(site),id,thread,(op,value) -> {
                if (!selected || !foreground) return;
                if ("back".equals(op)) { sendReaderAction(value); closeRecords(); }
                else if ("drawer".equals(op)) { closeRecords(); showDrawer("",false); }
                else sendReaderAction(value);
            });
        } catch (Exception unavailable) { Views.message(this,"无法读取本机离线记录"); }
    }
    private void sendReaderAction(String value) {
        if (web != null && !ticket.isEmpty() && Site.root(web.getUrl(),origin))
            web.evaluateJavascript("if(window.__focusMobile?.ticket===" + JSONObject.quote(ticket)
                + "){dispatchEvent(new CustomEvent('focus-record-action',{detail:JSON.parse(" + JSONObject.quote(value) + ")}))}",null);
    }
    private void closeRecords() {
        if (reader != null) { reader.close(); reader=null; checkSavedAccess(); }
    }
    private void lockRecords() {
        lockRecords("lock");
    }
    private void lockRecords(String operation) {
        try { records.call(operation,id,origin,new JSONObject()); } catch (Exception unavailable) { /* Optional store. */ }
        recordScopeConfirmed=false; checkSavedAccess();
        if (reader != null) reader.notify("{\"event\":\"access\"}");
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
        closeRecords(); switchTarget = target; switching = true; selected = false; apkUpdate.cancel();
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
        if (!retained) { setNativeSwitcher(false); retireView(); }
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
            String recordThread = site.optString("recordThread");
            link = intent.getStringExtra("link"); intent.removeExtra("link"); setIntent(intent);
            switching = false; boolean wasParked = !selected; selected = true;
            if (!recordThread.isEmpty()) openRecords(recordThread);
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
        else showDrawer("", true);
    }

    @Override public void onBackPressed() {
        if (!selected || switching || pendingBack != null) return;
        if (reader != null) { reader.back(); return; }
        if (drawer != null && drawer.handleBack(() -> moveTaskToBack(true))) return;
        if (savedChat!=null) { savedChat.back(() -> showDrawer("",true)); return; }
        if (web == null || probe || ticket.isEmpty() || !Site.root(web.getUrl(), origin)) { browserBack(); return; }
        Object press = new Object(); pendingBack = press;
        // 0 is a confirmed older document. An absent/stale reply must never perform a second action.
        String script = "if(!window.__focusMobile){0}else if(window.__focusMobile.ticket===" + JSONObject.quote(ticket)
            + "){typeof window.__focusBack==='function'?window.__focusBack():0}";
        web.evaluateJavascript(script, reply -> {
            if (pendingBack != press) return;
            pendingBack = null;
            if ("false".equals(reply)) showDrawer("", true);
            else if ("0".equals(reply)) browserBack();
        });
    }
    @Override protected void onActivityResult(int code, int result, Intent data) { super.onActivityResult(code,result,data); if (code == ApkUpdate.INSTALL_PERMISSION) apkUpdate.permissionResult(); else files.result(code,result,data); }
    void releaseTask() { selected = false; retireView(); finishAndRemoveTask(); }

    @Override protected void onDestroy() {
        closeSavedChat(); closeRecords(); if (records != null) records.close();
        main.removeCallbacksAndMessages(null); retireView(); if (files != null) files.dispose();
        if (pages != null) pages.finishOpening();
        PageSlots.detached(this);
        super.onDestroy();
        if (legacy) android.os.Process.killProcess(android.os.Process.myPid());
    }
}
