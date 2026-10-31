package com.neurotrader.pro.data

import android.util.Base64
import okhttp3.OkHttpClient
import okhttp3.Request
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** SHA-256 کلید عمومی (SPKI) به Base64 — همان چیزی که موتور در FINGERPRINT.txt چاپ می‌کند. */
fun spkiFingerprint(cert: X509Certificate): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(cert.publicKey.encoded)
    return Base64.encodeToString(digest, Base64.NO_WRAP)
}

/**
 * اعتماد فقط به گواهی‌ای که اثر انگشتش با Pin ذخیره‌شده یکی است.
 * اگر pin خالی باشد (فقط برای مرحله‌ی اول اتصال)، گواهی پذیرفته و اثر انگشتش ثبت می‌شود تا کاربر تأیید کند.
 */
class PinTrustManager(private val pin: String) : X509TrustManager {
    @Volatile var seen: String = ""
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw CertificateException("client auth not supported")
    }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull() ?: throw CertificateException("no certificate")
        val fp = spkiFingerprint(leaf)
        seen = fp
        if (pin.isNotEmpty() && fp != pin) throw CertificateException("اثر انگشت گواهی سرور تغییر کرده است")
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

object Net {
    fun client(pin: String, readTimeoutSec: Long = 20): Pair<OkHttpClient, PinTrustManager> {
        val tm = PinTrustManager(pin)
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(tm), null)
        val c = OkHttpClient.Builder()
            .sslSocketFactory(ctx.socketFactory, tm)
            // گواهی خودامضا با IP سرور مطابقت ندارد؛ امنیت با Pin کلید عمومی در PinTrustManager تأمین می‌شود
            // (اگر اثر انگشت مطابقت نداشته باشد، اتصال قبل از این مرحله قطع شده است)
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(12, TimeUnit.SECONDS)
            .readTimeout(readTimeoutSec, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
        return c to tm
    }

    /** اولین اتصال: گرفتن اثر انگشت گواهی سرور برای نمایش به کاربر. */
    fun fetchFingerprint(baseUrl: String): Result<String> = runCatching {
        val (c, tm) = client("", 10)
        c.newCall(Request.Builder().url("$baseUrl/api/ping").build()).execute().use { r ->
            if (!r.isSuccessful) error("HTTP ${r.code}")
        }
        tm.seen.ifEmpty { error("گواهی دریافت نشد") }
    }
}
