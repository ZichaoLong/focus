package org.focus.mobile;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.Build;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.*;

/** Bounded reading windows in the same fenced, budgeted archive as the offline reader. */
final class ConversationStore {
    private static final ExecutorService disk = Executors.newSingleThreadExecutor();
    // Accessed only by the disk executor. It outlives a view handoff.
    private static RecordsStore writer;
    private static final int PAGE = 36;
    private final Context context;
    private final RecordsStore store;
    private final String entry, origin, site;

    ConversationStore(Context context, RecordsStore store, String entry, String origin) {
        this.context=context.getApplicationContext(); this.store=store;
        this.entry=entry; this.origin=origin; this.site=entry+"|"+origin;
    }
    private static String digest(String value) throws Exception {
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder out=new StringBuilder(64);
        for(byte b:bytes) { out.append(Character.forDigit((b>>4)&15,16)); out.append(Character.forDigit(b&15,16)); }
        return out.toString();
    }
    private static String scalar(SQLiteDatabase db,String sql,String... args) {
        try(Cursor c=db.rawQuery(sql,args)) { return c.moveToFirst()?c.getString(0):null; }
    }
    private static String key(JSONObject row) {
        return row.optString("item",row.optString("first"));
    }
    private static String coordinate(JSONObject row) {
        return new JSONArray().put(row.optString("turn")).put(key(row)).toString();
    }
    static void index(SQLiteDatabase db,String run,int seq,JSONArray rows) {
        for(int i=0;i<rows.length();i++) {
            JSONObject row=rows.optJSONObject(i);
            if(row!=null && !key(row).isEmpty()) db.execSQL("INSERT OR IGNORE INTO reading_positions VALUES(?,?,?,?)",
                new Object[]{run,row.optString("turn"),key(row),seq});
        }
    }

    // Capture permission at receipt. The queue is process-wide and independent of the Activity or its next selection.
    boolean enqueue(JSONObject page) throws Exception {
        String thread=page.getString("thread"), scope=page.getString("scope"), hash=digest(thread);
        String fence=scalar(store.getReadableDatabase(),"SELECT fence FROM sites WHERE site=? AND enabled AND NOT locked AND scope=? AND length(scope)=64 AND NOT EXISTS(SELECT 1 FROM removed WHERE site=? AND key=?)",site,scope,site,hash);
        if(fence==null) return false;
        disk.execute(() -> {
            try {
                if(writer==null) writer=new RecordsStore(context);
                save(writer,page,hash,fence);
            }
            catch(Exception failure) {
                try { if(writer!=null) writer.call("note",entry,origin,new JSONObject().put("note","paused")); }
                catch(Exception ignored) { /* A full or unavailable disk cannot block reading. */ }
            }
        });
        return true;
    }
    private static ArrayList<JSONObject> fold(JSONArray source) throws Exception {
        ArrayList<JSONObject> rows=new ArrayList<>();
        JSONObject group=null;
        for(int i=source.length()-1;i>=0;i--) {
            JSONObject row=source.getJSONObject(i);
            String kind=row.getString("kind"), turn=row.getString("turn"), item=row.getString("item");
            if(group!=null && (!kind.equals("tool") || !turn.equals(group.getString("turn")))) { rows.add(group); group=null; }
            if(kind.equals("tool")) {
                String previous=group==null?"":group.getString("hash");
                if(group==null) group=new JSONObject().put("kind","tools").put("v",1).put("turn",turn).put("last",item);
                String encoded=new JSONArray().put(1).put(turn).put(item).put(previous).toString().replace("\\/","/");
                group.put("first",item).put("count",group.optInt("count")+1).put("hash",digest(encoded));
            } else if(kind.equals("assistant") || kind.equals("user")) {
                String text=row.getString("text");
                // Each database chunk fits a CursorWindow, including a single very long message.
                ArrayList<String> parts=new ArrayList<>();
                for(int start=0;start<text.length();) {
                    int end=Math.min(start+24000,text.length());
                    if(end<text.length() && Character.isHighSurrogate(text.charAt(end-1))) end--;
                    parts.add(text.substring(start,end)); start=end;
                }
                for(int part=parts.size()-1;part>=0;part--) {
                    JSONObject copy=new JSONObject().put("kind",kind).put("turn",turn).put("item",item)
                        .put("text",parts.get(part)).put("partial",row.optBoolean("partial"));
                    if(row.has("id")) copy.put("id",row.getString("id"));
                    if(parts.size()>1) copy.put("part",part);
                    rows.add(copy);
                }
            }
        }
        if(group!=null) rows.add(group);
        return rows;
    }
    private void save(RecordsStore worker,JSONObject page,String hash,String fence) throws Exception {
        if(page.optBoolean("partial")) {
            JSONObject row=page.getJSONArray("rows").optJSONObject(0);
            if(row==null || !"assistant".equals(row.optString("kind"))) return;
            String thread=page.getString("thread");
            String run=scalar(worker.getReadableDatabase(),"SELECT visible FROM books WHERE site=? AND thread=? AND EXISTS(SELECT 1 FROM sites WHERE site=? AND scope=? AND fence=? AND enabled AND NOT locked)",site,thread,site,page.getString("scope"),fence);
            if(run!=null && !run.isEmpty()) {
                String text=row.optString("text");
                if(text.length()>96000) row.put("text",text.substring(0,96000));
                worker.call("windowlive",entry,origin,new JSONObject().put("thread",thread).put("run",run).put("fence",fence)
                    .put("scope",page.getString("scope")).put("body",new JSONArray().put(row).toString()));
            }
            return;
        }
        ArrayList<JSONObject> rows=fold(page.getJSONArray("rows"));
        if(rows.isEmpty()) return;
        String thread=page.getString("thread"), scope=page.getString("scope"), title=page.optString("title",thread);
        String run=UUID.randomUUID().toString(), first=coordinate(rows.get(rows.size()-1)), last=coordinate(rows.get(0));
        SQLiteDatabase db=worker.getWritableDatabase();
        db.beginTransaction();
        try {
            if(scalar(db,"SELECT 1 FROM sites WHERE site=? AND scope=? AND fence=? AND enabled AND NOT locked AND NOT EXISTS(SELECT 1 FROM removed WHERE site=? AND key=?)",site,scope,fence,site,hash)==null) return;
            if(scalar(db,"SELECT 1 FROM books WHERE site=? AND thread=?",site,thread)==null
                && scalar(db,"SELECT 1 WHERE (SELECT COUNT(*) FROM books WHERE site=?)<1000 AND (SELECT COUNT(*) FROM books)<5000",site)==null) return;
            long now=System.currentTimeMillis();
            db.execSQL("INSERT OR IGNORE INTO books(site,thread,key,title,touched) VALUES(?,?,?,?,?)",new Object[]{site,thread,hash,title,now});
            // Replace overlapping copies of this window and retain only a bounded set of recently read pages.
            db.execSQL("DELETE FROM reading_pages WHERE site=? AND thread=? AND (first=? AND last=? OR run NOT IN (SELECT p.run FROM reading_pages p JOIN runs r USING(run) WHERE p.site=? AND p.thread=? ORDER BY r.stamp DESC,r.rowid DESC LIMIT 11))",new Object[]{site,thread,first,last,site,thread});
            db.execSQL("INSERT INTO runs(site,thread,run,stamp,mark,head) VALUES(?,?,?,?,?,?)",new Object[]{site,thread,run,now,"window",""});
            boolean tail=page.optBoolean("tail");
            db.execSQL("INSERT INTO reading_pages VALUES(?,?,?,?,?,?,?,?)",new Object[]{run,site,thread,tail?1:0,page.optBoolean("older")?1:0,page.optBoolean("newer")?1:0,first,last});
            db.execSQL("UPDATE books SET title=?,live=CASE WHEN ? THEN '' ELSE live END,livebytes=CASE WHEN ? THEN 0 ELSE livebytes END,visible=CASE WHEN visible='' OR (? AND EXISTS(SELECT 1 FROM runs r WHERE r.run=books.visible AND r.mark='window')) THEN ? ELSE visible END WHERE site=? AND thread=?",new Object[]{title,tail?1:0,tail?1:0,tail?1:0,run,site,thread});
            db.execSQL("DELETE FROM runs WHERE site=? AND thread=? AND mark='window' AND run NOT IN (SELECT run FROM reading_pages WHERE site=? AND thread=?) AND run NOT IN (SELECT visible FROM books WHERE site=? AND thread=?)",new Object[]{site,thread,site,thread,site,thread});
            long bytes=0; int seq=0, chars=0;
            JSONArray batch=new JSONArray();
            for(int i=0;i<=rows.size();i++) {
                JSONObject row=i<rows.size()?rows.get(i):null;
                int size=row==null?0:row.toString().length();
                if(batch.length()>0 && (row==null || chars+size>64000)) {
                    String body=batch.toString();
                    bytes+=body.getBytes(StandardCharsets.UTF_8).length;
                    db.execSQL("INSERT INTO chunks VALUES(?,?,?)",new Object[]{run,seq,body});
                    index(db,run,seq++,batch); batch=new JSONArray(); chars=0;
                }
                if(row!=null) { batch.put(row); chars+=size; }
            }
            db.execSQL("UPDATE runs SET bytes=?,seq=? WHERE run=?",new Object[]{bytes,seq,run});
            if(scalar(db,"SELECT 1 WHERE (SELECT SUM(r.bytes) FROM runs r JOIN reading_pages p USING(run) WHERE p.site=? AND p.thread=?)<=16777216 AND (SELECT SUM(bytes) FROM runs WHERE site=?)+(SELECT COALESCE(SUM(livebytes),0) FROM books WHERE site=?)<=67108864 AND (SELECT SUM(bytes) FROM runs)+(SELECT COALESCE(SUM(livebytes),0) FROM books)<=201326592",site,thread,site,site)==null)
                throw new IllegalStateException("record budget");
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    boolean available(String thread) {
        if (thread.isEmpty()) return false;
        try {
            return scalar(store.getReadableDatabase(),
                "SELECT 1 FROM books b JOIN sites s USING(site) JOIN runs r ON b.visible=r.run WHERE b.site=? AND b.thread=? AND r.seq>0 AND NOT s.locked AND length(s.scope)=64",site,thread)!=null;
        } catch (android.database.SQLException unavailable) {
            return false;
        }
    }

    JSONObject read(String thread,String scope,JSONObject request) throws Exception {
        SQLiteDatabase db=store.getReadableDatabase();
        // All statements in this read must see one publication, including a concurrent cleanup or lock.
        if (Build.VERSION.SDK_INT >= 35) db.beginTransactionReadOnly();
        else db.beginTransactionNonExclusive();
        try {
            String direction=request.optString("direction","open");
            boolean open="open".equals(direction);
            try(Cursor b=db.rawQuery("SELECT b.visible,b.title,b.anchor,b.live FROM books b JOIN sites s USING(site) WHERE b.site=? AND b.thread=? AND NOT s.locked AND length(s.scope)=64 AND (?='' OR s.scope=?)",new String[]{site,thread,scope,scope})) {
                if(!b.moveToFirst()) return null;
                String visible=b.getString(0);
                JSONObject anchor=b.getString(2).isEmpty()?new JSONObject():new JSONObject(b.getString(2));
                String turn=request.optString("turn",open?anchor.optString("turn"):"");
                String item=request.optString("item",open?anchor.optString("item"):"");
                try(Cursor runs=db.rawQuery("SELECT r.run,r.seq,r.complete,r.edge,p.tail,p.older,p.newer FROM runs r LEFT JOIN reading_pages p USING(run) WHERE r.site=? AND r.thread=? AND r.seq>0 AND (r.run=? OR p.run IS NOT NULL) ORDER BY r.stamp DESC,r.rowid DESC",new String[]{site,thread,visible})) {
                    // Prefer the saved reading position, then the freshest tail if it has disappeared.
                    for(int attempt=0;attempt<(open&&!item.isEmpty()?2:1);attempt++) {
                        runs.moveToPosition(-1);
                        String target=attempt==0?item:"";
                        while(runs.moveToNext()) {
                            String run=runs.getString(0);
                            boolean archive=runs.isNull(4);
                            boolean tail=archive || runs.getInt(4)!=0;
                            if(target.isEmpty() && !tail) continue;
                            // A partial reply belongs to the current tail even when the archive and the
                            // most recently opened reading window have different run ids.
                            JSONObject result=readRun(db,run,runs.getInt(1),runs.getString(3),tail?b.getString(3):"",
                                archive?runs.getInt(2)==0:runs.getInt(5)!=0,!archive&&runs.getInt(6)!=0,turn,target,direction);
                            if(result==null) continue;
                            if(open && !target.isEmpty()) {
                                JSONObject before=readRun(db,run,runs.getInt(1),runs.getString(3),"",
                                    archive?runs.getInt(2)==0:runs.getInt(5)!=0,false,turn,target,"older");
                                if(before!=null) {
                                    JSONArray prefix=before.getJSONArray("rows"), body=result.getJSONArray("rows"), joined=new JSONArray();
                                    int start=Math.max(0,prefix.length()-10);
                                    for(int i=start;i<prefix.length();i++) joined.put(prefix.get(i));
                                    for(int i=0;i<body.length();i++) joined.put(body.get(i));
                                    result.put("rows",joined).put("older",before.getBoolean("older") || start>0);
                                } else result.put("older",archive?runs.getInt(2)==0:runs.getInt(5)!=0);
                            }
                            return result.put("thread",thread).put("title",b.getString(1)).put("anchor",anchor);
                        }
                    }
                }
            }
            return null;
        } finally { db.endTransaction(); }
    }

    private static JSONObject readRun(SQLiteDatabase db,String run,int count,String edge,String live,boolean olderGap,
        boolean newerGap,String turn,String item,String direction) throws Exception {
        boolean open=direction.equals("open"), forward=direction.equals("newer") || open&&!item.isEmpty();
        int seq=0;
        if(!item.isEmpty()) {
            String pos=scalar(db,"SELECT seq FROM reading_positions WHERE run=? AND turn=? AND item=? ORDER BY seq "+(forward?"DESC":"ASC")+" LIMIT 1",run,turn,item);
            // Existing editions predate the lookup index. Search just their chunks and verify the exact pair below.
            if(pos==null && scalar(db,"SELECT 1 FROM reading_positions WHERE run=? LIMIT 1",run)==null) pos=scalar(db,"SELECT seq FROM chunks WHERE run=? AND instr(body,?)>0 AND instr(body,?)>0 ORDER BY seq LIMIT 1",run,JSONObject.quote(item),JSONObject.quote(turn));
            if(pos==null && !edge.contains(JSONObject.quote(item)) && !live.contains(JSONObject.quote(item))) return null;
            seq=pos!=null?Integer.parseInt(pos):edge.contains(JSONObject.quote(item))?count-1:0;
        }
        ArrayList<JSONObject> rows=new ArrayList<>();
        boolean found=item.isEmpty(), remains=false;
        int size=0;
        for(;seq>=0&&seq<count;seq+=forward?-1:1) {
            String body=scalar(db,"SELECT body FROM chunks WHERE run=? AND seq=?",run,Integer.toString(seq));
            if(body==null) break;
            JSONArray chunk=new JSONArray(body);
            if(seq==count-1 && !edge.isEmpty()) chunk.put(new JSONObject(edge));
            if(seq==0 && !live.isEmpty()) {
                JSONArray updates=new JSONArray(live);
                for(int n=0;n<updates.length();n++) {
                    JSONObject update=updates.getJSONObject(n);
                    boolean replaced=false;
                    for(int j=0;j<chunk.length();j++) {
                        JSONObject saved=chunk.getJSONObject(j);
                        if(key(saved).equals(key(update)) && saved.optString("turn").equals(update.optString("turn"))) { chunk.put(j,update); replaced=true; break; }
                    }
                    if(!replaced) { JSONArray joined=new JSONArray().put(update); for(int j=0;j<chunk.length();j++) joined.put(chunk.get(j)); chunk=joined; }
                }
            }
            for(int i=0;i<chunk.length();i++) {
                JSONObject row=chunk.getJSONObject(forward?chunk.length()-1-i:i);
                if(!found) {
                    if(!turn.equals(row.optString("turn")) || !item.equals(key(row))) continue;
                    found=true; if(!open) continue;
                }
                if(!open && item.equals(key(row)) && turn.equals(row.optString("turn"))) continue;
                JSONObject previous=rows.isEmpty()?null:rows.get(rows.size()-1);
                if(previous!=null && row.has("part") && previous.has("part") && key(previous).equals(key(row)) && previous.optString("turn").equals(row.optString("turn"))) {
                    previous.put("text",forward?previous.optString("text")+row.optString("text"):row.optString("text")+previous.optString("text"));
                    size+=row.optString("text").length();
                    continue;
                }
                if(rows.size()>=PAGE || size>=120000) { remains=true; break; }
                rows.add(row); size+=row.optString("text").length();
            }
            if(remains) break;
        }
        if(rows.isEmpty()) return null;
        if(!forward) Collections.reverse(rows);
        return new JSONObject().put("rows",new JSONArray(rows))
            .put("older",forward?!item.isEmpty() || olderGap:remains || olderGap)
            .put("newer",forward?remains || newerGap:!item.isEmpty() || newerGap);
    }
}
