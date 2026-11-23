package org.focus.mobile;

import android.app.Activity;
import android.app.ActivityManager;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ResultReceiver;
import android.os.SystemClock;
import java.util.UUID;
import java.util.function.Consumer;
import org.json.JSONObject;

/** Runs one site-management request in the entry's existing WebView profile. */
final class ProfileConnection {
    private final Activity owner;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Consumer<String> done;
    private UpdateConnection connection;
    private Intent legacy;
    private boolean closed;

    ProfileConnection(Activity owner, Consumer<String> done) {
        this.owner = owner;
        this.done = done;
    }
    void start(JSONObject entry, JSONObject call) {
        try {
            if (owner instanceof LegacyClientActivity) {
                connection = new UpdateConnection(owner, entry, call, false, this::finish);
                connection.start();
                return;
            }
            String key = UUID.fromString(entry.getString("id")).toString();
            boolean named = owner.getSharedPreferences("instances", Context.MODE_PRIVATE).getBoolean("named-" + key,false);
            if (!ProfileTransfer.namedProfiles() || (!named && ProfileTransfer.legacyDirectory(owner,key).isDirectory())) {
                if (named) { finish(UpdateConnection.error("请更新系统 WebView 以使用此实例的网页配置")); return; }
                startLegacyAfterExit(entry, call, SystemClock.elapsedRealtime() + 8000);
                return;
            }
            connection = new UpdateConnection(owner, entry, call, true, this::finish);
            connection.start();
        } catch (Exception e) { finish(UpdateConnection.error("无法打开实例的网页配置")); }
    }

    private void startLegacyAfterExit(JSONObject entry, JSONObject call, long deadline) {
        if (closed) return;
        ActivityManager manager = owner.getSystemService(ActivityManager.class);
        for (ActivityManager.RunningAppProcessInfo p : manager.getRunningAppProcesses()) {
            if (p.uid == android.os.Process.myUid() && (p.processName.equals(owner.getPackageName()+":legacy") ||
                p.processName.equals(owner.getPackageName()+":updateLegacy"))) {
                if (SystemClock.elapsedRealtime() >= deadline) finish(UpdateConnection.error("旧网页配置仍在释放，请重试"));
                else main.postDelayed(() -> startLegacyAfterExit(entry,call,deadline),100);
                return;
            }
        }
        ResultReceiver receiver = new ResultReceiver(main) {
            @Override protected void onReceiveResult(int code, Bundle data) {
                finish(data.getString("result",UpdateConnection.error("无法连接入口")));
            }
        };
        legacy = new Intent(owner,LegacyUpdateService.class).putExtra("site",entry.toString())
            .putExtra("call",call.toString()).putExtra("reply",receiver);
        owner.startService(legacy);
        main.postDelayed(() -> { if (!closed) finish(UpdateConnection.error("暂时无法读取实例状态")); },80000);
    }

    private void finish(String result) {
        if (closed) return;
        close();
        done.accept(result);
    }
    void close() {
        closed = true;
        main.removeCallbacksAndMessages(null);
        if (connection != null) { connection.close(); connection = null; }
        if (legacy != null) { owner.stopService(legacy); legacy = null; }
    }
}
