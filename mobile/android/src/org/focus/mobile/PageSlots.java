package org.focus.mobile;

import android.app.*;
import android.content.*;
import android.os.*;
import androidx.webkit.ProfileStore;
import org.json.*;
import java.util.*;

/** Recently selected isolated pages share one WebView host process. */
final class PageSlots {
    private final Activity owner;
    private final SharedPreferences prefs;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ActivityManager tasks;
    private static final Set<String> exportFailed = new HashSet<>();
    private static final Map<Class<?>, ClientActivity> live = new HashMap<>();
    private boolean opening;
    private AlertDialog transferNotice;
    private static boolean legacyOnly;

    PageSlots(Activity owner, SharedPreferences prefs) {
        this.owner = owner; this.prefs = prefs;
        tasks = owner.getSystemService(ActivityManager.class);
        retryDeletedProfiles();
    }

    // A rejected local import must leave the original directory usable, even
    // if a cookie policy or the storage quota prevents moving it on this engine.
    static void continueInLegacy(ClientActivity page, String id, String site, String link) {
        exportFailed.add(id);
        ProfileTransfer.snapshot(page, id).delete();
        for (ClientActivity tab : new ArrayList<>(live.values())) tab.releaseTask();
        page.startActivity(new Intent(page, LegacyClientActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("site", site).putExtra("link", link));
    }

    static void attached(ClientActivity page) { live.put(page.getClass(), page); }
    static void detached(ClientActivity page) { live.remove(page.getClass(), page); }
    private static final Class<?>[] ACTIVITIES = { ClientActivity.class, SecondClientActivity.class,
        ClientActivity.Third.class, ClientActivity.Fourth.class, ClientActivity.Fifth.class };
    int limit() { return Math.max(1, Math.min(ACTIVITIES.length, prefs.getInt("page-limit", 2))); }

    private List<Integer> occupied() {
        List<Integer> slots = new ArrayList<>();
        for (int i = 0; i < ACTIVITIES.length; i++) if (!instance(i).isEmpty()) slots.add(i);
        slots.sort(Comparator.comparingLong(this::lastUse));
        return slots;
    }

    private long lastUse(int slot) {
        // Version 1.2 kept the most recent of its two task slots.
        return prefs.getLong("use-" + slot, slot == prefs.getInt("latest-slot", 1) ? 1L : 0L);
    }

    void setLimit(int count) {
        if (count < 1 || count > ACTIVITIES.length) return;
        prefs.edit().putInt("page-limit", count).apply();
        List<Integer> slots = occupied();
        for (int i = 0; i < slots.size() - count; i++) retire(slots.get(i));
    }

    private int claim(String id) {
        List<Integer> slots = occupied();
        long order = slots.isEmpty() ? 1 : lastUse(slots.get(slots.size() - 1)) + 1;
        int slot = 0;
        while (slot < ACTIVITIES.length && !id.equals(instance(slot))) slot++;
        if (slot == ACTIVITIES.length) {
            if (slots.size() >= limit()) retire(slots.get(0));
            slot = 0;
            while (!instance(slot).isEmpty()) slot++;
        }
        prefs.edit().putString("slot-" + slot, id).putLong("use-" + slot, order).commit();
        return slot;
    }
    private String instance(int slot) { return prefs.getString("slot-" + slot, ""); }

    private void retire(int slot) {
        Class<?> type = ACTIVITIES[slot];
        ClientActivity page = live.get(type);
        if (page != null) page.releaseTask();
        else for (ActivityManager.AppTask task : tasks.getAppTasks()) {
            if (new ComponentName(owner, type).equals(task.getTaskInfo().baseIntent.getComponent())) task.finishAndRemoveTask();
        }
        prefs.edit().remove("slot-" + slot).remove("use-" + slot).commit();
    }

    boolean openNamedTarget(String id, JSONArray sites) {
        if (id.isEmpty() || legacyOnly || !ProfileTransfer.namedProfiles()) return false;
        for (int i = 0; i < sites.length(); i++) {
            JSONObject site = sites.optJSONObject(i);
            if (id.equals(site.optString("id")) && !needsLegacy(site)) {
                open(site, "", false, sites);
                return true;
            }
        }
        return false;
    }

    void open(JSONObject site, String link, boolean reload, JSONArray sites) {
        if (opening) return;
        if (!reload && link.isEmpty() && site.optString("id").equals(prefs.getString("active", ""))) {
            ComponentName legacy = new ComponentName(owner, LegacyClientActivity.class);
            for (ActivityManager.AppTask task : tasks.getAppTasks()) {
                ActivityManager.RecentTaskInfo info = task.getTaskInfo();
                if (info.numActivities > 0 && legacy.equals(info.baseIntent.getComponent())) { task.moveToFront(); return; }
            }
        }
        opening = true;
        afterLegacyExit(() -> prepare(site, link, reload, sites));
    }

    private void prepare(JSONObject site, String link, boolean reload, JSONArray sites) {
        String id = site.optString("id");
        // Export installed v1 sites before the first warm tab needs the renderer.
        // Both large drafts and cookie attributes travel via an app-private sealed file.
        if (!legacyOnly) for (int i = 0; i < sites.length(); i++) {
            JSONObject old = sites.optJSONObject(i);
            String key = old.optString("id");
            if (!needsLegacy(old) || old.optBoolean("sso") || exportFailed.contains(key)
                || ProfileTransfer.snapshot(owner, key).getBaseFile().exists()) continue;
            if (!live.isEmpty()) for (int slot : occupied()) retire(slot);
            if (transferNotice == null) transferNotice = new AlertDialog.Builder(owner)
                .setMessage("正在恢复原有实例的网页数据…").setCancelable(false).show();
            ResultReceiver reply = new ResultReceiver(main) {
                boolean finished;
                @Override protected void onReceiveResult(int code, Bundle data) {
                    if (finished) return;
                    finished = true;
                    if (code == 2) legacyOnly = true;
                    else if (code != 1) exportFailed.add(key);
                    if (!owner.isDestroyed()) afterLegacyExit(() -> prepare(site, link, reload, sites));
                }
            };
            try {
                if (owner.startService(new Intent(owner, ProfileExportService.class).putExtra("id", key)
                    .putExtra("origin", old.optString("origin")).putExtra("reply", reply)) != null) {
                    main.postDelayed(() -> reply.send(0, null), 16000);
                    return;
                }
            } catch (IllegalStateException background) { finishOpening(); return; }
            exportFailed.add(key);
        }
        boolean legacy = needsLegacy(site) && (site.optBoolean("sso") || exportFailed.contains(id));
        boolean supported = !legacyOnly && (legacy || ProfileTransfer.namedProfiles());
        legacy |= !supported;
        finishOpening();
        if (!supported && prefs.getBoolean("named-" + id, false)) {
            Views.message(owner, "此实例使用独立网页配置。请更新或重新启用支持多配置的系统 WebView。");
            return;
        }
        Intent intent = new Intent().addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("site", site.toString()).putExtra("link", link).putExtra("reload", reload);
        if (legacy) {
            ProfileTransfer.snapshot(owner, id).delete();
            for (int slot : occupied()) retire(slot);
            intent.setClass(owner, LegacyClientActivity.class);
        } else {
            intent.setClass(owner, ACTIVITIES[claim(id)]);
        }
        prefs.edit().putString("active", id).commit();
        owner.startActivity(intent);
    }

    void finishOpening() {
        opening = false;
        if (transferNotice != null) { transferNotice.dismiss(); transferNotice = null; }
    }

    private boolean needsLegacy(JSONObject site) {
        String id = site.optString("id");
        return !prefs.getBoolean("named-" + id, false) && ProfileTransfer.legacyDirectory(owner, id).isDirectory();
    }

    // Android's renderer service cannot be shared by two host processes. The
    // short-lived legacy host closes itself before a different directory opens.
    private void afterLegacyExit(Runnable ready) {
        new Runnable() {
            int checks;
            public void run() {
                if (owner.isDestroyed()) return;
                List<ActivityManager.RunningAppProcessInfo> processes = tasks.getRunningAppProcesses();
                if (processes != null) for (ActivityManager.RunningAppProcessInfo p : processes) {
                    if (p.uid == android.os.Process.myUid() && (owner.getPackageName() + ":legacy").equals(p.processName)) {
                        if (++checks < 120) main.postDelayed(this, 50);
                        else { finishOpening(); Views.message(owner, "旧页面仍在释放，请重试"); }
                        return;
                    }
                }
                ready.run();
            }
        }.run();
    }

    void forget(String id) {
        for (int slot = 0; slot < ACTIVITIES.length; slot++) if (id.equals(instance(slot))) retire(slot);
        ProfileTransfer.snapshot(owner, id).delete();
        Set<String> pending = new HashSet<>(prefs.getStringSet("delete-profiles", Collections.emptySet()));
        pending.add(id);
        prefs.edit().putStringSet("delete-profiles", pending).remove("named-" + id).commit();
        retryDeletedProfiles();
    }

    private void retryDeletedProfiles() {
        Set<String> pending = new HashSet<>(prefs.getStringSet("delete-profiles", Collections.emptySet()));
        if (pending.isEmpty() || !ProfileTransfer.namedProfiles()) return;
        pending.removeIf(id -> {
            try { ProfileStore.getInstance().deleteProfile(id); return true; }
            catch (IllegalStateException loaded) { return false; } // Retry before loading it on the next process start.
        });
        prefs.edit().putStringSet("delete-profiles", pending).commit();
    }
}
