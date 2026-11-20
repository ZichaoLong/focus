-keep class org.focus.mobile.** extends android.app.Activity { *; }
-keep class org.focus.mobile.** extends android.app.Service { *; }
-keep class org.focus.mobile.ApkProvider extends android.content.ContentProvider { *; }

# Compile-only annotations and the unused WebViewAssetLoader builder.
-dontwarn androidx.annotation.**
-dontwarn androidx.core.util.Pair
