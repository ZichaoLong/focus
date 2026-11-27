package org.focus.mobile;

import android.app.Activity;
import android.os.UserManager;
import android.print.PrintManager;
import android.webkit.WebView;

/** Submit this preview to Android. Only the system knows the user's final action. */
final class AndroidPrinting {
    static String print(Activity activity, WebView view, String name) {
        try {
            UserManager users = activity.getSystemService(UserManager.class);
            if (users != null && users.hasUserRestriction(UserManager.DISALLOW_PRINTING)) return "restricted";
            PrintManager manager = activity.getSystemService(PrintManager.class);
            if (manager == null) return "unavailable";
            String title = name == null || name.trim().isEmpty() ? "Focus" : name;
            return manager.print(title, view.createPrintDocumentAdapter(title), null) == null ? "error" : "ok";
        } catch (SecurityException denied) {
            return "restricted";
        } catch (RuntimeException failure) {
            return "error";
        }
    }
}
