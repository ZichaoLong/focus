package org.focus.mobile;

import android.content.Context;
import android.util.AtomicFile;
import android.webkit.*;
import androidx.webkit.*;
import org.json.*;
import java.io.File;
import java.util.function.Consumer;

/** One-time upgrade of v1 site data using public Web storage and Cookie APIs. */
final class ProfileTransfer {
    static AtomicFile snapshot(Context ctx, String id) {
        return new AtomicFile(new File(ctx.getNoBackupFilesDir(), "profile-upgrade-" + id));
    }

    static File legacyDirectory(Context ctx, String id) {
        return new File(ctx.getApplicationInfo().dataDir, "app_webview_" + id);
    }

    static boolean namedProfiles() { return WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE); }

    // A locally supplied, empty document at the exact origin. No remote code,
    // subresources or native page bridge participate in reading or restoring storage.
    static void offline(WebView view, String origin, String expression, Consumer<String> result) {
        WebSettings settings = view.getSettings();
        settings.setAllowContentAccess(false); settings.setAllowFileAccess(false);
        settings.setBlockNetworkLoads(true); settings.setDomStorageEnabled(true); settings.setJavaScriptEnabled(true);
        view.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView page, String url) {
                if (!Site.root(url, origin)) { result.accept("null"); return; }
                page.evaluateJavascript("location.origin === " + JSONObject.quote(origin) + " ? (" + expression + ") : null", result::accept);
            }
        });
        view.loadDataWithBaseURL(origin + "/", "<!doctype html><meta charset=utf-8>", "text/html", "utf-8", null);
    }

    static void export(WebView view, Context ctx, String id, String origin, Consumer<Boolean> done) {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.GET_COOKIE_INFO)) { done.accept(false); return; }
        String entries = "Object.entries(localStorage).filter(([k])=>k.startsWith('focus-web.') || k.startsWith('kimi-web.') || k==='kimi-locale' || k.startsWith("
            + JSONObject.quote("focus-mobile." + id + ".") + "))";
        offline(view, origin, entries, json -> {
            try {
                JSONArray cookies = new JSONArray();
                for (String header : CookieManagerCompat.getCookieInfo(CookieManager.getInstance(), origin + "/"))
                    cookies.put(header.replaceAll("(?i);\\s*domain\\s*=[^;]*", ""));
                JSONObject state = new JSONObject().put("entries", new JSONArray(json)).put("cookies", cookies);
                BasicVault.seal(snapshot(ctx, id), id + "@" + origin, state);
                done.accept(true);
            } catch (Exception e) { done.accept(false); }
        });
    }

    static void restore(WebView view, Context ctx, String id, String origin, Consumer<Boolean> done) {
        try {
            JSONObject state = BasicVault.open(snapshot(ctx, id), id + "@" + origin);
            JSONArray entries = state.getJSONArray("entries");
            JSONArray cookies = state.getJSONArray("cookies");
            CookieManager jar = WebViewCompat.getProfile(view).getCookieManager();
            String data = JSONObject.quote(entries.toString());
            // Only an uncommitted target profile reaches this path. A retry may
            // follow an interrupted import or further edits in the legacy view.
            offline(view, origin, "(()=>{localStorage.clear();for (const [k,v] of JSON.parse(" + data
                + ")) localStorage.setItem(k,v);return true})()", reply -> {
                if (!"true".equals(reply)) { done.accept(false); return; }
                jar.removeAllCookies(ignored -> restoreCookies(jar, origin, cookies, done));
            });
        } catch (Exception e) { done.accept(false); }
    }
    private static void restoreCookies(CookieManager jar, String origin, JSONArray cookies, Consumer<Boolean> done) {
        if (cookies.length() == 0) { jar.flush(); done.accept(true); return; }
        int[] pending = { cookies.length() };
        boolean[] accepted = { true };
        for (int i = 0; i < cookies.length(); i++) jar.setCookie(origin + "/", cookies.optString(i), ok -> {
            accepted[0] &= ok;
            if (--pending[0] == 0) { jar.flush(); done.accept(accepted[0]); }
        });
    }

}
