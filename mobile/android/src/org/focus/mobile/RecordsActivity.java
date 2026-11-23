package org.focus.mobile;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.widget.FrameLayout;
import org.json.*;

/** Hosts the device record index and delegates status checks to each entry's profile. */
public final class RecordsActivity extends Activity {
    private RecordsStore store;
    private RecordsPanel panel;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        store=new RecordsStore(this);
        FrameLayout frame=new FrameLayout(this); Views.install(this,frame);
        try {
            JSONArray sites=new JSONArray(getSharedPreferences("instances",MODE_PRIVATE).getString("list","[]"));
            for (int i=0;i<sites.length();i++) {
                JSONObject site=sites.getJSONObject(i);
                if (site.getString("id").equals(getIntent().getStringExtra("active")))
                    site.put("reading",getSharedPreferences("page-"+site.getString("id"),MODE_PRIVATE).getString("thread",""));
                store.call("register",site.getString("id"),site.getString("origin"),new JSONObject());
            }
            panel=new RecordsPanel(this,frame,store,sites,"","",(op,value)->{
                if ("back".equals(op)) finish();
                if ("visit".equals(op)) try {
                    JSONObject data=new JSONObject(value);
                    setResult(RESULT_OK,new Intent().putExtra("site",data.getString("entry")).putExtra("recordThread",data.getString("thread")));
                    finish();
                } catch (JSONException invalid) { Views.message(this,"无法打开记录"); }
            });
        } catch (Exception invalid) { Views.message(this,"无法读取本机离线记录"); finish(); }
    }
    @Override public void onBackPressed() { if (panel!=null) panel.back(); else finish(); }
    @Override protected void onPause() { if(panel!=null) panel.cancelCheck(); super.onPause(); }
    @Override protected void onDestroy() { if(panel!=null) panel.close(); if(store!=null) store.close(); super.onDestroy(); }
}
