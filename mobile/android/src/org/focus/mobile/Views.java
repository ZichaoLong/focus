package org.focus.mobile;

import android.app.Activity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.*;

final class Views {
    static LinearLayout column(Activity a) {
        LinearLayout l = new LinearLayout(a);
        l.setOrientation(LinearLayout.VERTICAL);
        int p = Math.round(12 * a.getResources().getDisplayMetrics().density);
        l.setPadding(p, p, p, p);
        return l;
    }

    static void install(Activity a, View content) {
        a.setContentView(content);
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            a.getWindow().setDecorFitsSystemWindows(false);
            content.setOnApplyWindowInsetsListener((v, insets) -> {
                android.graphics.Insets pads = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                v.setPadding(pads.left, pads.top, pads.right, pads.bottom);
                return WindowInsets.CONSUMED;
            });
        }
    }

    static Button button(Activity a, LinearLayout parent, String title, Runnable action) {
        Button b = new Button(a);
        b.setText(title);
        b.setAllCaps(false);
        b.setOnClickListener(v -> action.run());
        parent.addView(b);
        return b;
    }

    static EditText field(Activity a, LinearLayout parent, String hint, String value) {
        EditText field = new EditText(a);
        field.setSingleLine(true);
        field.setHint(hint);
        field.setText(value);
        parent.addView(field);
        return field;
    }

    static void message(Activity a, String message) { Toast.makeText(a, message, Toast.LENGTH_LONG).show(); }
}
