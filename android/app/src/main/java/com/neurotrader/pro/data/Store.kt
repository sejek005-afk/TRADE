package com.neurotrader.pro.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * ذخیره‌ی امن روی گوشی (رمزنگاری با Android Keystore).
 * فقط آدرس سرور، اثر انگشت گواهی و توکن‌ها اینجا هستند؛ رمز متاتریدر هیچ‌وقت روی گوشی ذخیره نمی‌شود.
 */
class Store(context: Context) {
    private val prefs: SharedPreferences = run {
        val key = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            context, "ntpro_secure", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    var server: String
        get() = prefs.getString("server", "") ?: ""
        set(v) = prefs.edit().putString("server", v).apply()

    var pin: String
        get() = prefs.getString("pin", "") ?: ""
        set(v) = prefs.edit().putString("pin", v).apply()

    var accessToken: String
        get() = prefs.getString("access", "") ?: ""
        set(v) = prefs.edit().putString("access", v).apply()

    var refreshToken: String
        get() = prefs.getString("refresh", "") ?: ""
        set(v) = prefs.edit().putString("refresh", v).apply()

    var lastAlertId: Long
        get() = prefs.getLong("last_alert", 0L)
        set(v) = prefs.edit().putLong("last_alert", v).apply()

    var username: String
        get() = prefs.getString("user", "") ?: ""
        set(v) = prefs.edit().putString("user", v).apply()

    fun clearSession() {
        prefs.edit().remove("access").remove("refresh").apply()
    }

    fun clearAll() {
        prefs.edit().clear().apply()
    }
}
