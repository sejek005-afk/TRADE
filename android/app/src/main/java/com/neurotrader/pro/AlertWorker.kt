package com.neurotrader.pro

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.neurotrader.pro.data.Api
import com.neurotrader.pro.data.Store
import java.util.concurrent.TimeUnit

/**
 * وقتی اپ بسته است، هر ۱۵ دقیقه هشدارهای جدید را از سرور می‌گیرد و نوتیفیکیشن می‌دهد.
 * (به FCM وابسته نیست، چون FCM در ایران همیشه پایدار نیست. ایمیل هم از سمت سرور ارسال می‌شود.)
 */
class AlertWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val store = Store(applicationContext)
        if (store.server.isEmpty() || store.refreshToken.isEmpty() || store.pin.isEmpty()) return Result.success()
        val api = Api(store)
        return try {
            if (!api.refresh()) return Result.success()
            val arr = api.arr("/api/alerts?after=${store.lastAlertId}")
            var maxId = store.lastAlertId
            for (i in arr.length() - 1 downTo 0) {
                val a = arr.getJSONObject(i)
                val id = a.optLong("id")
                if (id > maxId) maxId = id
                if (Notifs.shouldNotify(a)) Notifs.show(applicationContext, a)
            }
            store.lastAlertId = maxId
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }

    companion object {
        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<AlertWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("ntpro_alerts", ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }
}
