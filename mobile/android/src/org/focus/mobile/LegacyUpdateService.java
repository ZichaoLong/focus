package org.focus.mobile;

import android.app.Service;
import android.content.Intent;
import android.os.*;
import android.webkit.WebView;
import java.util.UUID;
import org.json.*;

/** Older engines have one profile per process and require the entry's original suffix. */
public final class LegacyUpdateService extends Service {
    private UpdateConnection connection;
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) { stopSelf(); return START_NOT_STICKY; }
        ResultReceiver receiver = intent.getParcelableExtra("reply");
        try {
            JSONObject site = new JSONObject(intent.getStringExtra("site"));
            WebView.setDataDirectorySuffix(UUID.fromString(site.getString("id")).toString());
            connection = new UpdateConnection(this, site, new JSONObject(intent.getStringExtra("call")),
                false, data -> finish(receiver,data));
            connection.start();
        } catch (Exception e) { finish(receiver,UpdateConnection.error("暂时无法使用旧实例的网页配置")); }
        return START_NOT_STICKY;
    }
    private void finish(ResultReceiver receiver, String data) {
        Bundle result = new Bundle(); result.putString("result",data);
        receiver.send(1,result); stopSelf();
    }
    @Override public void onDestroy() {
        if (connection != null) connection.close();
        super.onDestroy(); android.os.Process.killProcess(android.os.Process.myPid());
    }
}
