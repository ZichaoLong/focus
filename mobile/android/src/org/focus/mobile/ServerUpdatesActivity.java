package org.focus.mobile;

import android.app.Activity;
import android.content.*;
import android.os.*;
import android.webkit.*;
import android.widget.FrameLayout;
import java.io.ByteArrayInputStream;
import org.json.*;

/** The bundled manager is the only document with access to the local entry list. */
public final class ServerUpdatesActivity extends Activity {
    private static final String PAGE = "file:///android_asset/server-updates.html";
    private static final String SCRIPT = "file:///android_asset/server-updates.js";
    private final Handler main = new Handler(Looper.getMainLooper());
    private JSONArray sites;
    private SharedPreferences state;
    private WebView panel;
    private ProfileConnection connection;
    private String pending = "";
    private boolean foreground;

    @Override public void onCreate(Bundle bundle) {
        super.onCreate(bundle);
        try { sites = new JSONArray(getSharedPreferences("instances", MODE_PRIVATE).getString("list","[]")); }
        catch (JSONException invalid) { finish(); return; }
        state = getSharedPreferences("server-updates", MODE_PRIVATE);
        ManagerStyle ui = new ManagerStyle(this);
        FrameLayout frame = new FrameLayout(this);
        panel = new WebView(this); frame.addView(panel);
        Views.install(this,frame); Views.systemBars(this,ui.dark,ui.canvas);
        WebSettings settings = panel.getSettings();
        settings.setJavaScriptEnabled(true); settings.setBlockNetworkLoads(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        panel.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) { return true; }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
                String url = req.getUrl().toString();
                if (url.equals(req.isForMainFrame() ? PAGE : SCRIPT)) return null;
                return new WebResourceResponse("text/plain","utf-8",new ByteArrayInputStream(new byte[0]));
            }
        });
        panel.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onJsPrompt(WebView v, String url, String message, String value, JsPromptResult result) {
                if (!PAGE.equals(url) || !PAGE.equals(v.getUrl()) || !foreground) { result.cancel(); return true; }
                try { result.confirm(command(message,value)); }
                catch (Exception invalid) { result.cancel(); }
                return true;
            }
        });
        panel.loadUrl(PAGE);
    }

    private JSONObject site(String id) {
        for (int i=0; i<sites.length(); i++)
            if (id.equals(sites.optJSONObject(i).optString("id"))) return sites.optJSONObject(i);
        throw new IllegalArgumentException("Unknown instance");
    }

    private String command(String command, String value) throws Exception {
        if ("focus-updates/init".equals(command)) {
            JSONObject records = new JSONObject();
            for (int i=0; i<sites.length(); i++) {
                String id = sites.getJSONObject(i).getString("id");
                if (state.contains(id)) records.put(id,new JSONObject(state.getString(id,"{}")));
            }
            return new JSONObject().put("sites",sites).put("records",records)
                .put("channel",state.getString("channel","installed")).toString();
        }
        if ("focus-updates/save".equals(command)) {
            JSONObject data = new JSONObject(value), records = data.getJSONObject("records");
            SharedPreferences.Editor edit = state.edit().putString("channel",data.getString("channel"));
            for (int i=0; i<sites.length(); i++) {
                String id = sites.getJSONObject(i).getString("id");
                if (records.has(id)) edit.putString(id,records.getJSONObject(id).toString()); else edit.remove(id);
            }
            return edit.commit() ? "ok" : "";
        }
        if ("focus-updates/open".equals(command)) {
            site(value); setResult(RESULT_OK,new Intent().putExtra("site",value)); main.post(this::finish); return "ok";
        }
        if ("focus-updates/back".equals(command)) { main.post(this::finish); return "ok"; }
        if (!"focus-updates/request".equals(command) || !pending.isEmpty()) return "";
        JSONObject call = new JSONObject(value), entry = site(call.getString("site"));
        String id = call.getString("id"), action = call.getString("action");
        call.getJSONObject("body");
        if (!id.matches("[a-f0-9]{32}") || !(action.equals("status") || action.equals("prepare") || action.equals("apply"))) return "";
        pending = id;
        main.post(() -> {
            if (pending.equals(id) && foreground) {
                connection=new ProfileConnection(this, result -> reply(id,result)); connection.start(entry,call);
            }
        });
        return "ok";
    }

    private void reply(String id, String value) {
        if (!id.equals(pending) || !foreground) return;
        pending = ""; main.removeCallbacksAndMessages(null); connection = null;
        panel.evaluateJavascript("window.focusBatchResult?.(" + JSONObject.quote(id) +
            ",JSON.parse(" + JSONObject.quote(value) + "))",null);
    }
    @Override protected void onResume() {
        super.onResume(); foreground = true;
        if (panel != null) panel.evaluateJavascript("window.focusBatchActive?.(true)",null);
    }
    @Override protected void onPause() {
        foreground = false; pending = ""; main.removeCallbacksAndMessages(null);
        if (connection != null) { connection.close(); connection = null; }
        if (panel != null) panel.evaluateJavascript("window.focusBatchActive?.(false)",null);
        super.onPause();
    }
    @Override protected void onDestroy() {
        if (panel != null) { ((FrameLayout)panel.getParent()).removeView(panel); panel.destroy(); }
        super.onDestroy();
    }
}
