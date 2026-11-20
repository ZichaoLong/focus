package org.focus.mobile;

import android.app.Activity;
import android.content.*;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.webkit.*;
import android.widget.*;

/** A guest WebView above the caller's task, including on engines without named profiles. */
public final class ExternalPageActivity extends Activity {
    private static boolean initialized;
    private WebView page;
    private TextView site;
    private String address;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        address = state == null ? getIntent().getDataString() : state.getString("address");
        if (!Site.httpsPage(address)) { finish(); return; }
        // This process never loads an instance profile, HTTP auth cache, or Focus bridge.
        if (!initialized) { WebView.setDataDirectorySuffix("external-links"); initialized = true; }
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        LinearLayout bar = new LinearLayout(this); bar.setGravity(Gravity.CENTER_VERTICAL);
        Button close = Views.button(this, bar, "‹", this::finish);
        close.setContentDescription("回到 Focus"); close.setMinWidth(0); close.setMinimumWidth(0);
        site = new TextView(this); site.setSingleLine(true);
        site.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);
        site.setOnClickListener(v -> new android.app.AlertDialog.Builder(this).setMessage(Site.origin(address))
            .setPositiveButton(android.R.string.ok, null).show());
        bar.addView(site, new LinearLayout.LayoutParams(0, -2, 1));
        Views.button(this, bar, "用浏览器打开", () -> {
            String current = page.getUrl();
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(Site.httpsPage(current) ? current : address))); }
            catch (ActivityNotFoundException missing) { Views.message(this, "未找到浏览器"); }
        });
        panel.addView(bar);
        page = new WebView(this);
        WebSettings settings = page.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptThirdPartyCookies(page, false);
        page.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest request) {
                return request.isForMainFrame() && !Site.httpsPage(request.getUrl().toString());
            }
            @Override public void onPageStarted(WebView v, String url, Bitmap icon) { showAddress(url); }
            @Override public void doUpdateVisitedHistory(WebView v, String url, boolean reload) { showAddress(url); }
            @Override public void onReceivedHttpAuthRequest(WebView v, HttpAuthHandler handler, String host, String realm) {
                handler.cancel();
            }
            @Override public boolean onRenderProcessGone(WebView v, RenderProcessGoneDetail detail) {
                finish(); return true;
            }
        });
        panel.addView(page, new LinearLayout.LayoutParams(-1, 0, 1));
        Views.install(this, panel); Views.systemBars(this, false, 0xfffafafa);
        showAddress(address); page.loadUrl(address);
    }

    private void showAddress(String url) {
        if (Site.httpsPage(url)) { address = url; site.setText(Site.origin(url)); }
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state); state.putString("address", address);
    }
    @Override protected void onDestroy() {
        if (page != null) { ((LinearLayout)page.getParent()).removeView(page); page.destroy(); }
        super.onDestroy();
    }
}
