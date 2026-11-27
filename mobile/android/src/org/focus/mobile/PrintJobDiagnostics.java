package org.focus.mobile;

import android.os.SystemClock;
import android.print.PrintJob;
import android.print.PrintJobInfo;
import android.print.PrintManager;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Optional observations after a print request, scoped to one document recording. */
final class PrintJobDiagnostics {
    private static final ScheduledThreadPoolExecutor worker = newWorker();
    private static final int[] SAMPLE_SECONDS = {0, 2, 10, 30};
    private final long started;
    private JSONArray events = new JSONArray();
    private final List<ScheduledFuture<?>> samples = new ArrayList<>();
    private int watched, dropped;

    PrintJobDiagnostics(long started) { this.started = started; }

    private static ScheduledThreadPoolExecutor newWorker() {
        ScheduledThreadPoolExecutor pool = new ScheduledThreadPoolExecutor(1, r -> new Thread(r, "focus-print-diagnostics"));
        pool.setRemoveOnCancelPolicy(true);
        pool.setKeepAliveTime(10, TimeUnit.SECONDS);
        pool.allowCoreThreadTimeOut(true);
        return pool;
    }

    synchronized void record(int attempt, String source, String event) {
        long ms = SystemClock.elapsedRealtime() - started;
        if (events == null || ms >= AndroidPrinting.LIMIT_MS) return;
        if (events.length() == 40) { events.remove(0); dropped++; }
        events.put(new JSONArray().put(ms).put(attempt).put(source).put(event));
    }

    // Android can return cached info on an old handle after a job disappears.
    // Match this job in the app-visible list before reading its current state.
    private static String state(PrintManager manager, PrintJob target) {
        for (PrintJob listed : manager.getPrintJobs()) {
            if (!target.getId().equals(listed.getId())) continue;
            switch (listed.getInfo().getState()) {
                case PrintJobInfo.STATE_CREATED: return "job-created";
                case PrintJobInfo.STATE_QUEUED: return "job-queued";
                case PrintJobInfo.STATE_STARTED: return "job-started";
                case PrintJobInfo.STATE_BLOCKED: return "job-blocked";
                case PrintJobInfo.STATE_COMPLETED: return "job-completed";
                case PrintJobInfo.STATE_FAILED: return "job-failed";
                case PrintJobInfo.STATE_CANCELED: return "job-canceled";
                default: return "job-unknown";
            }
        }
        return "job-not-listed";
    }

    synchronized void watch(PrintManager manager, PrintJob job, int attempt, String source) {
        if (watched == 4) { record(attempt, source, "job-sample-limit"); return; }
        watched++;
        Runnable sample = new Runnable() {
            private boolean first = true, terminal;
            @Override public void run() {
                synchronized (PrintJobDiagnostics.this) {
                    if (events == null || terminal || SystemClock.elapsedRealtime() - started >= AndroidPrinting.LIMIT_MS) return;
                    if (first) { first = false; record(attempt, source, "job-query-start"); }
                }
                // Binder reads can block. Stop/export never waits for the system service.
                String result;
                try { result = state(manager, job); }
                catch (RuntimeException unavailable) { result = "job-query-error"; }
                record(attempt, source, result);
                terminal = "job-completed".equals(result) || "job-canceled".equals(result) || "job-failed".equals(result);
            }
        };
        for (int delay : SAMPLE_SECONDS) samples.add(worker.schedule(sample, delay, TimeUnit.SECONDS));
    }

    synchronized void close() {
        events = null;
        for (ScheduledFuture<?> sample : samples) sample.cancel(false);
        samples.clear();
    }

    synchronized JSONObject finish() throws JSONException {
        JSONObject snapshot = new JSONObject().put("events", events).put("droppedEvents", dropped);
        close();
        return snapshot;
    }
}
