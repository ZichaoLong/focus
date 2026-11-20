package org.focus.mobile;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.*;

/** Native text, surfaces and touch targets shared by the list and its forms. */
final class ManagerStyle {
    final Activity owner;
    final boolean dark;
    final int canvas, card, ink, muted, accent, tint, line;

    ManagerStyle(Activity owner) {
        this.owner = owner;
        dark = (owner.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        canvas = dark ? 0xff171b19 : 0xfff5f7f4; card = dark ? 0xff222723 : 0xffffffff;
        ink = dark ? 0xffedf2ed : 0xff1b2a22; muted = dark ? 0xffb4c0b7 : 0xff54645a;
        accent = dark ? 0xffa0d1b6 : 0xff285b42; tint = dark ? 0xff2a4032 : 0xffe6f1e9;
        line = dark ? 0xff364239 : 0xffd9e2da;
    }
    int dp(int n) { return Math.round(n * owner.getResources().getDisplayMetrics().density); }
    void pad(View view, int horizontal, int vertical) {
        view.setPadding(dp(horizontal), dp(vertical), dp(horizontal), dp(vertical));
    }
    TextView text(String value, int size, int color, boolean bold) {
        TextView t = new TextView(owner); t.setText(value); t.setTextSize(size); t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return t;
    }
    GradientDrawable surface(int color, boolean border) {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color); bg.setCornerRadius(dp(14));
        if (border) bg.setStroke(dp(1), line);
        return bg;
    }
    void clickable(View view, int color, Runnable action) {
        view.setBackground(new RippleDrawable(ColorStateList.valueOf(dark ? 0x28ffffff : 0x18000000), surface(color, false), null));
        view.setFocusable(true); view.setOnClickListener(v -> action.run());
    }
    Button button(String value, boolean primary, Runnable action) {
        Button button = new Button(owner);
        button.setText(value); button.setAllCaps(false); button.setTextSize(15);
        button.setMinWidth(0); button.setMinimumWidth(0); button.setMinHeight(dp(48));
        button.setStateListAnimator(null); button.setGravity(Gravity.CENTER);
        button.setTextColor(primary ? canvas : accent);
        clickable(button, primary ? accent : card, action); pad(button, 14, 0);
        return button;
    }
    void gap(LinearLayout list, int height) { list.addView(new View(owner), 1, dp(height)); }
}
