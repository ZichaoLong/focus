package org.focus.mobile;

import java.net.URI;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class Site {
    private static final Pattern BASIC = Pattern.compile(
        "^Basic\\s+realm=(?:\"((?:[^\"\\\\]|\\\\.)*)\"|([^\\s,]+))(?:\\s*,\\s*charset=\"?UTF-8\"?)?\\s*$",
        Pattern.CASE_INSENSITIVE);

    static String origin(String input) {
        URI uri = URI.create(input.trim());
        String host = uri.getHost();
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        boolean local = scheme.equals("http") && ("localhost".equalsIgnoreCase(host) || "127.0.0.1".equals(host) || "[::1]".equals(host));
        if ((!scheme.equals("https") && !local) || host == null || uri.getRawUserInfo() != null
                || uri.getPort() == 0 || uri.getPort() > 65535) throw new IllegalArgumentException("远程入口需要 HTTPS；HTTP 仅支持本机回环地址");
        int defaultPort = local ? 80 : 443;
        return scheme + "://" + host.toLowerCase(Locale.ROOT) + (uri.getPort() < 0 || uri.getPort() == defaultPort ? "" : ":" + uri.getPort());
    }

    static String entry(String input) {
        URI uri = URI.create(input.trim());
        String path = uri.getRawPath();
        if (path != null && !path.isEmpty() && !path.equals("/") || uri.getRawQuery() != null || uri.getRawFragment() != null)
            throw new IllegalArgumentException("请输入站点根地址，授权链接请单独打开");
        return origin(input);
    }

    static boolean sameOrigin(String url, String origin) {
        try { return origin(url).equals(origin); } catch (RuntimeException e) { return false; }
    }

    static boolean httpsPage(String url) {
        try { return origin(url).startsWith("https://"); }
        catch (RuntimeException invalid) { return false; }
    }

    static boolean root(String url, String origin) {
        return url != null && sameOrigin(url, origin) && "/".equals(URI.create(url).getRawPath());
    }

    static boolean verifyBasic(String origin, String realm) throws java.io.IOException {
        javax.net.ssl.HttpsURLConnection conn = (javax.net.ssl.HttpsURLConnection)
            URI.create(origin + "/focus-connect.txt").toURL().openConnection();
        try {
            conn.setInstanceFollowRedirects(false); conn.setUseCaches(false);
            conn.setConnectTimeout(5000); conn.setReadTimeout(5000);
            int status = conn.getResponseCode();
            if (status >= 500 || status == 408 || status == 429) throw new java.io.IOException("入口暂不可达");
            return status == 401 && basicRealm(conn.getHeaderField("WWW-Authenticate"), realm);
        } finally { conn.disconnect(); }
    }

    static boolean basicRealm(String header, String realm) {
        if (header == null || realm == null || realm.length() > 512) return false;
        Matcher m = BASIC.matcher(header.trim());
        if (!m.matches()) return false;
        String value = m.group(1) == null ? m.group(2) : m.group(1).replaceAll("\\\\(.)", "$1");
        return realm.equals(value);
    }
}
