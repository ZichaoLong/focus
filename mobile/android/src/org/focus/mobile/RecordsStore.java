package org.focus.mobile;

import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.*;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Scanner;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Private, cross-process SQLite store. Only packaged statement names are executable. */
final class RecordsStore extends SQLiteOpenHelper {
    private static final Pattern PARAM = Pattern.compile(":([a-z]+)");
    private static final String LIVE = " auth lock revoke note touch capture checkpoint start write finish live bookmark closed revert allow ";
    private static final String LOCAL = " status enable list book chunk bookmark touch candidates cleanselected allow ";
    private final JSONObject commands;

    RecordsStore(Context context) {
        super(context, "offline-records-v1.db", null, 1);
        try (InputStream input = context.getAssets().open("records-sql.json");
             Scanner scanner = new Scanner(input, "UTF-8").useDelimiter("\\A")) {
            commands = new JSONObject(scanner.next());
        } catch (Exception failure) { throw new IllegalStateException("记录格式不可用", failure); }
    }

    @Override public void onConfigure(SQLiteDatabase db) {
        try (Cursor setting=db.rawQuery("PRAGMA secure_delete=ON",null)) { setting.moveToFirst(); }
    }
    @Override public void onCreate(SQLiteDatabase db) {
        JSONArray schema = commands.optJSONArray("schema");
        for (int i = 0; i < schema.length(); i++) db.execSQL(schema.optString(i));
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        throw new IllegalStateException("不支持的记录版本");
    }

    private void run(SQLiteDatabase db, String op, JSONObject data, JSONArray rows) throws JSONException {
        JSONArray steps = commands.getJSONArray(op);
        for (int i = 0; i < steps.length(); i++) {
            String template = steps.getString(i);
            if (template.startsWith("@")) { run(db, template.substring(1), data, rows); continue; }
            boolean guard = template.startsWith("!"), read = template.startsWith("?");
            Matcher matcher = PARAM.matcher(guard || read ? template.substring(1) : template);
            ArrayList<String> args = new ArrayList<>();
            StringBuffer sql = new StringBuffer();
            while (matcher.find()) {
                args.add(data.getString(matcher.group(1))); matcher.appendReplacement(sql, "?");
            }
            matcher.appendTail(sql);
            String[] bindings = args.toArray(new String[0]);
            if (!guard && !read) { db.execSQL(sql.toString(), bindings); continue; }
            try (Cursor cursor = db.rawQuery(sql.toString(), bindings)) {
                if (guard && !cursor.moveToFirst()) throw new IllegalStateException("记录已变更或空间已满");
                while (read && cursor.moveToNext()) {
                    JSONObject row = new JSONObject();
                    for (int j = 0; j < cursor.getColumnCount(); j++)
                        row.put(cursor.getColumnName(j), cursor.getString(j));
                    rows.put(row);
                }
            }
        }
    }

    String call(String op, String site, String origin, JSONObject data) throws JSONException {
        data.put("site", site + "|" + origin);
        SQLiteDatabase db = getWritableDatabase();
        JSONArray rows = new JSONArray();
        db.beginTransaction();
        try {
            run(db, op, data, rows);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        return rows.toString();
    }

    String request(boolean local, String site, String origin, String op, JSONObject data) throws JSONException {
        if (!op.matches("[a-z]+") || !(local ? LOCAL : LIVE).contains(" " + op + " "))
            throw new IllegalArgumentException("未知记录操作");
        return call(op, site, origin, data);
    }
}
