package org.focus.mobile;

import android.app.Activity;
import android.webkit.*;
import android.widget.FrameLayout;
import java.io.ByteArrayInputStream;
import org.json.*;

/** A bundled document with a fixed offline database vocabulary and no network access. */
final class RecordsPanel {
    interface Actions { void send(String op, String value); }
    private static final String PAGE = "file:///android_asset/records.html";
    private final WebView view;
    private final FrameLayout parent;
    private final Actions actions;
    private final RecordsStore store;
    private final JSONArray sites;
    private final String entry, thread;
    private final Activity activity;
    private ProfileConnection check;
    private boolean closed;
    RecordsPanel(Activity activity, FrameLayout parent, RecordsStore store, JSONArray sites,
                 String entry, String thread, Actions actions) {
        this.parent=parent; this.actions=actions; this.store=store; this.sites=sites;
        this.entry=entry; this.thread=thread; this.activity=activity;
        view=new WebView(activity); parent.addView(view,new FrameLayout.LayoutParams(-1,-1)); view.bringToFront();
        WebSettings settings=view.getSettings(); settings.setJavaScriptEnabled(true); settings.setBlockNetworkLoads(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false); settings.setDomStorageEnabled(false);
        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) { return true; }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                if ((r.isForMainFrame()?PAGE:"file:///android_asset/records.js").equals(r.getUrl().toString())) return null;
                return new WebResourceResponse("text/plain","utf-8",new ByteArrayInputStream(new byte[0]));
            }
        });
        view.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onJsPrompt(WebView v,String url,String msg,String value,JsPromptResult result) {
                if (closed || !PAGE.equals(url) || !PAGE.equals(v.getUrl()) || !msg.startsWith("records/1/")) { result.cancel(); return true; }
                try { result.confirm(command(msg.substring(10),new JSONObject(value))); }
                catch (Exception invalid) { result.cancel(); }
                return true;
            }
        });
        view.loadUrl(PAGE);
    }

    private String command(String op, JSONObject data) throws Exception {
        if ("init".equals(op)) return new JSONObject().put("sites",sites).put("entry",entry)
            .put("thread",thread).toString();
        if ("cancelcheck".equals(op)) { cancelCheck(); return "ok"; }
        if ("action".equals(op)) {
            String value=data.toString();
            view.post(() -> { if (!closed) actions.send(data.optString("op"),value); });
            return "ok";
        }
        String id=data.getString("entry");
        for (int i=0;i<sites.length();i++) {
            JSONObject site=sites.getJSONObject(i);
            if (!id.equals(site.getString("id"))) continue;
            if ("verify".equals(op)) {
                if (!view.isShown() || !activity.hasWindowFocus()) return "";
                JSONObject body=data.getJSONObject("body");
                JSONObject state=new JSONArray(store.call("status",id,site.getString("origin"),new JSONObject())).getJSONObject(0);
                if (!"0".equals(state.getString("locked")) || !state.getString("scope").equals(body.getString("scope"))
                    || !body.getString("scope").matches("[a-f0-9]{64}")) return "";
                String token=data.getString("id");
                JSONObject request=new JSONObject().put("action","record-status").put("id",token).put("body",body);
                cancelCheck();
                check=new ProfileConnection(activity, value -> {
                    check=null;
                    if (!closed) view.evaluateJavascript("window.focusRecordCheck?.("+JSONObject.quote(token)+",JSON.parse("+JSONObject.quote(value)+"))",null);
                });
                ProfileConnection pending=check;
                view.post(() -> { if (!closed && check==pending) pending.start(site,request); });
                return "ok";
            }
            return store.request(true,id,site.getString("origin"),op,data);
        }
        throw new IllegalArgumentException("未知实例");
    }
    void notify(String value) {
        view.evaluateJavascript("window.focusRecordEvent?.(JSON.parse(" + JSONObject.quote(value) + "))",null);
    }
    void back() { view.evaluateJavascript("window.focusRecordBack?.()",null); }
    void cancelCheck() { if(check!=null) { check.close(); check=null; } }
    void close() { closed=true; cancelCheck(); parent.removeView(view); view.stopLoading(); view.destroy(); }
}
