package org.focus.mobile;

import android.content.*;
import android.security.keystore.*;
import android.util.Base64;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

// The ciphertext is useless without this non-exportable, per-install Keystore key.
final class BasicVault {
    private static final String ALIAS = "org.focus.mobile.basic.v1";
    private static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore"); ks.load(null);
        if (ks.containsAlias(ALIAS)) return (SecretKey) ks.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance("AES", "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }

    private static AtomicFile record(Context ctx, String id) {
        return new AtomicFile(new File(ctx.getNoBackupFilesDir(), "basic-" + id));
    }

    static JSONObject read(Context ctx, String id, String origin, String realm) throws Exception {
        JSONObject entry = open(record(ctx, id), id);
        return entry != null && origin.equals(entry.getString("origin")) && realm.equals(entry.getString("realm")) ? entry : null;
    }

    static JSONObject open(AtomicFile file, String binding) throws Exception {
        if (!file.getBaseFile().exists()) return null;
        JSONObject box = new JSONObject(new String(file.readFully(), StandardCharsets.UTF_8));
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(box.getString("iv"), 0)));
        cipher.updateAAD(binding.getBytes(StandardCharsets.UTF_8));
        return new JSONObject(new String(cipher.doFinal(Base64.decode(box.getString("data"), 0)), StandardCharsets.UTF_8));
    }

    static void store(Context ctx, String id, JSONObject entry) throws Exception {
        seal(record(ctx, id), id, entry);
    }

    static void seal(AtomicFile file, String binding, JSONObject entry) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD(binding.getBytes(StandardCharsets.UTF_8));
        JSONObject box = new JSONObject().put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
            .put("data", Base64.encodeToString(cipher.doFinal(entry.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP));
        FileOutputStream stream = file.startWrite();
        try {
            stream.write(box.toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(stream);
        } catch (Exception error) {
            file.failWrite(stream);
            throw error;
        }
    }

    static void erase(Context ctx, String id) { record(ctx, id).delete(); }
}
