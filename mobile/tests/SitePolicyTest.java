package org.focus.mobile;

public final class SitePolicyTest {
    private static void expect(boolean value) {
        if (!value) throw new AssertionError();
    }

    public static void main(String[] args) {
        String origin = Site.entry("https://FOCUS.example:443/");
        expect(origin.equals("https://focus.example"));
        expect(Site.sameOrigin("https://focus.example/api/meta", origin));
        expect(!Site.sameOrigin("https://focus.example:8443/", origin));
        expect(!Site.sameOrigin("https://focus.example.other/", origin));
        expect(!Site.sameOrigin("https://focus.example@other.example/", origin));
        expect(!Site.sameOrigin("http://focus.example/", origin));
        expect(!Site.root("https://focus.example/preview", origin));
        expect(Site.root("https://focus.example/?thread=t", origin));
        expect(Site.entry("http://[::1]:8123").equals("http://[::1]:8123"));
        expect(Site.httpsPage("https://example.org:8443/article?q=read#section"));
        expect(!Site.httpsPage("https://user:pass@example.org/"));
        expect(!Site.httpsPage("file:///data/local"));
        expect(!Site.httpsPage("http://localhost/article"));
        for (String url : new String[]{"http://10.0.0.1", "http://localhost.example", "http://127.0.0.1@other",
                                      "https://focus.example/path", "https://focus.example/#token=example"}) {
            try { Site.entry(url); throw new AssertionError(url); }
            catch (IllegalArgumentException expected) { }
        }
        expect(Site.basicRealm("Basic realm=\"Focus\", charset=\"UTF-8\"", "Focus"));
        expect(Site.basicRealm("basic realm=\"a\\\"b\"", "a\"b"));
        expect(!Site.basicRealm("Basic realm=\"Focus\"", "focus"));
        expect(!Site.basicRealm("Digest realm=\"Focus\"", "Focus"));
        expect(!Site.basicRealm("Basic realm=\"other\", Basic realm=\"Focus\"", "Focus"));
        System.out.println("Entry and Basic challenge policy passed");
    }
}
