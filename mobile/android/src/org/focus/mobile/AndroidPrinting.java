package org.focus.mobile;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.os.UserManager;
import android.print.PageRange;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.webkit.WebView;
import java.util.UUID;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** The current trusted document owns one optional, bounded print recording. */
final class AndroidPrinting {
    private static final long LIMIT_MS = 300_000;
    private final Activity activity;
    private Recording recording;

    AndroidPrinting(Activity activity) { this.activity = activity; }

    private static final class Recording {
        final String id = UUID.randomUUID().toString();
        final long started = SystemClock.elapsedRealtime();
        JSONArray events = new JSONArray();
        int lastAttempt, dropped;

        long elapsed() { return SystemClock.elapsedRealtime() - started; }

        void record(int attempt, String source, String event) {
            long ms = elapsed();
            if (events == null || ms >= LIMIT_MS) return;
            if (events.length() == 40) { events.remove(0); dropped++; }
            // Rows contain only elapsed time, the local attempt number and fixed enums.
            events.put(new JSONArray().put(ms).put(attempt).put(source).put(event));
        }
    }

    void clear() {
        if (recording != null) recording.events = null;
        recording = null;
    }

    String handle(WebView view, String operation, String value) {
        if ("print".equals(operation)) return print(view, value, false, null);
        if ("print-diag-start".equals(operation)) {
            clear();
            recording = new Recording();
            return recording.id;
        }
        Recording current = recording;
        if (current == null || value == null) return "error";
        try {
            if ("print-diag-stop".equals(operation) && current.id.equals(value)) {
                try {
                    return new JSONObject().put("sdk", Build.VERSION.SDK_INT)
                        .put("elapsedMs", Math.min(current.elapsed(), LIMIT_MS)).put("droppedEvents", current.dropped)
                        .put("events", current.events).toString();
                } finally { clear(); }
            }
            if (!"print-diag-run".equals(operation) || value.length() > 2048 || current.elapsed() >= LIMIT_MS) return "error";
            JSONObject request = new JSONObject(value);
            int number = request.getInt("attempt");
            String source = request.getString("source");
            boolean test = "native-test".equals(source);
            if (!current.id.equals(request.getString("session")) || number <= current.lastAttempt
                    || (!test && !"webview".equals(source))) return "error";
            String name = test ? "Focus Mobile print test" : request.getString("name");
            current.lastAttempt = number;
            Consumer<String> trace = event -> current.record(number, source, event);
            trace.accept("request");
            try {
                UserManager users = activity.getSystemService(UserManager.class);
                if (users != null && users.hasUserRestriction(UserManager.DISALLOW_PRINTING)) trace.accept("printing-restricted");
            } catch (RuntimeException unavailable) { /* An optional policy query cannot block printing. */ }
            return print(view, name, test, trace);
        } catch (JSONException | RuntimeException invalid) { return "error"; }
    }

    private String print(WebView view, String name, boolean test, Consumer<String> trace) {
        try {
            PrintManager manager = activity.getSystemService(PrintManager.class);
            if (manager == null) return failed(trace, "no-service");
            if (name == null || name.isEmpty() || name.length() > 255) return failed(trace, "invalid-name");
            PrintDocumentAdapter adapter = test ? new PrintTestPage(activity) : view.createPrintDocumentAdapter(name);
            if (adapter == null) return failed(trace, "no-adapter");
            if (trace != null) {
                trace.accept("adapter-created");
                adapter = new ObservedAdapter(adapter, trace);
            }
            if (manager.print(name, adapter, null) == null) return failed(trace, "no-job");
            if (trace != null) trace.accept("job-returned");
            return "ok";
        } catch (SecurityException denied) { return failed(trace, "security-exception"); }
        catch (RuntimeException unavailable) { return failed(trace, "exception"); }
    }

    private static String failed(Consumer<String> trace, String reason) {
        if (trace != null) trace.accept(reason);
        return "error";
    }

    /** Forward the original callbacks, cancellation signal and descriptor unchanged. */
    private static final class ObservedAdapter extends PrintDocumentAdapter {
        private final PrintDocumentAdapter delegate;
        private final Consumer<String> trace;
        ObservedAdapter(PrintDocumentAdapter delegate, Consumer<String> trace) { this.delegate = delegate; this.trace = trace; }
        @Override public void onStart() { trace.accept("start"); delegate.onStart(); }
        @Override public void onLayout(PrintAttributes oldAttrs, PrintAttributes newAttrs, CancellationSignal cancel,
                LayoutResultCallback callback, Bundle extras) {
            trace.accept("layout");
            delegate.onLayout(oldAttrs, newAttrs, cancel, callback, extras);
        }
        @Override public void onWrite(PageRange[] pages, ParcelFileDescriptor destination, CancellationSignal cancel,
                WriteResultCallback callback) {
            trace.accept("write");
            delegate.onWrite(pages, destination, cancel, callback);
        }
        @Override public void onFinish() { trace.accept("finish"); delegate.onFinish(); }
    }
}
