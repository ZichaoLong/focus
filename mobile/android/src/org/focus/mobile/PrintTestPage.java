package org.focus.mobile;

import android.content.Context;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.print.PageRange;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintDocumentInfo;
import android.print.pdf.PrintedPdfDocument;
import java.io.IOException;
import java.io.OutputStream;

/** One fixed page for comparing system printing with the conversation WebView. */
final class PrintTestPage extends PrintDocumentAdapter {
    private final Context context;
    private PrintAttributes attributes;

    PrintTestPage(Context context) { this.context = context; }

    @Override public void onLayout(PrintAttributes previous, PrintAttributes next, CancellationSignal cancel,
            LayoutResultCallback callback, Bundle extras) {
        if (cancel.isCanceled()) { callback.onLayoutCancelled(); return; }
        attributes = next;
        PrintDocumentInfo info = new PrintDocumentInfo.Builder("focus-print-test.pdf")
            .setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT).setPageCount(1).build();
        callback.onLayoutFinished(info, !next.equals(previous));
    }

    @Override public void onWrite(PageRange[] pages, ParcelFileDescriptor destination, CancellationSignal cancel,
            WriteResultCallback callback) {
        PrintAttributes layout = attributes;
        new Thread(() -> {
            boolean requested = false;
            for (PageRange range : pages) if (range.getStart() == 0) requested = true;
            try (OutputStream output = new ParcelFileDescriptor.AutoCloseOutputStream(destination)) {
                if (requested && layout != null && !cancel.isCanceled()) {
                    PrintedPdfDocument pdf = new PrintedPdfDocument(context, layout);
                    try {
                        PdfDocument.Page page = pdf.startPage(0);
                        try {
                            Paint ink = new Paint(Paint.ANTI_ALIAS_FLAG);
                            ink.setTextSize(16);
                            page.getCanvas().drawText("Focus Mobile print test", 12, 28, ink);
                        } finally { pdf.finishPage(page); }
                        pdf.writeTo(output);
                    } finally { pdf.close(); }
                }
            } catch (IOException | RuntimeException failure) {
                if (cancel.isCanceled()) callback.onWriteCancelled(); else callback.onWriteFailed(null);
                return;
            }
            if (cancel.isCanceled()) callback.onWriteCancelled();
            else if (!requested || layout == null) callback.onWriteFailed(null);
            else callback.onWriteFinished(new PageRange[]{new PageRange(0, 0)});
        }, "focus-print-test").start();
    }
}
