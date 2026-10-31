package com.neurotrader.pro.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neurotrader.pro.AppVM
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject

private val PAGES = listOf(
    "settings" to "تنظیمات ریسک، ساعات، نمادها و استراتژی‌ها",
    "mt5" to "حساب متاتریدر",
    "health" to "وضعیت سلامت (پینگ، اسلیپیج، اتصال)",
    "reports" to "گزارش هفتگی و ژورنال",
    "backtest" to "بک‌تست",
    "logs" to "لاگ زنده‌ی موتور",
    "alerts" to "هشدارها",
    "versions" to "تاریخچه‌ی تنظیمات",
    "account" to "خروج و امنیت",
)

@Composable
fun MoreScreen(vm: AppVM, sub: String, go: (String) -> Unit) {
    when (sub) {
        "settings" -> SettingsScreen(vm, go)
        "mt5" -> Mt5Screen(vm, go)
        "health" -> HealthScreen(vm, go)
        "reports" -> ReportsScreen(vm, go)
        "backtest" -> BacktestScreen(vm, go)
        "logs" -> LogsScreen(vm, go)
        "alerts" -> AlertsScreen(vm, go)
        "versions" -> VersionsScreen(vm, go)
        "account" -> AccountScreen(vm, go)
        else -> LazyColumn {
            item { Header(vm, "بیشتر") }
            items(PAGES) { (key, title) ->
                Section("", Modifier.clickable { go(key) }) { Text(title, color = C.text, fontSize = 14.sp) }
            }
        }
    }
}

@Composable
private fun SubHeader(title: String, go: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
        TextButton(onClick = { go("") }) { Text("→ بازگشت") }
        Text(title, color = C.text, fontSize = 18.sp, fontWeight = FontWeight.Bold)
    }
}

// ---------- تنظیمات ----------
private data class Field(val path: String, val label: String, val kind: String = "num")

private val FIELDS = listOf(
    Field("mode", "حالت معامله", "choice:demo,paper,live"),
    Field("allow_live", "اجازه‌ی حساب واقعی", "bool"),
    Field("symbols", "نمادها (با ویرگول)", "list"),
    Field("risk.risk_per_trade_pct", "ریسک هر معامله (٪ موجودی)"),
    Field("risk.max_daily_loss_pct", "سقف ضرر روزانه (٪)"),
    Field("risk.max_trades_per_day", "سقف معاملات روزانه", "int"),
    Field("risk.max_open_positions", "حداکثر پوزیشن هم‌زمان", "int"),
    Field("risk.max_same_currency_exposure", "حداکثر پوزیشن هم‌جهت روی یک ارز", "int"),
    Field("risk.max_drawdown_pct", "Kill Switch خودکار در Drawdown (٪)"),
    Field("risk.min_rr_after_costs", "حداقل ریوارد به ریسک بعد از هزینه"),
    Field("risk.commission_per_lot_usd", "کمیسیون رفت‌وبرگشت هر لات ($)"),
    Field("confluence.min_strategies", "حداقل استراتژی هم‌جهت", "int"),
    Field("confluence.min_score", "آستانه‌ی امتیاز ترکیبی (۰-۱۰۰)"),
    Field("exits.partial_tp_r", "هدف اول (R)"),
    Field("exits.partial_close_pct", "درصد بستن در هدف اول", "int"),
    Field("exits.trail_atr_mult", "فاصله‌ی حد ضرر متحرک (×ATR)"),
    Field("exits.time_stop_bars", "Time Stop (تعداد کندل ۵ دقیقه)", "int"),
    Field("sessions.friday_cutoff_utc", "جمعه: بدون معامله‌ی جدید بعد از ساعت (UTC)", "int"),
    Field("sessions.kill_zone_only", "فقط در Kill Zone وارد شو", "bool"),
    Field("news.block_before_min", "توقف قبل از خبر مهم (دقیقه)", "int"),
    Field("news.block_after_min", "توقف بعد از خبر مهم (دقیقه)", "int"),
    Field("news.pre_news_action", "قبل از خبر مهم با پوزیشن باز", "choice:breakeven,partial,none"),
    Field("news.adverse_headline_action", "خبر فوری مخالف پوزیشن", "choice:tighten,close,none"),
    Field("news.finnhub_key", "کلید Finnhub", "secret"),
    Field("news.fmp_key", "کلید Financial Modeling Prep", "secret"),
    Field("news.te_key", "کلید Trading Economics", "secret"),
    Field("traps.reverse_on_trap", "در صورت تله، معامله‌ی برعکس", "bool"),
    Field("learning.enabled", "یادگیری فعال", "bool"),
    Field("learning.min_trades_per_bucket", "حداقل معامله قبل از تغییر وزن", "int"),
    Field("learning.drawdown_brake_pct", "ترمز یادگیری در Drawdown (٪)"),
    Field("learning.nn_enabled", "شبکه‌ی عصبی", "bool"),
    Field("notify.email.enabled", "ایمیل پشتیبان هشدارها", "bool"),
    Field("notify.email.smtp_host", "SMTP host", "text"),
    Field("notify.email.smtp_port", "SMTP port", "int"),
    Field("notify.email.user", "ایمیل فرستنده", "text"),
    Field("notify.email.password", "رمز ایمیل (App Password)", "secret"),
    Field("notify.email.to", "ایمیل گیرنده", "text"),
)

private val CHOICE_FA = mapOf("demo" to "دمو", "paper" to "شبیه‌سازی", "live" to "واقعی", "breakeven" to "سربه‌سر",
    "partial" to "بستن بخشی", "none" to "هیچ", "tighten" to "محدود کردن ضرر", "close" to "بستن")

private fun lookup(cfg: JSONObject, path: String): Any? {
    var cur: Any? = cfg
    for (p in path.split(".")) cur = (cur as? JSONObject)?.opt(p)
    return cur
}

private fun putPath(root: JSONObject, path: String, value: Any) {
    val parts = path.split(".")
    var cur = root
    for (p in parts.dropLast(1)) {
        if (!cur.has(p)) cur.put(p, JSONObject())
        cur = cur.getJSONObject(p)
    }
    cur.put(parts.last(), value)
}

@Composable
fun SettingsScreen(vm: AppVM, go: (String) -> Unit) {
    LaunchedEffect(Unit) { vm.load("config", "/api/config") }
    val resp = vm.data["config"] as? JSONObject
    val cfg = resp?.optJSONObject("config")
    val values = remember(cfg) { mutableStateMapOf<String, String>() }
    LaunchedEffect(cfg) {
        if (cfg == null) return@LaunchedEffect
        FIELDS.forEach { f ->
            val v = lookup(cfg, f.path)
            values[f.path] = when (v) {
                is JSONArray -> v.strings().joinToString(", ")
                null -> ""
                else -> v.toString()
            }
        }
        val st = cfg.o("strategies")
        st.keys().forEach { k -> values["strategies.$k"] = st.optBoolean(k).toString() }
    }
    LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
        item { SubHeader("تنظیمات", go) }
        if (cfg == null) {
            item { Section("") { Muted("در حال بارگذاری…") } }
            return@LazyColumn
        }
        item {
            Section("") {
                Muted("ممنوعیت‌های قطعی (مارتینگل، گرید، معامله بدون حد ضرر، دورتر کردن حد ضرر) در کد قفل‌اند و تنظیمی ندارند.")
            }
        }
        items(FIELDS) { f -> FieldEditor(f, values) }
        item {
            Section("استراتژی‌ها") {
                val fa = resp?.o("strategies_fa") ?: JSONObject()
                cfg.o("strategies").keys().asSequence().toList().forEach { k ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(fa.s(k, k), color = C.text, fontSize = 13.sp, modifier = Modifier.weight(1f))
                        Switch(checked = values["strategies.$k"] == "true", onCheckedChange = { values["strategies.$k"] = it.toString() })
                    }
                }
            }
        }
        item {
            Column(Modifier.padding(12.dp)) {
                Button(onClick = {
                    val patch = JSONObject()
                    try {
                        FIELDS.forEach { f ->
                            val raw = values[f.path] ?: return@forEach
                            val orig = lookup(cfg, f.path)
                            val v: Any = when {
                                f.kind == "bool" -> raw == "true"
                                f.kind == "int" -> raw.trim().toInt()
                                f.kind == "num" -> raw.trim().toDouble()
                                f.kind == "list" -> JSONArray(raw.split(",").map { it.trim() }.filter { it.isNotEmpty() })
                                else -> raw
                            }
                            val changed = when (orig) {
                                is JSONArray -> orig.toString() != v.toString()
                                is Number -> (orig.toDouble() != (v as? Number)?.toDouble())
                                else -> orig?.toString() != v.toString()
                            }
                            if (changed) putPath(patch, f.path, v)
                        }
                        cfg.o("strategies").keys().forEach { k ->
                            val nv = values["strategies.$k"] == "true"
                            if (nv != cfg.o("strategies").optBoolean(k)) putPath(patch, "strategies.$k", nv)
                        }
                        vm.updateConfig(patch, "تغییر از اپ")
                        values.clear()
                    } catch (e: NumberFormatException) {
                        vm.message = "عدد نامعتبر در یکی از فیلدها"
                    }
                }, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("ذخیره‌ی تنظیمات") }
            }
        }
    }
}

@Composable
private fun FieldEditor(f: Field, values: MutableMap<String, String>) {
    val v = values[f.path] ?: ""
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
        when {
            f.kind == "bool" -> Row(verticalAlignment = Alignment.CenterVertically) {
                Text(f.label, color = C.text, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Switch(checked = v == "true", onCheckedChange = { values[f.path] = it.toString() })
            }
            f.kind.startsWith("choice:") -> {
                Text(f.label, color = C.muted, fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    f.kind.removePrefix("choice:").split(",").forEach { opt ->
                        FilterChip(v == opt, { values[f.path] = opt }, label = { Text(CHOICE_FA[opt] ?: opt) })
                    }
                }
            }
            else -> OutlinedTextField(
                value = v, onValueChange = { values[f.path] = it }, label = { Text(f.label) }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                visualTransformation = if (f.kind == "secret") PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
                keyboardOptions = KeyboardOptions(keyboardType = when (f.kind) {
                    "num" -> KeyboardType.Decimal; "int" -> KeyboardType.Number; else -> KeyboardType.Text
                })
            )
        }
    }
}

// ---------- MT5 ----------
@Composable
fun Mt5Screen(vm: AppVM, go: (String) -> Unit) {
    var login by remember { mutableStateOf("") }
    var pass by remember { mutableStateOf("") }
    var server by remember { mutableStateOf("LiteFinance-MT5-Demo") }
    var path by remember { mutableStateOf("") }
    LazyColumn {
        item { SubHeader("حساب متاتریدر", go) }
        item {
            Section("") {
                Body("رمز فقط یک‌بار به سرور فرستاده و آنجا رمزنگاری‌شده ذخیره می‌شود؛ روی گوشی ذخیره نمی‌شود و از سرور هم برگردانده نمی‌شود.")
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(login, { login = it.filter(Char::isDigit) }, label = { Text("شماره حساب (Login)") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
                OutlinedTextField(pass, { pass = it }, label = { Text("رمز معامله") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                OutlinedTextField(server, { server = it }, label = { Text("نام سرور بروکر") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(path, { path = it }, label = { Text("مسیر terminal64.exe (خالی = پیش‌فرض)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(8.dp))
                Muted("مسیر پیش‌فرض C:\\NeuroTraderPro\\MT5 است — یک نصب جدا از متاتریدرِ برنامه‌ی دیگر روی سرور، تا حساب آن عوض نشود.")
                Spacer(Modifier.height(8.dp))
                BusyButton("ارسال امن به سرور", vm.busy, login.isNotBlank() && pass.isNotBlank() && server.isNotBlank()) {
                    vm.sendMt5(login, pass, server, path); pass = ""
                }
            }
        }
    }
}

// ---------- سلامت ----------
@Composable
fun HealthScreen(vm: AppVM, go: (String) -> Unit) {
    LaunchedEffect(Unit) {
        while (true) {
            vm.load("health", "/api/health"); delay(5000)
        }
    }
    val h = vm.data["health"] as? JSONObject
    LazyColumn {
        item { SubHeader("وضعیت سلامت", go) }
        if (h == null) {
            item { Section("") { Muted("در حال بارگذاری…") } }
            return@LazyColumn
        }
        item {
            Section("اتصال‌ها") {
                StatusRow("اپ ↔ سرور VPS", true, if (vm.wsConnected) "زنده (WebSocket)" else "درخواست معمولی")
                StatusRow("موتور ↔ متاتریدر", h.optBoolean("mt5"), "اتصال مجدد: ${h.optInt("reconnects")}")
                val ping = h.d("ping_ms", -1.0)
                StatusRow("پینگ تا سرور بروکر", ping in 0.0..250.0, if (ping < 0) "-" else "${ping.f(0)}ms")
                val age = h.d("feed_age", -1.0)
                StatusRow("داده‌ی قیمت", age in 0.0..120.0, if (age < 0) "-" else "${age.f(0)} ثانیه پیش")
                val na = h.d("news_age", -1.0)
                StatusRow("فید اخبار", na in 0.0..1800.0, if (na < 0) "-" else "${(na / 60).f(0)} دقیقه پیش")
                StatusRow("تقویم اقتصادی", h.s("calendar_source").isNotEmpty(), h.s("calendar_source"))
                StatusRow("Watchdog", true, "آپ‌تایم ${(h.d("uptime") / 3600).f(1)} ساعت")
                KV("نسخه / Magic", "${h.s("version")} / ${h.s("magic")}")
            }
        }
        item {
            Section("اسلیپیج") {
                val sl = h.a("slippage").objects()
                if (sl.isEmpty()) Muted("هنوز معامله‌ای ثبت نشده")
                sl.forEach { s -> KV(s.s("symbol"), "میانگین ${s.d("avg").f(1)} • بیشترین ${s.d("max").f(1)} پوینت (${s.optInt("n")})") }
            }
        }
    }
}

// ---------- گزارش ----------
@Composable
fun ReportsScreen(vm: AppVM, go: (String) -> Unit) {
    LaunchedEffect(Unit) {
        vm.load("weekly", "/api/reports/weekly"); vm.load("journal", "[/api/journal?limit=100")
    }
    val w = vm.data["weekly"] as? JSONObject
    val j = (vm.data["journal"] as? JSONArray)?.objects() ?: emptyList()
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { SubHeader("گزارش و ژورنال", go) }
        item { Section("گزارش هفتگی") { Body(w?.s("text") ?: "…") } }
        item { Section("ژورنال معاملات") { if (j.isEmpty()) Muted("هنوز معامله‌ای نیست") } }
        items(j) { t ->
            Section("${dirFa(t.optInt("direction"))} ${t.s("symbol")} • ${t.s("entry_time_tehran")}") {
                Body(t.s("reason_open"))
                if (t.s("reason_close").isNotEmpty()) {
                    Spacer(Modifier.height(4.dp)); Body(t.s("reason_close"), pnlColor(t.d("pnl")))
                }
            }
        }
    }
}

// ---------- بک‌تست ----------
@Composable
fun BacktestScreen(vm: AppVM, go: (String) -> Unit) {
    var days by remember { mutableStateOf("60") }
    LaunchedEffect(Unit) {
        while (true) {
            vm.load("backtest", "/api/backtest"); delay(8000)
        }
    }
    val b = vm.data["backtest"] as? JSONObject
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { SubHeader("بک‌تست", go) }
        item {
            Section("اجرای بک‌تست روی سرور") {
                Muted("با کمیسیون ECN، اسپرد متغیر و اسلیپیج؛ برای هر استراتژی جدا و ترکیبی. اجرا با اولویت پایین تا معاملات کند نشوند.")
                OutlinedTextField(days, { days = it.filter(Char::isDigit) }, label = { Text("تعداد روز") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(6.dp))
                BusyButton(if (b?.optBoolean("running") == true) "در حال اجرا…" else "شروع", vm.busy, b?.optBoolean("running") != true) {
                    vm.action("/api/backtest", JSONObject().put("days", days.toIntOrNull() ?: 60), "بک‌تست شروع شد")
                }
            }
        }
        val res = b?.optJSONObject("last")?.optJSONObject("results")
        if (res != null) {
            res.keys().asSequence().toList().forEach { sym ->
                val r = res.o(sym)
                item { Section("نتیجه‌ی ترکیبی $sym") { Body(r.s("text")) } }
                val per = r.o("per_strategy")
                item {
                    Section("هر استراتژی جدا — $sym") {
                        per.keys().asSequence().toList().forEach { k ->
                            val p = per.o(k)
                            KV(k, "${p.optInt("trades")} معامله • WR ${p.d("win_rate").f(0)}٪ • PF ${p.d("profit_factor").f(2)} • Exp ${p.d("expectancy_r").signed()}R",
                                if (p.d("expectancy_r") > 0) C.green else C.muted)
                        }
                    }
                }
            }
        }
    }
}

// ---------- لاگ ----------
@Composable
fun LogsScreen(vm: AppVM, go: (String) -> Unit) {
    val state = rememberLazyListState()
    LaunchedEffect(vm.logs.size) { if (vm.logs.isNotEmpty()) state.scrollToItem(vm.logs.size) }
    LazyColumn(state = state) {
        item { SubHeader("لاگ زنده", go) }
        if (vm.logs.isEmpty()) item { Section("") { Muted(if (vm.wsConnected) "منتظر لاگ…" else "اتصال زنده برقرار نیست") } }
        items(vm.logs.toList()) { l ->
            val color = when (l.s("level")) { "ERROR" -> C.red; "WARNING" -> C.amber; else -> C.muted }
            Text("${tehran(l.d("time").toLong())} ${l.s("msg")}", color = color, fontSize = 11.sp,
                fontFamily = FontFamily.Monospace, modifier = Modifier.padding(horizontal = 10.dp, vertical = 1.dp))
        }
    }
}

// ---------- هشدارها ----------
@Composable
fun AlertsScreen(vm: AppVM, go: (String) -> Unit) {
    LaunchedEffect(Unit) { vm.load("alerts", "[/api/alerts") }
    val list = (vm.data["alerts"] as? JSONArray)?.objects() ?: emptyList()
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { SubHeader("هشدارها", go) }
        items(list) { a ->
            val color = when (a.s("level")) { "critical" -> C.red; "warning" -> C.amber; "trade" -> C.green; else -> C.blue }
            Section("") {
                Text(a.s("time_tehran") + " • " + a.s("kind"), color = color, fontSize = 12.sp)
                Body(a.s("message"))
            }
        }
    }
}

// ---------- نسخه‌های تنظیمات ----------
@Composable
fun VersionsScreen(vm: AppVM, go: (String) -> Unit) {
    LaunchedEffect(Unit) { vm.load("versions", "[/api/config/versions") }
    val list = (vm.data["versions"] as? JSONArray)?.objects() ?: emptyList()
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { SubHeader("تاریخچه‌ی تنظیمات", go) }
        items(list) { v ->
            Section("#${v.optInt("id")} • ${v.s("time_tehran")} • ${v.s("user")}") {
                Muted(v.s("reason"))
                v.a("changes").strings().take(12).forEach { Text(it, color = C.text, fontSize = 11.sp, fontFamily = FontFamily.Monospace) }
                OutlinedButton(onClick = { vm.action("/api/config/versions/${v.optInt("id")}/restore", ok = "تنظیمات به این نسخه برگشت") }) {
                    Text("بازگردانی این نسخه")
                }
            }
        }
    }
}

// ---------- حساب ----------
@Composable
fun AccountScreen(vm: AppVM, go: (String) -> Unit) {
    LazyColumn {
        item { SubHeader("خروج و امنیت", go) }
        item {
            Section("") {
                KV("سرور", vm.store.server)
                KV("اثر انگشت گواهی", vm.store.pin.take(16) + "…")
                KV("کاربر", vm.store.username)
                Spacer(Modifier.height(10.dp))
                OutlinedButton(onClick = { vm.logout(false) }, modifier = Modifier.fillMaxWidth()) { Text("خروج") }
                OutlinedButton(onClick = { vm.logout(true) }, modifier = Modifier.fillMaxWidth()) { Text("خروج از همه‌ی دستگاه‌ها") }
                OutlinedButton(onClick = { vm.resetServer() }, modifier = Modifier.fillMaxWidth()) { Text("تغییر سرور / حذف اطلاعات اپ", color = C.red) }
            }
        }
    }
}
