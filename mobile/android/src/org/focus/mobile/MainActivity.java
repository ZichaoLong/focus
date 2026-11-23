package org.focus.mobile;

import android.app.*;
import android.content.*;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.*;
import org.json.*;
import java.util.UUID;
import java.io.File;

public final class MainActivity extends Activity {
    static final String PICK = "org.focus.mobile.PICK";
    private JSONArray sites;
    private SharedPreferences prefs;
    private PageSlots pages;
    private String returnInstance = "";
    private ManagerStyle ui;

    @Override public void onCreate(Bundle state) {
        ui = new ManagerStyle(this);
        if (ui.dark) setTheme(android.R.style.Theme_Material_NoActionBar);
        super.onCreate(state);
        prefs = getSharedPreferences("instances", MODE_PRIVATE);
        if (state != null) returnInstance = state.getString("return-instance", "");
        pages = new PageSlots(this, prefs);
        try { sites = new JSONArray(prefs.getString("list", "[]")); }
        catch (JSONException e) { throw new IllegalStateException(e); }
        render();
    }

    @Override protected void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); }

    @Override protected void onResume() {
        super.onResume();
        if (PICK.equals(getIntent().getAction())) {
            prefs.edit().remove("active").commit();
            returnInstance = getIntent().getStringExtra("return-instance");
            String target = getIntent().getStringExtra("target");
            String record = getIntent().getStringExtra("recordThread");
            setIntent(new Intent());
            render();
            for (int i = 0; i < sites.length(); i++) {
                JSONObject site = sites.optJSONObject(i);
                if (site.optString("id").equals(target)) {
                    if (record != null) try { site = new JSONObject(site.toString()).put("recordThread",record); }
                    catch (JSONException invalid) { return; }
                    open(site, ""); break;
                }
            }
        } else for (int i = 0; i < sites.length(); i++) {
            JSONObject site = sites.optJSONObject(i);
            if (site.optString("id").equals(prefs.getString("active", ""))) { open(site, ""); break; }
        }
    }

    @Override protected void onDestroy() { pages.finishOpening(); super.onDestroy(); }

    @Override protected void onStop() {
        super.onStop();
        // The launcher and parked instance tasks must stay behind the user's previous app.
        if (!prefs.getString("active", "").isEmpty() && !isFinishing()) moveTaskToBack(true);
    }

    private JSONObject returnSite() {
        for (int i = 0; i < sites.length(); i++) {
            JSONObject site = sites.optJSONObject(i);
            if (site.optString("id").equals(returnInstance)) return site;
        }
        return null;
    }

    @Override public void onBackPressed() {
        JSONObject site = returnSite();
        if (site != null) open(site, ""); else moveTaskToBack(true);
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putString("return-instance", returnInstance);
    }

    private void render() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = Views.column(this);
        ui.pad(list, 20, 20); scroll.setBackgroundColor(ui.canvas);
        scroll.addView(list);
        Views.install(this, scroll);
        Views.systemBars(this, ui.dark, ui.canvas);
        if (returnSite() != null) {
            list.addView(ui.button("返回对话", false, this::onBackPressed), -2, -2); ui.gap(list, 16);
        }
        LinearLayout header = new LinearLayout(this); header.setGravity(Gravity.CENTER_VERTICAL);
        header.addView(ui.text("管理实例", 26, ui.ink, true), new LinearLayout.LayoutParams(0, -2, 1));
        header.addView(ui.button("添加实例", true, () -> edit(-1))); list.addView(header);
        ui.gap(list, 16);
        if (sites.length() > 0) {
            list.addView(ui.button("本机离线记录", false, () -> startActivityForResult(new Intent(this, RecordsActivity.class).putExtra("active",returnInstance),25)));
            ui.gap(list, 8);
            list.addView(ui.button("服务端更新", false, () -> startActivityForResult(new Intent(this, ServerUpdatesActivity.class), 24)));
            ui.gap(list, 12);
        }
        if (sites.length() == 0) list.addView(ui.text("添加 Focus 的访问地址以开始使用。", 15, ui.muted, false));
        for (int i = 0; i < sites.length(); i++) {
            final int index = i;
            JSONObject site = sites.optJSONObject(i);
            boolean current = site.optString("id").equals(returnInstance);
            LinearLayout row = new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL);
            row.setBackground(ui.surface(current ? ui.tint : ui.card, true)); ui.pad(row, 4, 3); list.addView(row);
            LinearLayout entry = new LinearLayout(this); entry.setOrientation(LinearLayout.VERTICAL);
            ui.clickable(entry, current ? ui.tint : ui.card, () -> open(site, "")); ui.pad(entry, 12, 10);
            if (current) entry.addView(ui.text("当前实例", 12, ui.accent, true));
            entry.addView(ui.text(site.optString("name"), 18, ui.ink, true));
            entry.addView(ui.text(site.optString("origin"), 14, ui.muted, false));
            entry.setContentDescription(site.optString("name") + "\n" + site.optString("origin"));
            row.addView(entry, new LinearLayout.LayoutParams(0, -2, 1));
            Button more = new Button(this); more.setText("⋮"); more.setContentDescription("管理 " + site.optString("name"));
            more.setTextColor(ui.ink); more.setTextSize(20); more.setBackgroundResource(android.R.drawable.list_selector_background);
            row.addView(more, ui.dp(48), ui.dp(48)); ui.gap(list, 8);
            more.setOnClickListener(v -> {
                PopupMenu menu = new PopupMenu(this, more);
                menu.getMenu().add("重新连接").setOnMenuItemClickListener(item -> { launch(site, "", true); return true; });
                menu.getMenu().add("编辑").setOnMenuItemClickListener(item -> { edit(index); return true; });
                menu.getMenu().add("使用 Focus 授权链接").setOnMenuItemClickListener(item -> { authorize(site); return true; });
                menu.getMenu().add("删除").setOnMenuItemClickListener(item -> {
                    new AlertDialog.Builder(this).setMessage("删除这个实例及此 App 保存的凭据和页面数据？")
                        .setNegativeButton("取消", null).setPositiveButton("删除", (d,w) ->
                            { sites.remove(index); persist(); forget(site); render(); }).show();
                    return true;
                });
                menu.show();
            });
        }
        ui.gap(list, 20);
        list.addView(ui.button("保留实例页面数 · " + pages.limit(), false, () ->
            new AlertDialog.Builder(this).setTitle("保留实例页面数")
                .setSingleChoiceItems(new String[]{"1", "2", "3", "4", "5"}, pages.limit() - 1, (dialog, index) -> {
                    pages.setLimit(index + 1); dialog.dismiss(); render();
                }).setNegativeButton("取消", null).show()));
    }

    @Override protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if ((code == 24 || code == 25) && result == RESULT_OK && data != null)
            setIntent(new Intent().setAction(PICK).putExtra("return-instance", returnInstance)
                .putExtra("target", data.getStringExtra("site")).putExtra("recordThread",data.getStringExtra("recordThread")));
    }

    private void persist() { prefs.edit().putString("list", sites.toString()).commit(); }

    private void forget(JSONObject site) {
        String id = site.optString("id");
        pages.forget(id);
        try (RecordsStore store = new RecordsStore(this)) { store.call("forget", id, site.optString("origin"), new JSONObject()); }
        catch (JSONException invalid) { throw new IllegalStateException(invalid); }
        getSharedPreferences("server-updates", MODE_PRIVATE).edit().remove(id).apply();
        BasicVault.erase(this, id);
        deleteSharedPreferences("page-" + id);
        removeTree(new File(getApplicationInfo().dataDir, "app_webview_" + id));
    }

    private static void removeTree(File file) {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) removeTree(child);
        file.delete();
    }

    private void edit(int index) {
        JSONObject old = index < 0 ? new JSONObject() : sites.optJSONObject(index);
        LinearLayout form = Views.column(this);
        ui.pad(form, 22, 12);
        form.addView(ui.text("实例名称", 14, ui.muted, true));
        EditText name = Views.field(this, form, "名称", old.optString("name"));
        ui.gap(form, 12); form.addView(ui.text("访问地址", 14, ui.muted, true));
        EditText address = Views.field(this, form, "https://focus.example", old.optString("origin"));
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        ui.gap(form, 16);
        CheckBox sso = new CheckBox(this); sso.setText("允许跨站登录（SSO）");
        sso.setChecked(old.optBoolean("sso")); form.addView(sso);
        form.addView(ui.text("仅在入口需要跳到其他网站登录时开启。HTTP Basic 会在连接时询问。", 14, ui.muted, false));
        ScrollView fields = new ScrollView(this); fields.addView(form);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(index < 0 ? "添加实例" : "编辑实例").setView(fields)
            .setNegativeButton("取消", null).setPositiveButton("保存", null).create();
        dialog.show();
        dialog.getButton(-1).setOnClickListener(v -> {
            try {
                String origin = Site.entry(address.getText().toString());
                String label = name.getText().toString().trim();
                if (label.isEmpty()) { name.setError("请输入名称"); return; }
                for (int i = 0; i < sites.length(); i++)
                    if (i != index && sites.optJSONObject(i).optString("origin").equals(origin)) throw new IllegalArgumentException("入口已存在");
                boolean reuse = origin.equals(old.optString("origin"));
                JSONObject site = new JSONObject().put("origin", origin).put("name", label).put("sso", sso.isChecked())
                    .put("id", reuse ? old.getString("id") : UUID.randomUUID().toString());
                if (index < 0) sites.put(site); else sites.put(index, site);
                persist();
                if (!reuse && index >= 0) forget(old);
                dialog.dismiss(); render();
            } catch (Exception e) { address.setError(e.getMessage()); }
        });
    }

    private void authorize(JSONObject site) {
        LinearLayout form = Views.column(this);
        ui.pad(form, 22, 12);
        form.addView(ui.text("仅在 Focus 提示需要授权时，粘贴这个实例签发的链接。", 14, ui.muted, false));
        EditText link = Views.field(this, form, "此入口的 Focus 授权链接", "");
        new AlertDialog.Builder(this).setTitle("使用 Focus 授权链接").setView(form).setNegativeButton("取消", null)
            .setPositiveButton("打开", (d,w) -> {
                String url = link.getText().toString().trim();
                if (Site.root(url, site.optString("origin")) && url.contains("#token=")) open(site, url);
                else Views.message(this, "需要同一入口的授权链接");
            }).show();
    }

    private void open(JSONObject site, String link) {
        launch(site, link, false);
    }
    private void launch(JSONObject site, String link, boolean reload) {
        pages.open(site, link, reload, sites);
    }
}
