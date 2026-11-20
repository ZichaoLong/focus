package org.focus.mobile;

import android.app.Activity;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONObject;

/** An in-window list. Merely displaying it leaves the active WebView running. */
final class InstanceDrawer {
    private final Activity owner;
    private final FrameLayout parent;
    private FrameLayout overlay;
    private int foreground, muted, accent;

    InstanceDrawer(Activity owner, FrameLayout parent) { this.owner = owner; this.parent = parent; }
    private int dp(int value) { return Math.round(value * owner.getResources().getDisplayMetrics().density); }

    boolean dismiss() {
        if (overlay == null) return false;
        parent.removeView(overlay); overlay = null;
        parent.getChildAt(0).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
        return true;
    }

    void show(JSONArray sites, String active, boolean dark, Consumer<String> switchTo, Runnable manage, Runnable about) {
        dismiss();
        InputMethodManager keyboard = owner.getSystemService(InputMethodManager.class);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(parent.getWindowToken(), 0);
        foreground = dark ? 0xffe9e9e7 : 0xff242523;
        muted = dark ? 0xffb1b1aa : 0xff61645d;
        accent = dark ? 0xff343b37 : 0xffe6ece7;
        overlay = new FrameLayout(owner);
        overlay.setBackgroundColor(0x66000000);
        overlay.setOnClickListener(v -> dismiss());
        LinearLayout panel = new LinearLayout(owner);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(14), dp(20), dp(14), dp(12));
        panel.setBackgroundColor(dark ? 0xff1d1f1d : 0xfffcfcfa);
        panel.setClickable(true);
        int width = Math.min(dp(328), Math.round(parent.getWidth() * .84f));
        overlay.addView(panel, new FrameLayout.LayoutParams(width, -1, Gravity.START));
        TextView heading = label("实例", 22, foreground);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        panel.addView(heading);
        ScrollView scroll = new ScrollView(owner);
        panel.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout list = new LinearLayout(owner); list.setOrientation(LinearLayout.VERTICAL); scroll.addView(list);
        for (int i = 0; i < sites.length(); i++) {
            JSONObject site = sites.optJSONObject(i);
            if (site == null) continue;
            String id = site.optString("id");
            boolean selected = active.equals(id);
            LinearLayout row = new LinearLayout(owner);
            row.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout details = new LinearLayout(owner); details.setOrientation(LinearLayout.VERTICAL);
            details.setPadding(dp(12), dp(10), dp(6), dp(10));
            TextView title = new TextView(owner); title.setText(site.optString("name")); title.setTextSize(16); title.setTextColor(foreground);
            TextView address = new TextView(owner); address.setText(site.optString("origin")); address.setTextSize(12); address.setTextColor(muted);
            address.setSingleLine(true); address.setEllipsize(android.text.TextUtils.TruncateAt.END);
            details.addView(title); details.addView(address);
            row.addView(details, new LinearLayout.LayoutParams(0, -2, 1));
            if (selected) {
                GradientDrawable bg = new GradientDrawable();
                bg.setColor(accent); bg.setCornerRadius(dp(10)); row.setBackground(bg);
                row.addView(label("✓", 16, foreground)); row.setSelected(true);
            }
            row.setContentDescription(site.optString("name") + (selected ? "，当前实例" : "") + "\n" + site.optString("origin"));
            row.setFocusable(true);
            row.setOnClickListener(v -> { dismiss(); if (!selected) switchTo.accept(id); });
            list.addView(row);
        }
        View rule = new View(owner); rule.setBackgroundColor(accent); panel.addView(rule, new LinearLayout.LayoutParams(-1, dp(1)));
        action(panel, "管理实例", manage); action(panel, "关于 Focus Mobile", about);
        parent.getChildAt(0).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        parent.addView(overlay); overlay.setAccessibilityPaneTitle("实例");
    }

    private TextView label(String value, int size, int color) {
        TextView text = new TextView(owner); text.setText(value); text.setTextSize(size); text.setTextColor(color);
        text.setPadding(dp(12), dp(12), dp(12), dp(12)); text.setMinHeight(dp(48)); text.setGravity(Gravity.CENTER_VERTICAL);
        return text;
    }

    private void action(LinearLayout panel, String title, Runnable click) {
        TextView button = label(title, 15, muted); button.setFocusable(true);
        button.setOnClickListener(v -> { dismiss(); click.run(); }); panel.addView(button);
    }
}
