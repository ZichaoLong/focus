package org.focus.mobile;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.IntentSender;
import android.os.Bundle;

/** Observe the same Android handoff for both the Web preview and the native control. */
abstract class PrintHostActivity extends Activity {
    final AndroidPrinting printing = new AndroidPrinting(this);

    @Override public void startIntentSender(IntentSender sender, Intent fillIn, int mask, int values, int extra, Bundle options)
            throws IntentSender.SendIntentException {
        printing.intentEvent("intent-start");
        try { super.startIntentSender(sender, fillIn, mask, values, extra, options); }
        catch (IntentSender.SendIntentException | RuntimeException failure) {
            if (failure instanceof ActivityNotFoundException) printing.intentEvent("intent-no-activity");
            else if (failure instanceof SecurityException) printing.intentEvent("intent-denied");
            else if (failure instanceof IntentSender.SendIntentException) printing.intentEvent("intent-send-error");
            else printing.intentEvent("intent-error");
            throw failure;
        }
        printing.intentEvent("intent-returned");
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        printing.hostEvent(focused ? "window-focused" : "window-unfocused");
    }

    @Override protected void onResume() { super.onResume(); printing.hostEvent("activity-resumed"); }
    @Override protected void onPause() { printing.hostEvent("activity-paused"); super.onPause(); }
    @Override protected void onDestroy() { printing.clear(); super.onDestroy(); }
}
