package com.neurotrader.pro

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject

object Notifs {
    private const val CH_TRADE = "trades"
    private const val CH_ALERT = "alerts"

    fun init(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_TRADE, "معاملات", NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(NotificationChannel(CH_ALERT, "هشدارها", NotificationManager.IMPORTANCE_HIGH))
    }

    private val titles = mapOf(
        "open" to "معامله باز شد", "close" to "معامله بسته شد", "partial" to "بستن بخشی از پوزیشن",
        "fill" to "سفارش لیمیت اجرا شد", "kill_switch" to "Kill Switch", "learning_brake" to "توقف یادگیری",
        "news" to "خبر مهم", "mt5" to "متاتریدر", "slippage" to "اسلیپیج", "execution_halt" to "توقف معاملات",
        "fatigue" to "فرسودگی استراتژی", "weekly" to "گزارش هفتگی", "model" to "مدل یادگیری",
        "training" to "آموزش هفتگی", "feed" to "قطع داده‌ی قیمت", "news_feed" to "قطع فید اخبار",
    )

    fun shouldNotify(a: JSONObject): Boolean {
        val level = a.optString("level")
        val kind = a.optString("kind")
        return level in setOf("critical", "warning", "trade") || kind in setOf("news", "weekly", "learning_brake", "model")
    }

    fun show(ctx: Context, a: JSONObject) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        val kind = a.optString("kind")
        val critical = a.optString("level") == "critical" || a.optString("level") == "warning"
        val intent = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE
        )
        val msg = a.optString("message")
        val n = NotificationCompat.Builder(ctx, if (critical) CH_ALERT else CH_TRADE)
            .setSmallIcon(android.R.drawable.stat_notify_more)
            .setContentTitle(titles[kind] ?: "نوروترید پرو")
            .setContentText(msg.lineSequence().firstOrNull() ?: msg)
            .setStyle(NotificationCompat.BigTextStyle().bigText(msg))
            .setContentIntent(intent)
            .setAutoCancel(true)
            .setPriority(if (critical) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .build()
        try {
            NotificationManagerCompat.from(ctx).notify(a.optInt("id", (System.currentTimeMillis() % 100000).toInt()), n)
        } catch (_: SecurityException) {
        }
    }
}
