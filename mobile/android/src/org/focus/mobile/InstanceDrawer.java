package org.focus.mobile;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.VelocityTracker;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONObject;

/** An in-window list. Merely displaying it leaves the active WebView running. */
final class InstanceDrawer {
    private final Activity owner;
    private final FrameLayout parent;
    private DrawerOverlay overlay;
    private long exitDeadline;
    private int foreground, muted, accent;

    InstanceDrawer(Activity owner, FrameLayout parent) { this.owner = owner; this.parent = parent; }
    private int dp(int value) { return Math.round(value * owner.getResources().getDisplayMetrics().density); }

    void disarmExit() { exitDeadline = 0; }

    boolean handleBack(Runnable background) {
        if (overlay == null) return false;
        boolean exit = SystemClock.elapsedRealtime() < exitDeadline;
        dismiss();
        if (exit) background.run();
        return true;
    }

    private void dismiss() {
        disarmExit();
        if (overlay == null) return;
        parent.removeView(overlay); overlay = null;
        parent.getChildAt(0).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
    }

    void show(JSONArray sites, String active, boolean dark, boolean fromRootBack, Consumer<String> switchTo, Runnable manage, Runnable about) {
        dismiss();
        InputMethodManager keyboard = owner.getSystemService(InputMethodManager.class);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(parent.getWindowToken(), 0);
        foreground = dark ? 0xffe9e9e7 : 0xff242523;
        muted = dark ? 0xffb1b1aa : 0xff61645d;
        accent = dark ? 0xff343b37 : 0xffe6ece7;
        overlay = new DrawerOverlay();
        LinearLayout panel = overlay.panel;
        panel.setPadding(dp(14), dp(20), dp(14), dp(12));
        panel.setBackgroundColor(dark ? 0xff1d1f1d : 0xfffcfcfa);
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
        if (fromRootBack) exitDeadline = SystemClock.elapsedRealtime() + 2000;
    }

    /** Track the pointer in the stationary overlay while the panel moves underneath it. */
    private final class DrawerOverlay extends FrameLayout {
        private static final float SCRIM_ALPHA = 0.4f;
        private final View scrim = new View(owner);
        final LinearLayout panel = new LinearLayout(owner);
        private final int slop = ViewConfiguration.get(owner).getScaledTouchSlop();
        private final int flingSpeed = dp(600);
        private VelocityTracker velocity;
        private float downX, downY, startTranslation;
        private int edgeSign;
        private boolean canDrag, dragging, closing;

        DrawerOverlay() {
            super(owner);
            scrim.setBackgroundColor(Color.BLACK);
            scrim.setAlpha(SCRIM_ALPHA);
            addView(scrim, new LayoutParams(-1, -1));
            setOnClickListener(v -> dismiss());
            panel.setOrientation(LinearLayout.VERTICAL);
            panel.setClickable(true);
            int width = Math.min(dp(328), Math.round(parent.getWidth() * .84f));
            addView(panel, new LayoutParams(width, -1, Gravity.START));
        }

        @Override protected void onAttachedToWindow() {
            super.onAttachedToWindow();
            velocity = VelocityTracker.obtain();
        }

        @Override public boolean onInterceptTouchEvent(MotionEvent event) {
            if (closing) return true;
            float x = event.getX(), y = event.getY();
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    downX = x; downY = y;
                    edgeSign = getLayoutDirection() == View.LAYOUT_DIRECTION_RTL ? 1 : -1;
                    canDrag = x >= panel.getX() && x < panel.getX() + panel.getWidth();
                    dragging = false;
                    velocity.clear();
                    velocity.addMovement(event);
                    break;
                case MotionEvent.ACTION_MOVE:
                    if (!canDrag) break;
                    velocity.addMovement(event);
                    float outward = edgeSign * (x - downX), vertical = Math.abs(y - downY);
                    if (outward > slop && outward > 1.5f * vertical) {
                        dragging = true;
                        panel.animate().cancel();
                        scrim.animate().cancel();
                        startTranslation = panel.getTranslationX();
                        slideTo(x);
                        return true; // The framework cancels the pressed row or scrolling child.
                    }
                    if (vertical > slop || outward < -slop) canDrag = false;
                    break;
                case MotionEvent.ACTION_POINTER_DOWN:
                    canDrag = false;
                    break;
            }
            return false;
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            if (closing) return true;
            if (!dragging) return super.onTouchEvent(event);
            velocity.addMovement(event);
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_POINTER_DOWN:
                    canDrag = false;
                    break;
                case MotionEvent.ACTION_MOVE:
                    if (canDrag) slideTo(event.getX());
                    break;
                case MotionEvent.ACTION_UP:
                    if (canDrag) slideTo(event.getX());
                    velocity.computeCurrentVelocity(1000);
                    float speed = edgeSign * velocity.getXVelocity();
                    float distance = edgeSign * panel.getTranslationX();
                    boolean farEnough = distance >= panel.getWidth() / 3f;
                    boolean flungOutward = speed >= flingSpeed && distance >= 2 * slop;
                    settle(canDrag && (flungOutward || (farEnough && speed > -flingSpeed)));
                    break;
                case MotionEvent.ACTION_CANCEL:
                    settle(false);
                    break;
            }
            return true;
        }

        private void slideTo(float x) {
            int width = panel.getWidth();
            float distance = Math.max(0, Math.min(width, edgeSign * (startTranslation + x - downX)));
            panel.setTranslationX(edgeSign * distance);
            scrim.setAlpha(SCRIM_ALPHA * (1 - distance / width));
        }

        private void settle(boolean close) {
            dragging = false;
            closing = close;
            if (close) disarmExit();
            scrim.animate().alpha(close ? 0 : SCRIM_ALPHA).setDuration(160).start();
            panel.animate().translationX(close ? edgeSign * panel.getWidth() : 0).setDuration(160)
                .withEndAction(close ? () -> { if (overlay == this) dismiss(); } : null).start();
        }

        @Override protected void onDetachedFromWindow() {
            scrim.animate().cancel();
            panel.animate().cancel();
            velocity.recycle();
            dragging = closing = false;
            panel.setTranslationX(0);
            scrim.setAlpha(SCRIM_ALPHA);
            super.onDetachedFromWindow();
        }
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
