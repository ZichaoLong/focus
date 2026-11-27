package org.focus.mobile;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.os.UserManager;
import android.print.PageRange;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintJob;
import android.print.PrintManager;
import android.webkit.WebView;
import java.util.UUID;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** A print host owns at most one bounded recording. */
final class AndroidPrinting {
    static final long LIMIT_MS = 300_000;
    private static final String TEST_PAGE_NAME = "Focus Mobile print test";
    private final Activity activity;
    private Recording recording;
    private boolean dispatchingPrint;

    AndroidPrinting(Activity activity) { this.activity = activity; }

    private static final class Recording {
        final String id = UUID.randomUUID().toString();
        final long started = SystemClock.elapsedRealtime();
        final PrintJobDiagnostics observations;
        JSONArray events = new JSONArray();
        int lastAttempt, dropped;
        String lastSource;

        Recording(boolean observeJobs) { observations = observeJobs ? new PrintJobDiagnostics(started) : null; }

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
        if (recording != null) {
            if (recording.observations != null) recording.observations.close();
            recording.events = null;
        }
        recording = null;
    }

    void hostEvent(String event) {
        Recording current = recording;
        if (current != null && current.observations != null && current.lastAttempt > 0)
            current.observations.record(current.lastAttempt, current.lastSource, event);
    }

    void intentEvent(String event) {
        if (Looper.myLooper() == Looper.getMainLooper() && dispatchingPrint) hostEvent(event);
    }

    /** Called directly by the native Activity's button listener. */
    boolean startNativeButtonTest() {
        clear();
        recording = new Recording(true);
        return "ok".equals(recordedPrint(null, TEST_PAGE_NAME, true, recording, 1, "native-button"));
    }

    JSONObject finishRecording() throws JSONException {
        Recording current = recording;
        try {
            JSONObject snapshot = new JSONObject();
            if (current.observations != null) snapshot.put("observations", current.observations.finish());
            return snapshot.put("sdk", Build.VERSION.SDK_INT).put("elapsedMs", Math.min(current.elapsed(), LIMIT_MS))
                .put("droppedEvents", current.dropped).put("events", current.events);
        } finally { clear(); }
    }

    String handle(WebView view, String operation, String value) {
        if ("print".equals(operation)) return print(view, value, false, null);
        if ("print-diag-start".equals(operation)) {
            clear();
            recording = new Recording("print-job-diagnostics".equals(value));
            return recording.id;
        }
        Recording current = recording;
        if (current == null || value == null) return "error";
        try {
            if ("print-diag-stop".equals(operation) && current.id.equals(value)) return finishRecording().toString();
            if (!"print-diag-run".equals(operation) || value.length() > 2048 || current.elapsed() >= LIMIT_MS) return "error";
            JSONObject request = new JSONObject(value);
            int number = request.getInt("attempt");
            String source = request.getString("source");
            boolean test = "native-test".equals(source);
            if (!current.id.equals(request.getString("session")) || number <= current.lastAttempt
                    || (!test && !"webview".equals(source))) return "error";
            String name = test ? TEST_PAGE_NAME : request.getString("name");
            return recordedPrint(view, name, test, current, number, source);
        } catch (JSONException | RuntimeException invalid) { return "error"; }
    }

    private String recordedPrint(WebView view, String name, boolean test, Recording current, int number, String source) {
        current.lastAttempt = number;
        current.lastSource = source;
        current.record(number, source, "request");
        if (current.observations != null)
            hostEvent(activity.hasWindowFocus() ? "window-initial-focused" : "window-initial-unfocused");
        try {
            UserManager users = activity.getSystemService(UserManager.class);
            if (users != null && users.hasUserRestriction(UserManager.DISALLOW_PRINTING))
                current.record(number, source, "printing-restricted");
        } catch (RuntimeException unavailable) { /* An optional policy query cannot block printing. */ }
        return print(view, name, test, current);
    }

    private String print(WebView view, String name, boolean test, Recording current) {
        int attempt = current == null ? 0 : current.lastAttempt;
        String source = current == null ? "webview" : current.lastSource;
        Consumer<String> trace = current == null ? null : event -> current.record(attempt, source, event);
        PrintJobDiagnostics observations = current == null ? null : current.observations;
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
            PrintJob job;
            dispatchingPrint = observations != null;
            try { job = manager.print(name, adapter, null); }
            finally { dispatchingPrint = false; }
            if (job == null) return failed(trace, "no-job");
            if (trace != null) trace.accept("job-returned");
            if (observations != null) {
                try { observations.watch(manager, job, attempt, source); }
                catch (RuntimeException unavailable) { observations.record(attempt, source, "job-query-error"); }
            }
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
