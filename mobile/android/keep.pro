-keep class org.focus.mobile.** extends android.app.Activity { *; }
-keep class org.focus.mobile.** extends android.app.Service { *; }

# Compile-only annotations and the unused WebViewAssetLoader builder.
-dontwarn androidx.annotation.**
-dontwarn androidx.core.util.Pair
