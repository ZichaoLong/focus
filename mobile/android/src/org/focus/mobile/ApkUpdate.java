package org.focus.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.provider.Settings;
import android.util.Base64;
import android.webkit.JsPromptResult;
import java.io.*;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Locale;
import org.json.JSONObject;

final class ApkUpdate {
    static final int INSTALL_PERMISSION = 14;
    private final Activity activity;
    private final File directory;
    private File temporary, awaitingPermission;
    private FileOutputStream output;
    private JSONObject release;
    private MessageDigest digest;
    private long received;
    private String installedHash;

    ApkUpdate(Activity activity) {
        this.activity = activity;
        directory = new File(activity.getCacheDir(), "mobile-installer");
    }

    private PackageInfo installed() throws Exception {
        return activity.getPackageManager().getPackageInfo(activity.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) result.append(String.format(Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }

    String handle(String operation, String value) {
        try {
            switch (operation) {
                case "apk-info":
                    PackageInfo info = installed();
                    if (installedHash == null) {
                        MessageDigest hash = MessageDigest.getInstance("SHA-256");
                        try (InputStream in = new FileInputStream(activity.getApplicationInfo().sourceDir)) {
                            byte[] buffer = new byte[32768];
                            for (int n; (n = in.read(buffer)) != -1;) hash.update(buffer, 0, n);
                        }
                        installedHash = hex(hash.digest());
                    }
                    return new JSONObject().put("version", info.versionName).put("version_code", info.getLongVersionCode())
                        .put("sha256", installedHash).toString();
                case "apk-begin":
                    cancel();
                    if (value.length() > 4096) throw new IOException("无效的版本清单");
                    release = new JSONObject(value);
                    if (!activity.getPackageName().equals(release.getString("package"))
                        || release.getLong("version_code") < installed().getLongVersionCode()
                        || !release.getString("sha256").matches("[a-f0-9]{64}")
                        || release.getLong("size") <= 0 || release.getLong("size") > 32 * 1024 * 1024)
                        throw new IOException("包名、版本号或大小与此应用不兼容");
                    if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("无法创建安装包缓存");
                    // Keep recent installer grants usable across activity restarts.
                    File[] expired = directory.listFiles(file -> file.lastModified() < System.currentTimeMillis() - 7L * 86400000);
                    if (expired != null) for (File file : expired) file.delete();
                    temporary = File.createTempFile("download-", ".apk", directory);
                    output = new FileOutputStream(temporary);
                    digest = MessageDigest.getInstance("SHA-256");
                    received = 0;
                    break;
                case "apk-write":
                    if (output == null || value.length() > 32768) throw new IOException("安装包传输已中断");
                    byte[] bytes = Base64.decode(value, Base64.NO_WRAP);
                    received += bytes.length;
                    if (received > release.getLong("size")) throw new IOException("安装包大小不符");
                    output.write(bytes);
                    digest.update(bytes);
                    break;
                case "apk-finish": confirmInstall(); break;
                case "apk-abort": cancel(); break;
                default: throw new IOException("未知的安装操作");
            }
            return "ok";
        } catch (Exception e) {
            cancel(); return "error:" + e.getMessage();
        }
    }

    private void verify() throws Exception {
        if (output == null) throw new IOException("安装包传输已中断");
        output.close(); output = null;
        String hash = release.getString("sha256");
        if (received != release.getLong("size") || !hash.equals(hex(digest.digest())))
            throw new IOException("安装包内容校验失败");
        PackageInfo candidate = activity.getPackageManager().getPackageArchiveInfo(temporary.getPath(), PackageManager.GET_SIGNING_CERTIFICATES);
        if (candidate == null || candidate.signingInfo == null || candidate.signingInfo.hasMultipleSigners()
            || !activity.getPackageName().equals(candidate.packageName) || !release.getString("version").equals(candidate.versionName)
            || candidate.getLongVersionCode() != release.getLong("version_code"))
            throw new IOException("安装包身份与版本清单不符");
        Signature signer = candidate.signingInfo.getApkContentsSigners()[0];
        Signature current = installed().signingInfo.getApkContentsSigners()[0];
        if (!release.getString("certificate_sha256").equals(hex(MessageDigest.getInstance("SHA-256").digest(signer.toByteArray())))
            || !Arrays.asList(candidate.signingInfo.getSigningCertificateHistory()).contains(current))
            throw new IOException("发布签名与已安装应用不兼容");
    }

    void save(FileExchange files, JsPromptResult result) {
        try {
            verify();
            files.chooseVerified(temporary, "Focus-Mobile-" + release.getString("version") + ".apk", result);
            temporary = null;
        } catch (Exception e) { cancel(); result.confirm("error:" + e.getMessage()); }
    }

    private void confirmInstall() throws Exception {
        verify();
        File ready = new File(directory, release.getString("sha256") + ".apk");
        java.nio.file.Files.move(temporary.toPath(), ready.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        temporary = null;
        new AlertDialog.Builder(activity).setTitle("安装 Focus Mobile " + release.getString("version") + "？")
            .setMessage("已验证 APK 和发布签名。系统安装器将确认覆盖安装。")
            .setNegativeButton("取消", null).setPositiveButton("继续安装", (dialog, which) -> install(ready)).show();
    }

    private void install(File ready) {
        try {
            if (!activity.getPackageManager().canRequestPackageInstalls()) {
                awaitingPermission = ready;
                activity.startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName())), INSTALL_PERMISSION);
                return;
            }
            Uri uri = new Uri.Builder().scheme("content").authority(activity.getPackageName() + ".apk")
                .appendPath(ready.getName()).build();
            Intent intent = new Intent(Intent.ACTION_VIEW).setDataAndType(uri, ApkProvider.MIME)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            intent.setClipData(ClipData.newRawUri("APK", uri));
            activity.startActivity(intent);
        } catch (RuntimeException e) { Views.message(activity, "系统安装器不可用，可选择「另存 APK」后手动安装。"); }
    }

    void permissionResult() {
        File ready = awaitingPermission;
        awaitingPermission = null;
        if (ready != null && activity.getPackageManager().canRequestPackageInstalls()) install(ready);
        else Views.message(activity, "尚未允许安装，可选择「另存 APK」。");
    }

    void cancel() {
        if (output != null) { try { output.close(); } catch (IOException ignored) {} output = null; }
        if (temporary != null) { temporary.delete(); temporary = null; }
        release = null;
    }
}
