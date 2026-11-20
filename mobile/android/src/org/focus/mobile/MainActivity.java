package org.focus.mobile;

import android.app.*;
import android.content.*;
import android.os.Bundle;
import android.widget.*;
import org.json.*;
import java.util.UUID;
import java.io.File;

public final class MainActivity extends Activity {
    static final String PICK = "org.focus.mobile.PICK";
    private JSONArray sites;
    private SharedPreferences prefs;
    private PageSlots pages;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("instances", MODE_PRIVATE);
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
            setIntent(new Intent());
        } else for (int i = 0; i < sites.length(); i++) {
            JSONObject site = sites.optJSONObject(i);
            if (site.optString("id").equals(prefs.getString("active", ""))) { open(site, ""); break; }
        }
    }

    @Override protected void onDestroy() { pages.finishOpening(); super.onDestroy(); }

    private void render() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = Views.column(this);
        scroll.addView(list);
        Views.install(this, scroll);
        TextView title = new TextView(this);
        title.setText("Focus 实例"); title.setTextSize(24); list.addView(title);
        for (int i = 0; i < sites.length(); i++) {
            final int index = i;
            JSONObject site = sites.optJSONObject(i);
            LinearLayout row = new LinearLayout(this); list.addView(row);
            Button entry = Views.button(this, row, site.optString("name") + "\n" + site.optString("origin"), () -> open(site, ""));
            entry.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
            Button more = new Button(this); more.setText("⋮"); more.setContentDescription("管理 " + site.optString("name"));
            row.addView(more);
            more.setOnClickListener(v -> {
                PopupMenu menu = new PopupMenu(this, more);
                menu.getMenu().add("重新连接").setOnMenuItemClickListener(item -> { launch(site, "", true); return true; });
                menu.getMenu().add("编辑").setOnMenuItemClickListener(item -> { edit(index); return true; });
                menu.getMenu().add("授权链接").setOnMenuItemClickListener(item -> { authorize(site); return true; });
                menu.getMenu().add("删除").setOnMenuItemClickListener(item -> {
                    new AlertDialog.Builder(this).setMessage("删除这个实例及此 App 保存的凭据和页面数据？")
                        .setNegativeButton("取消", null).setPositiveButton("删除", (d,w) ->
                            { sites.remove(index); persist(); forget(site); render(); }).show();
                    return true;
                });
                menu.show();
            });
        }
        Views.button(this, list, "添加实例", () -> edit(-1));
    }

    private void persist() { prefs.edit().putString("list", sites.toString()).commit(); }

    private void forget(JSONObject site) {
        String id = site.optString("id");
        pages.forget(id);
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
        EditText name = Views.field(this, form, "名称", old.optString("name"));
        EditText address = Views.field(this, form, "https://focus.example", old.optString("origin"));
        CheckBox sso = new CheckBox(this); sso.setText("网页登录 / SSO（允许 HTTPS 登录跳转）");
        sso.setChecked(old.optBoolean("sso")); form.addView(sso);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("实例入口").setView(form)
            .setNegativeButton("取消", null).setPositiveButton("保存", null).create();
        dialog.show();
        dialog.getButton(-1).setOnClickListener(v -> {
            try {
                String origin = Site.entry(address.getText().toString());
                String label = name.getText().toString().trim();
                if (label.isEmpty()) throw new IllegalArgumentException("请输入名称");
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
        EditText link = Views.field(this, form, "此入口的 Focus 授权链接", "");
        new AlertDialog.Builder(this).setTitle("打开一次性授权链接").setView(form).setNegativeButton("取消", null)
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
