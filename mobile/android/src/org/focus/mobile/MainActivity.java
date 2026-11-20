package org.focus.mobile;

import android.app.*;
import android.content.*;
import android.os.Bundle;
import android.widget.*;
import org.json.*;
import java.util.UUID;
import java.io.File;

public final class MainActivity extends Activity {
    private JSONArray sites;
    private SharedPreferences prefs;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("instances", MODE_PRIVATE);
        try { sites = new JSONArray(prefs.getString("list", "[]")); }
        catch (JSONException e) { throw new IllegalStateException(e); }
        render();
        if (state == null) {
            for (int i = 0; i < sites.length(); i++) {
                JSONObject site = sites.optJSONObject(i);
                if (site.optString("id").equals(prefs.getString("active", ""))) { open(site, ""); break; }
            }
        }
    }

    private void render() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = Views.column(this);
        scroll.addView(list);
        Views.install(this, scroll);
        TextView title = new TextView(this);
        title.setText("Focus 实例"); title.setTextSize(24); list.addView(title);
        Views.button(this, list, "添加实例", () -> edit(-1));
        for (int i = 0; i < sites.length(); i++) {
            final int index = i;
            JSONObject site = sites.optJSONObject(i);
            Views.button(this, list, site.optString("name") + "\n" + site.optString("origin"), () -> open(site, ""));
            LinearLayout row = new LinearLayout(this); list.addView(row);
            Views.button(this, row, "编辑", () -> edit(index));
            Views.button(this, row, "授权链接", () -> authorize(site));
            Views.button(this, row, "删除", () -> new AlertDialog.Builder(this)
                .setMessage("删除这个实例及其在 App 中保存的凭据和页面数据？")
                .setNegativeButton("取消", null).setPositiveButton("删除", (d,w) -> {
                    sites.remove(index); persist(); forget(site); render();
                }).show());
        }
    }

    private void persist() { prefs.edit().putString("list", sites.toString()).commit(); }

    private void forget(JSONObject site) {
        String id = site.optString("id");
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
        prefs.edit().putString("active", site.optString("id")).commit();
        startActivityForResult(new Intent(this, ClientActivity.class).putExtra("site", site.toString()).putExtra("link", link), 1);
    }

    @Override protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req == 1) prefs.edit().remove("active").apply();
    }
}
