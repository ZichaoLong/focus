package org.focus.mobile;

import android.app.Service;
import android.content.Intent;
import android.os.*;
import android.webkit.WebView;
import java.util.UUID;

/** Each v1 directory belongs to a different process-wide default WebView profile. */
public final class ProfileExportService extends Service {
    private WebView view;
    private ResultReceiver receiver;
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || receiver != null) { stopSelf(); return START_NOT_STICKY; }
        receiver = intent.getParcelableExtra("reply");
        try {
            String id = UUID.fromString(intent.getStringExtra("id")).toString();
            String origin = Site.entry(intent.getStringExtra("origin"));
            WebView.setDataDirectorySuffix(id);
            if (!ProfileTransfer.namedProfiles()) { finishWith(2); return START_NOT_STICKY; }
            view = new WebView(this);
            main.postDelayed(() -> complete(false), 12000);
            ProfileTransfer.export(view, this, id, origin, this::complete);
        } catch (RuntimeException e) { complete(false); }
        return START_NOT_STICKY;
    }

    private void complete(boolean ok) { finishWith(ok ? 1 : 0); }

    private void finishWith(int code) {
        if (receiver == null) return;
        ResultReceiver result = receiver; receiver = null;
        main.removeCallbacksAndMessages(null);
        if (view != null) { view.destroy(); view = null; }
        result.send(code, null);
        stopSelf();
    }

    @Override public void onDestroy() {
        super.onDestroy();
        android.os.Process.killProcess(android.os.Process.myPid());
    }
}
