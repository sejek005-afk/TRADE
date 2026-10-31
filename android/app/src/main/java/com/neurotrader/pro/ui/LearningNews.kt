package com.neurotrader.pro.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neurotrader.pro.AppVM
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

private val tehranFmt = SimpleDateFormat("MM/dd HH:mm", Locale.US).apply { timeZone = TimeZone.getTimeZone("Asia/Tehran") }
fun tehran(ts: Long): String = if (ts <= 0) "-" else tehranFmt.format(Date(ts * 1000))

@Composable
fun LearningScreen(vm: AppVM) {
    LaunchedEffect(Unit) { vm.load("learning", "/api/learning") }
    val l = vm.data["learning"] as? JSONObject
    val reload: () -> Unit = { vm.load("learning", "/api/learning") }
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { Header(vm, "یادگیری") }
        if (l == null) {
            item { Section("") { Muted("در حال بارگذاری…") } }
            return@LazyColumn
        }
        val fa = l.o("strategies_fa")
        val paused = l.o("paused")
        item {
            Section("وضعیت") {
                StatusRow("یادگیری", !paused.optBoolean("paused"), if (paused.optBoolean("paused")) paused.s("reason") else "فعال")
                StatusRow("آموزش هفتگی", true, if (l.o("training").optBoolean("running")) "در حال اجرا…" else "شنبه‌ها (بازار تعطیل)")
                KV("مدل فعلی (Champion)", if (l.isNull("champion")) "هنوز ندارد (فقط استراتژی‌ها)" else "#${l.optInt("champion")}")
                KV("مدل Shadow (Challenger)", if (l.isNull("challenger")) "-" else "#${l.optInt("challenger")} از ${tehran(l.optLong("challenger_since"))}")
                KV("شبکه‌ی عصبی", if (l.optBoolean("nn_active")) "فعال" else "غیرفعال (از LightGBM بهتر نبوده)")
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (paused.optBoolean("paused"))
                        OutlinedButton(onClick = { vm.action("/api/learning/resume", ok = "یادگیری فعال شد", after = reload) }) { Text("شروع یادگیری") }
                    else
                        OutlinedButton(onClick = { vm.action("/api/learning/pause", ok = "یادگیری متوقف شد", after = reload) }) { Text("توقف یادگیری") }
                    OutlinedButton(onClick = { vm.action("/api/learning/rollback", ok = "وزن‌ها برگشت داده شد", after = reload) }) { Text("Rollback وزن‌ها") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.action("/api/learning/model_rollback", ok = "مدل قبلی فعال شد", after = reload) }) { Text("Rollback مدل") }
                    OutlinedButton(onClick = { vm.action("/api/learning/train", ok = "آموزش شروع شد", after = reload) }) { Text("آموزش الان") }
                }
            }
        }
        val suspended = l.o("suspended")
        val sk = suspended.keys().asSequence().toList()
        if (sk.isNotEmpty()) item {
            Section("استراتژی‌های معلق (فرسودگی)") {
                sk.forEach { s ->
                    val v = suspended.o(s)
                    KV(fa.s(s, s), "اخیر ${v.d("recent").signed()}R در برابر سابقه ${v.d("history").signed()}R", C.amber)
                    OutlinedButton(onClick = { vm.action("/api/strategies/$s/reinstate", ok = "دوباره فعال شد", after = reload) }) { Text("فعال‌سازی دوباره") }
                }
            }
        }
        val weights = l.a("weights").objects().groupBy { it.s("bucket") }
        item { Section("وزن استراتژی‌ها در هر وضعیت بازار + سشن") { if (weights.isEmpty()) Muted("هنوز معامله‌ای برای یادگیری ثبت نشده؛ همه‌ی وزن‌ها ۱.۰ هستند") } }
        items(weights.keys.toList()) { b ->
            val parts = b.split("|")
            Section("${REGIME_FA[parts.getOrNull(0)] ?: parts.getOrNull(0)} • ${SESSION_FA[parts.getOrNull(1)] ?: parts.getOrNull(1)}") {
                weights[b]!!.sortedByDescending { it.d("weight") }.forEach { w ->
                    val wt = w.d("weight")
                    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                        Text(fa.s(w.s("strategy"), w.s("strategy")), color = C.text, fontSize = 12.sp, modifier = Modifier.weight(1f))
                        Text("${wt.f(2)} (${w.optInt("n_raw")} معامله)", color = if (wt > 1) C.green else if (wt < 1) C.red else C.muted, fontSize = 12.sp)
                    }
                    LinearProgressIndicator(progress = { (wt / 2.0).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                }
            }
        }
        val probs = l.a("recent_probs").objects()
        if (probs.isNotEmpty()) item {
            Section("احتمال مدل‌ها برای سیگنال‌های اخیر") {
                probs.take(20).forEach { p ->
                    KV("${tehran(p.optLong("time"))} ${p.s("symbol")} ${dirFa(p.optInt("direction"))}",
                        listOfNotNull(
                            if (!p.isNull("ml_prob")) "ترکیبی ${(p.d("ml_prob") * 100).f(0)}٪" else null,
                            if (!p.isNull("nn_prob")) "عصبی ${(p.d("nn_prob") * 100).f(0)}٪" else null,
                            if (!p.isNull("shadow_prob")) "Shadow ${(p.d("shadow_prob") * 100).f(0)}٪" else null,
                        ).joinToString(" | "))
                }
            }
        }
        val models = l.a("models").objects()
        if (models.isNotEmpty()) item {
            Section("نسخه‌های مدل") {
                models.forEach { m ->
                    val wf = m.o("metrics").o("walk_forward")
                    val best = if (m.o("metrics").optBoolean("nn_active")) wf.o("ens") else wf.o("gbm")
                    KV("#${m.optInt("id")} v${m.optInt("version")} — ${m.s("status")}",
                        "AUC ${best.d("auc").f(3)} • PF ${best.d("pf").f(2)} • Exp ${best.d("exp").signed()}R")
                }
            }
        }
        val log = l.a("log").objects()
        item {
            Section("تاریخچه‌ی تغییرات وزن") {
                if (log.isEmpty()) Muted("تغییری ثبت نشده")
                log.take(60).forEach { e ->
                    Muted("${tehran(e.optLong("time"))} • ${fa.s(e.s("strategy"), e.s("strategy"))} [${e.s("bucket")}] " +
                            "${e.d("old").f(2)} → ${e.d("new").f(2)} • ${e.s("reason")}")
                }
            }
        }
    }
}

@Composable
fun NewsScreen(vm: AppVM) {
    var tab by rememberSaveable { mutableStateOf("news") }
    LaunchedEffect(tab) {
        if (tab == "news") vm.load("news", "[/api/news?limit=150") else vm.load("calendar", "/api/calendar")
    }
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { Header(vm, "اخبار") }
        item {
            Row(Modifier.padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(tab == "news", { tab = "news" }, label = { Text("فید اخبار") })
                FilterChip(tab == "cal", { tab = "cal" }, label = { Text("تقویم اقتصادی") })
            }
        }
        if (tab == "news") {
            val list = (vm.data["news"] as? JSONArray)?.objects() ?: emptyList()
            if (list.isEmpty()) item { Section("") { Muted("خبری دریافت نشده (کلید Finnhub را در تنظیمات وارد کنید یا منتظر RSS بمانید)") } }
            items(list) { n ->
                Section("") {
                    Text(n.s("headline"), color = C.text, fontSize = 13.sp, fontWeight = if (n.s("impact") == "high") FontWeight.Bold else FontWeight.Normal)
                    Spacer(Modifier.height(4.dp))
                    val eff = n.o("effects")
                    val tags = eff.keys().asSequence().map { k ->
                        val v = eff.d(k)
                        "$k: " + (if (v > 0.2) "مثبت" else if (v < -0.2) "منفی" else "خنثی")
                    }.joinToString("  •  ")
                    Muted("${n.s("time_tehran")} • ${n.s("source")}")
                    if (tags.isNotEmpty()) Text(tags, color = C.blue, fontSize = 12.sp)
                }
            }
        } else {
            val cal = vm.data["calendar"] as? JSONObject
            val evs = cal?.a("events")?.objects() ?: emptyList()
            item { Section("") { Muted("منبع: ${cal?.s("source") ?: "-"} — زمان‌ها به وقت تهران") } }
            items(evs) { e ->
                Section("") {
                    Row {
                        Text(e.s("currency"), color = if (e.optBoolean("high")) C.red else C.amber, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                        Text("  ${e.s("title")}", color = C.text, fontSize = 13.sp)
                    }
                    Muted("${e.s("time_tehran")} • پیش‌بینی ${e.s("forecast", "-")} • قبلی ${e.s("previous", "-")}" +
                            (if (e.s("actual").isNotEmpty()) " • واقعی ${e.s("actual")}" else ""))
                }
            }
        }
    }
}
