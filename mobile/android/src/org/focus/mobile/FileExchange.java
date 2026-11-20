package org.focus.mobile;

import android.app.Activity;
import android.content.*;
import android.net.Uri;
import android.util.Base64;
import android.webkit.*;
import java.io.*;
import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

// Only accepts picker-issued content URIs. All staging and copies run off the UI thread.
final class FileExchange {
    private final Activity activity;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private ValueCallback<Uri[]> upload;
    private JsPromptResult picker;
    private File staged;
    private Uri destination;
    private int generation;

    FileExchange(Activity activity) { this.activity = activity; }

    boolean upload(ValueCallback<Uri[]> callback, WebChromeClient.FileChooserParams params) {
        if (upload != null) upload.onReceiveValue(null);
        upload = callback;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        String[] types = params.getAcceptTypes();
        if (types.length > 0 && !types[0].isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, types);
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE);
        try { activity.startActivityForResult(intent, 2); }
        catch (ActivityNotFoundException e) { upload.onReceiveValue(null); upload = null; }
        return true;
    }

    void handle(String op, String value, JsPromptResult result) {
        if ("choose".equals(op)) {
            if (picker != null || staged != null || value.isEmpty() || value.length() > 255 || value.matches(".*[/\\\\].*")) {
                result.confirm("error"); return;
            }
            picker = result;
            try { activity.startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("application/octet-stream").putExtra(Intent.EXTRA_TITLE, value), 3); }
            catch (ActivityNotFoundException e) { picker = null; result.confirm("error"); }
            return;
        }
        if ("abort".equals(op)) { cancel(); result.confirm("ok"); return; }
        File file = staged;
        Uri target = destination;
        int request = generation;
        if (file == null || target == null || value.length() > 32768 || !("write".equals(op) || "finish".equals(op))) {
            result.confirm("error"); return;
        }
        boolean finish = "finish".equals(op);
        io.execute(() -> {
            boolean ok = false;
            try {
                if (finish) {
                    try (InputStream in = new FileInputStream(file); OutputStream out = activity.getContentResolver().openOutputStream(target, "wt")) {
                        if (out == null) throw new IOException();
                        byte[] buffer = new byte[65536];
                        int n;
                        while ((n = in.read(buffer)) >= 0) out.write(buffer, 0, n);
                    }
                } else {
                    try (OutputStream out = new FileOutputStream(file, true)) { out.write(Base64.decode(value, Base64.NO_WRAP)); }
                }
                ok = true;
            } catch (Exception ignored) { /* signal failure to the Web caller */ }
            boolean success = ok;
            activity.runOnUiThread(() -> {
                if (request != generation) { result.cancel(); return; }
                if (finish || !success) cancel();
                result.confirm(success ? "ok" : "error");
            });
        });
    }

    void result(int code, int resultCode, Intent intent) {
        boolean accepted = resultCode == Activity.RESULT_OK && intent != null;
        if (code == 2 && upload != null) {
            ArrayList<Uri> uris = new ArrayList<>();
            if (accepted && intent.getClipData() != null) {
                ClipData clip = intent.getClipData();
                for (int i = 0; i < clip.getItemCount(); i++) add(uris, clip.getItemAt(i).getUri());
            } else if (accepted) add(uris, intent.getData());
            upload.onReceiveValue(uris.isEmpty() ? null : uris.toArray(new Uri[0])); upload = null;
        }
        if (code == 3 && picker != null) {
            JsPromptResult pending = picker; picker = null;
            Uri selected = accepted ? intent.getData() : null;
            if (selected == null || !"content".equals(selected.getScheme())) { pending.cancel(); return; }
            try {
                staged = File.createTempFile("focus-save-", ".part", activity.getCacheDir());
                destination = selected; pending.confirm("ok");
            } catch (IOException e) { pending.confirm("error"); }
        }
    }

    private static void add(ArrayList<Uri> uris, Uri uri) {
        if (uri != null && "content".equals(uri.getScheme())) uris.add(uri);
    }
    void cancel() {
        generation++;
        if (upload != null) { upload.onReceiveValue(null); upload = null; }
        if (picker != null) { picker.cancel(); picker = null; }
        if (staged != null) staged.delete();
        staged = null; destination = null;
    }
    void dispose() { cancel(); io.shutdown(); }
}
