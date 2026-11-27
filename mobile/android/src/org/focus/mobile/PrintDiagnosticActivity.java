package org.focus.mobile;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** A native user gesture in its own Activity, available with an empty instance list. */
public final class PrintDiagnosticActivity extends PrintHostActivity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable timeout = this::freeze;
    private JSONObject components;
    private Button test, stop, copy;
    private TextView componentStatus, status, details;
    private boolean recording;
    private String report = "";

    @Override public void onCreate(Bundle state) {
        ManagerStyle ui = new ManagerStyle(this);
        if (ui.dark) setTheme(android.R.style.Theme_Material_NoActionBar);
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(ui.canvas);
        LinearLayout list = Views.column(this);
        ui.pad(list, 20, 20);
        scroll.addView(list);
        Views.install(this, scroll);
        Views.systemBars(this, ui.dark, ui.canvas);
        list.addView(ui.button("返回实例管理", false, this::finish), -2, -2);
        ui.gap(list, 16);
        list.addView(ui.text("系统打印诊断", 26, ui.ink, true));
        ui.gap(list, 8);
        list.addView(ui.text("用安卓原生按钮打印一页固定文字。如出现系统打印面板，完成操作或返回此页。点击测试约 40 秒后复制报告。", 15, ui.muted, false));
        ui.gap(list, 12);
        componentStatus = ui.text("正在检查系统打印组件…", 15, ui.ink, false);
        list.addView(componentStatus);
        ui.gap(list, 12);
        test = ui.button("打印一页测试文本", true, this::startTest);
        list.addView(test);
        status = ui.text("", 15, ui.muted, false);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        list.addView(status);
        stop = ui.button("结束记录并查看报告", false, this::freeze);
        copy = ui.button("复制诊断报告", false, this::copyReport);
        list.addView(stop);
        list.addView(copy);
        stop.setVisibility(View.GONE);
        copy.setVisibility(View.GONE);
        details = ui.text("", 14, ui.ink, false);
        details.setTextIsSelectable(true);
        list.addView(details);

        // Optional package visibility checks must never gate the actual print request.
        new Thread(() -> {
            JSONObject observed = PrintComponents.read(getApplicationContext());
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                components = observed;
                componentStatus.setText("系统打印面板　" + label(observed.optString("printDialog"))
                    + "\n标准安卓打印后台组件　" + label(observed.optString("aospSpoolerService")));
            });
        }, "focus-print-components").start();
    }

    private static String label(String state) {
        switch (state) {
            case "enabled": return "已启用";
            case "resolvable": return "可解析";
            case "disabled": return "已停用";
            case "not-visible": return "本应用未查到";
            default: return "无法查询";
        }
    }

    private void startTest() {
        recording = true;
        report = "";
        details.setText("");
        test.setEnabled(false);
        stop.setVisibility(View.VISIBLE);
        copy.setVisibility(View.VISIBLE);
        boolean submitted = printing.startNativeButtonTest();
        status.setText(submitted ? "系统已返回打印任务，正在记录后续状态。" : "未取得打印任务，可以查看或复制诊断报告。");
        main.postDelayed(timeout, AndroidPrinting.LIMIT_MS);
    }

    private void freeze() {
        if (!recording) return;
        recording = false;
        main.removeCallbacks(timeout);
        try {
            JSONObject nativeReport = printing.finishRecording();
            expandEvents(nativeReport);
            expandEvents(nativeReport.getJSONObject("observations"));
            report = new JSONObject().put("format", "focus-mobile-native-print/v1")
                    .put("environment", components == null ? new JSONObject().put("status", "pending") : components)
                    .put("native", nativeReport).toString(2);
        } catch (JSONException invalid) { report = ""; }
        details.setText(report);
        status.setText(report.isEmpty() ? "未能读取报告，请重新测试。" : "记录已结束。");
        stop.setVisibility(View.GONE);
        copy.setVisibility(report.isEmpty() ? View.GONE : View.VISIBLE);
        test.setEnabled(true);
    }

    private static void expandEvents(JSONObject trace) throws JSONException {
        JSONArray rows = trace.getJSONArray("events");
        JSONArray events = new JSONArray();
        for (int i = 0; i < rows.length(); i++) {
            JSONArray row = rows.getJSONArray(i);
            events.put(new JSONObject().put("ms", row.getLong(0)).put("attempt", row.getInt(1))
                    .put("source", row.getString(2)).put("event", row.getString(3)));
        }
        trace.put("status", "collected").put("events", events);
    }

    private void copyReport() {
        freeze();
        if (report.isEmpty()) return;
        try {
            ClipboardManager clipboard = getSystemService(ClipboardManager.class);
            if (clipboard != null) {
                clipboard.setPrimaryClip(ClipData.newPlainText("Focus 打印诊断", report));
                status.setText("诊断报告已复制。");
                return;
            }
        } catch (RuntimeException unavailable) { /* The report remains selectable below. */ }
        status.setText("剪贴板暂不可用，可以长按选取下方的报告。");
    }

    @Override protected void onDestroy() {
        main.removeCallbacks(timeout);
        super.onDestroy();
    }
}
