package org.focus.mobile;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Only a user-confirmed installer receives a temporary read grant to this exact APK. */
public final class ApkProvider extends ContentProvider {
    static final String MIME = "application/vnd.android.package-archive";

    @Override public boolean onCreate() { return true; }

    private File file(Uri uri) {
        String path = uri.getPath();
        if (path == null || !path.matches("/[0-9a-f]{64}\\.apk"))
            throw new IllegalArgumentException("Invalid APK");
        return new File(new File(getContext().getCacheDir(), "mobile-installer"), path.substring(1));
    }

    @Override public String getType(Uri uri) { file(uri); return MIME; }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read only");
        return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        File apk = file(uri);
        String[] columns = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        MatrixCursor result = new MatrixCursor(columns);
        MatrixCursor.RowBuilder row = result.newRow();
        for (String column : columns) {
            if (OpenableColumns.DISPLAY_NAME.equals(column)) row.add("Focus-Mobile.apk");
            else if (OpenableColumns.SIZE.equals(column)) row.add(apk.length());
            else row.add(null);
        }
        return result;
    }

    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException(); }
}
