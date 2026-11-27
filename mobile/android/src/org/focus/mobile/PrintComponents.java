package org.focus.mobile;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import org.json.JSONException;
import org.json.JSONObject;

/** Package-manager observations for the native test. A vendor may supply different components. */
final class PrintComponents {
    private static final String SPOOLER = "com.android.printspooler";
    private static final ComponentName SERVICE = new ComponentName(SPOOLER, SPOOLER + ".model.PrintSpoolerService");

    private interface Lookup { String read() throws PackageManager.NameNotFoundException; }

    private static String lookup(Lookup query) {
        try { return query.read(); }
        catch (PackageManager.NameNotFoundException missing) { return "not-visible"; }
        catch (RuntimeException unavailable) { return "unknown"; }
    }

    static JSONObject read(Context context) {
        PackageManager pm = context.getPackageManager();
        JSONObject env = new JSONObject();
        try {
            env.put("appVersion", lookup(() -> pm.getPackageInfo(context.getPackageName(), 0).versionName));
            try { env.put("printingFeature", pm.hasSystemFeature(PackageManager.FEATURE_PRINTING)); }
            catch (RuntimeException unavailable) { env.put("printingFeature", JSONObject.NULL); }
            env.put("aospSpoolerPackage", lookup(() -> pm.getApplicationInfo(SPOOLER,
                    PackageManager.MATCH_DISABLED_COMPONENTS).enabled ? "enabled" : "disabled"));
            env.put("aospSpoolerService", lookup(() -> {
                try { pm.getServiceInfo(SERVICE, 0); return "enabled"; }
                catch (PackageManager.NameNotFoundException inactive) {
                    pm.getServiceInfo(SERVICE, PackageManager.MATCH_DISABLED_COMPONENTS);
                    return "disabled";
                }
            }));
            env.put("printDialog", lookup(() -> {
                // Match the same action and URI scheme that Android uses, without launching it.
                Intent dialog = new Intent("android.print.PRINT_DIALOG", Uri.fromParts("printjob", "focus-test", null));
                int flags = PackageManager.MATCH_DEFAULT_ONLY;
                if (pm.resolveActivity(dialog, flags) != null) return "resolvable";
                return pm.resolveActivity(dialog, flags | PackageManager.MATCH_DISABLED_COMPONENTS) != null
                        ? "disabled" : "not-visible";
            }));
            return env;
        } catch (JSONException invalid) { throw new IllegalStateException(invalid); }
    }
}
