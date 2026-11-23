package org.focus.mobile;

import android.app.Activity;
import android.webkit.*;
import android.widget.FrameLayout;
import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Map;
import org.json.*;

/** Packaged ChatPane for reading before a network document exists. No instance credentials or network access. */
final class SavedConversation {
    static final String ORIGIN="https://conversation.focus.invalid";
    static final String PAGE=ORIGIN+"/conversation.html";
    interface Action { void run(String op,String thread); }
    private final WebView view;
    private final FrameLayout parent;
    private String thread;
    private boolean closed, moved, interacting, unavailable;
    private JSONObject latestPosition;
    private String offered="", landed="";
    SavedConversation(Activity activity,FrameLayout parent,RecordsStore store,ConversationStore conversation,
        String id,String origin,String name,String initial,Action action) {
        this.parent=parent; thread=initial;
        view=new WebView(activity);
        JSONObject appearance = conversation.appearance();
        String scheme = appearance.optString("colorScheme","system");
        int night = activity.getResources().getConfiguration().uiMode & android.content.res.Configuration.UI_MODE_NIGHT_MASK;
        boolean dark = "dark".equals(scheme) || ("system".equals(scheme) && night == android.content.res.Configuration.UI_MODE_NIGHT_YES);
        view.setBackgroundColor(dark ? 0xff0d1117 : android.graphics.Color.WHITE);
        WebSettings settings=view.getSettings();
        settings.setJavaScriptEnabled(true); settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setBlockNetworkLoads(true);
        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r) { return true; }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r) {
                String path=r.getUrl().getPath();
                if(r.getUrl().toString().startsWith(ORIGIN+"/") && path!=null && !path.contains("..") && "GET".equals(r.getMethod())) {
                    try {
                        String mime=path.endsWith(".html")?"text/html":path.endsWith(".js")?"application/javascript":path.endsWith(".css")?"text/css":path.endsWith(".woff2")?"font/woff2":"application/octet-stream";
                        Map<String,String> headers=new HashMap<>();
                        headers.put("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-src 'none'");
                        return new WebResourceResponse(mime,"utf-8",200,"OK",headers,activity.getAssets().open("conversation"+path));
                    } catch(Exception missing) { /* Only packaged resources are eligible. */ }
                }
                return new WebResourceResponse("text/plain","utf-8",404,"Missing",null,new ByteArrayInputStream(new byte[0]));
            }
        });
        view.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onJsPrompt(WebView v,String url,String msg,String value,JsPromptResult result) {
                if(closed || !PAGE.equals(url) || !PAGE.equals(v.getUrl()) || !msg.startsWith("conversation/1/")) { result.cancel(); return true; }
                try {
                    JSONObject data=new JSONObject(value);
                    String op=msg.substring("conversation/1/".length());
                    if(op.equals("init")) result.confirm(new JSONObject().put("thread",thread).put("name",name).put("unavailable",unavailable).put("appearance",appearance).toString());
                    else if(op.equals("interacting")) { interacting=data.getBoolean("active"); result.confirm("ok"); }
                    else if(op.equals("threads")) result.confirm(store.request(true,id,origin,"list",data));
                    else if(op.equals("select")) {
                        String next=data.getString("thread");
                        if(!conversation.available(next)) { result.cancel(); return true; }
                        thread=next; latestPosition=null; moved=false; offered=landed=""; result.confirm("ok"); view.post(() -> { if(!closed) action.run(op,next); });
                    } else if(op.equals("read") && thread.equals(data.getString("thread"))) {
                        JSONObject page=conversation.read(thread,"",data);
                        if(page!=null && "open".equals(data.optString("direction"))) latestPosition=page.getJSONObject("anchor");
                        result.confirm(page==null?"null":page.toString());
                    } else if(op.equals("bookmark") && thread.equals(data.getString("thread"))) {
                        latestPosition=data.getJSONObject("anchor");
                        moved=true;
                        data.put("anchor",latestPosition.toString()).put("now",System.currentTimeMillis());
                        result.confirm(store.request(true,id,origin,"bookmark",data));
                    } else if(op.equals("instances") || op.equals("records") || op.equals("retry")) {
                        result.confirm("ok"); view.post(() -> { if(!closed) action.run(op,thread); });
                    } else result.cancel();
                } catch(Exception invalid) { result.cancel(); }
                return true;
            }
        });
        parent.addView(view,new FrameLayout.LayoutParams(-1,-1)); view.loadUrl(PAGE);
    }
    boolean waitingForPosition(WebView online) {
        if (interacting) return true;
        if(latestPosition==null || (!latestPosition.has("item") && !moved)) return false;
        final String position=latestPosition.toString();
        if(position.equals(landed)) return false;
        if(!position.equals(offered)) {
            offered=position;
            landed="";
            online.evaluateJavascript("!dispatchEvent(new CustomEvent('focus-conversation-position',{cancelable:true,detail:{thread:"
                +JSONObject.quote(thread)+",position:"+JSONObject.quote(position)+"}}))", handled -> {
                    if(!"true".equals(handled)) positioned(position);
                });
        }
        return true;
    }
    void networkFailure() {
        unavailable=true;
        view.evaluateJavascript("dispatchEvent(new Event('focus-instance-unavailable'))",null);
    }
    void networkReachable() {
        if (!unavailable) return;
        unavailable=false;
        view.evaluateJavascript("dispatchEvent(new Event('focus-instance-reachable'))",null);
    }
    void back(Runnable openDrawer) {
        view.evaluateJavascript("!dispatchEvent(new Event('focus-saved-back',{cancelable:true}))", handled -> {
            if (!closed && !"true".equals(handled)) openDrawer.run();
        });
    }
    void reconnect() { offered=landed=""; }
    void positioned(String position) { if(position.equals(offered)) landed=position; }
    boolean hasAccess(ConversationStore store) { return store.available(thread); }
    void close() { closed=true; parent.removeView(view); view.stopLoading(); view.destroy(); }
}
