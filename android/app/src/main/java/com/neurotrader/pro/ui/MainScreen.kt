package com.neurotrader.pro.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neurotrader.pro.AppVM
import org.json.JSONArray
import org.json.JSONObject

@Composable
fun MainScreen(vm: AppVM, snackbar: SnackbarHostState) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var sub by rememberSaveable { mutableStateOf("") }
    val tabs = listOf("داشبورد" to Icons.Default.Home, "معاملات" to Icons.Default.List, "یادگیری" to Icons.Default.Star,
        "اخبار" to Icons.Default.Notifications, "بیشتر" to Icons.Default.Menu)
    Scaffold(
        containerColor = C.bg,
        snackbarHost = { androidx.compose.material3.SnackbarHost(snackbar) },
        bottomBar = {
            NavigationBar(containerColor = C.card) {
                tabs.forEachIndexed { i, (label, icon) ->
                    NavigationBarItem(selected = tab == i, onClick = { tab = i; sub = "" },
                        icon = { Icon(icon, contentDescription = label) }, label = { Text(label, fontSize = 11.sp) },
                        colors = NavigationBarItemDefaults.colors(selectedIconColor = C.green, selectedTextColor = C.green,
                            unselectedIconColor = C.muted, unselectedTextColor = C.muted, indicatorColor = C.card2))
                }
            }
        }
    ) { pad ->
        Box(Modifier.padding(pad).fillMaxSize()) {
            when (tab) {
                0 -> Dashboard(vm)
                1 -> TradesScreen(vm)
                2 -> LearningScreen(vm)
                3 -> NewsScreen(vm)
                else -> MoreScreen(vm, sub) { sub = it }
            }
        }
    }
}

@Composable
fun Header(vm: AppVM, title: String) {
    val st = vm.state
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, color = C.text, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        if (st != null) {
            Text(MODE_FA[st.s("mode")] ?: st.s("mode"), color = if (st.s("mode") == "live") C.red else C.amber, fontSize = 12.sp)
            Spacer(Modifier.width(8.dp))
        }
        Dot(vm.wsConnected)
    }
}

@Composable
fun Dashboard(vm: AppVM) {
    val st = vm.state
    var confirmKill by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { vm.refreshState() }
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { Header(vm, "داشبورد") }
        if (st == null) {
            item { Section("") { Muted("در حال دریافت وضعیت از سرور…") } }
            return@LazyColumn
        }
        val acc = st.o("account")
        val stats = st.o("stats")
        val kill = st.o("kill_switch")
        val halt = st.o("execution_halt")
        val learning = st.o("learning")
        if (kill.optBoolean("active")) item { Banner("Kill Switch فعال است: ${kill.s("reason")}", C.red) }
        if (halt.optBoolean("active")) item { Banner("معامله‌ی جدید متوقف است: ${halt.s("reason")}", C.amber) }
        if (learning.optBoolean("paused")) item { Banner("یادگیری متوقف است: ${learning.s("reason")}", C.amber) }
        if (!st.o("health").optBoolean("mt5")) item { Banner("اتصال موتور به متاتریدر قطع است (موتور در حال تلاش مجدد است)", C.red) }
        item {
            Section("حساب") {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceAround) {
                    Stat("موجودی", acc.d("balance").f(), modifier = Modifier.weight(1f))
                    Stat("Equity", acc.d("equity").f(), modifier = Modifier.weight(1f))
                    Stat("سود/ضرر امروز", stats.d("day_pnl").signed(), pnlColor(stats.d("day_pnl")), Modifier.weight(1f))
                }
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceAround) {
                    Stat("وین‌ریت", "${stats.d("win_rate").f(1)}٪", modifier = Modifier.weight(1f))
                    Stat("Profit Factor", if (stats.isNull("profit_factor")) "-" else stats.d("profit_factor").f(), modifier = Modifier.weight(1f))
                    Stat("Drawdown", "${stats.d("drawdown_pct").f(1)}٪", if (stats.d("drawdown_pct") > 4) C.red else C.text, Modifier.weight(1f))
                }
                Spacer(Modifier.height(6.dp))
                KV("Expectancy", "${stats.d("expectancy_r").signed(3)}R")
                KV("تعداد معاملات", stats.optInt("trades").toString())
                KV("حساب", "${acc.s("login")} @ ${acc.s("server")}${if (acc.optBoolean("demo")) " (دمو)" else ""}")
            }
        }
        item {
            Section("کنترل ربات") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("ربات", color = C.text, modifier = Modifier.weight(1f))
                    Switch(checked = st.optBoolean("bot_enabled"), onCheckedChange = { vm.setBot(it) })
                }
                Spacer(Modifier.height(8.dp))
                if (kill.optBoolean("active")) {
                    OutlinedButton(onClick = { vm.kill(false) }, modifier = Modifier.fillMaxWidth()) { Text("غیرفعال کردن Kill Switch") }
                } else {
                    Button(onClick = { confirmKill = true }, modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = C.red)) { Text("Kill Switch — توقف فوری معاملات جدید") }
                }
            }
        }
        val market = st.o("market")
        val keys = market.keys().asSequence().toList()
        items(keys) { sym -> MarketCard(market.o(sym)) }
        val positions = st.a("positions").objects()
        item { Section("پوزیشن‌های باز (${positions.size})") { if (positions.isEmpty()) Muted("پوزیشن بازی نیست") } }
        items(positions) { p -> PositionCard(vm, p) }
    }
    if (confirmKill) {
        AlertDialog(onDismissRequest = { confirmKill = false },
            title = { Text("فعال‌سازی Kill Switch") },
            text = { Body("هیچ معامله‌ی جدیدی باز نمی‌شود تا وقتی دستی غیرفعالش کنید. پوزیشن‌های باز با حد ضرر/سودشان مدیریت می‌شوند.") },
            confirmButton = { TextButton(onClick = { confirmKill = false; vm.kill(true) }) { Text("فعال کن", color = C.red) } },
            dismissButton = { TextButton(onClick = { confirmKill = false }) { Text("انصراف") } })
    }
}

@Composable
fun Banner(text: String, color: Color) {
    Section("") { Text(text, color = color, fontWeight = FontWeight.Bold, fontSize = 13.sp) }
}

@Composable
fun MarketCard(m: JSONObject) {
    Section(m.s("symbol")) {
        KV("قیمت", if (m.has("bid")) m.d("bid").toString() else "-")
        KV("اسپرد", "${m.d("spread_points").f(0)} پوینت")
        KV("وضعیت بازار", "${REGIME_FA[m.s("regime")] ?: "-"} (ADX ${m.d("adx").f(0)})")
        KV("سشن", (SESSION_FA[m.s("session")] ?: "-") + (if (m.s("kill_zone").isNotEmpty()) " • Kill Zone" else ""))
        KV("روند تایم بالاتر", when (m.optInt("htf_dir")) { 1 -> "صعودی"; -1 -> "نزولی"; else -> "نامشخص" })
        if (m.has("intermarket_note") && m.s("intermarket_note").isNotEmpty()) KV("بین‌بازاری", m.s("intermarket_note"))
        val mins = m.d("minutes_to_news", 9999.0)
        if (mins < 600) KV("خبر مهم بعدی", "${mins.f(0)} دقیقه دیگر", if (mins < 60) C.amber else C.text)
        if (!m.optBoolean("can_open", true)) KV("ورود جدید", m.s("block_reason"), C.amber)
        if (m.s("news_block").isNotEmpty()) KV("توقف خبری", m.s("news_block"), C.amber)
        val sig = m.optJSONObject("last_signal")
        if (sig != null) {
            Spacer(Modifier.height(6.dp))
            Muted("آخرین سیگنال: ${dirFa(sig.optInt("direction"))} — امتیاز ${sig.d("score").f(0)}" +
                    (if (!sig.isNull("ml_prob")) " — مدل ${(sig.d("ml_prob") * 100).f(0)}٪" else "") +
                    (if (sig.optBoolean("accepted")) " ✓" else " — ${sig.s("reason")}"))
        }
    }
}

@Composable
fun PositionCard(vm: AppVM, p: JSONObject) {
    var expand by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    val profit = p.d("profit")
    Section("${dirFa(p.optInt("direction"))} ${p.s("symbol")} — ${p.d("volume")} لات", Modifier.clickable { expand = !expand }) {
        KV("سود/ضرر شناور", if (p.isNull("profit")) "-" else profit.signed(), pnlColor(profit))
        KV("ورود", "${p.d("entry_price")} • ${p.s("entry_time_tehran")}")
        KV("حد ضرر / حد سود", "${p.d("sl")} / ${p.d("tp")}")
        KV("وضعیت", if (p.s("status") == "pending") "سفارش لیمیت در انتظار" else if (p.optInt("tp1_hit") == 1) "هدف اول گرفته شد" else "باز")
        if (expand) {
            Spacer(Modifier.height(6.dp))
            Body(p.s("reason_open"))
        }
        Spacer(Modifier.height(6.dp))
        OutlinedButton(onClick = { confirm = true }, modifier = Modifier.fillMaxWidth()) { Text("بستن پوزیشن", color = C.red) }
    }
    if (confirm) {
        AlertDialog(onDismissRequest = { confirm = false }, title = { Text("بستن ${p.s("symbol")}؟") },
            confirmButton = { TextButton(onClick = { confirm = false; vm.closePosition(p.optLong("id")) }) { Text("ببند") } },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("انصراف") } })
    }
}

@Composable
fun TradesScreen(vm: AppVM) {
    var status by rememberSaveable { mutableStateOf("closed") }
    LaunchedEffect(status) { vm.load("trades_$status", "[/api/trades?status=$status&limit=200") }
    val list = (vm.data["trades_$status"] as? JSONArray)?.objects() ?: emptyList()
    LazyColumn(contentPadding = PaddingValues(bottom = 16.dp)) {
        item { Header(vm, "معاملات") }
        item {
            Row(Modifier.padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(status == "closed", { status = "closed" }, label = { Text("تاریخچه") })
                FilterChip(status == "open", { status = "open" }, label = { Text("باز") })
                FilterChip(status == "cancelled", { status = "cancelled" }, label = { Text("لغوشده") })
            }
        }
        if (list.isEmpty()) item { Section("") { Muted("موردی نیست") } }
        items(list) { t -> TradeCard(t) }
    }
}

@Composable
fun TradeCard(t: JSONObject) {
    var expand by remember { mutableStateOf(false) }
    val pnl = t.d("pnl")
    Section("${dirFa(t.optInt("direction"))} ${t.s("symbol")}  ${if (t.s("status") == "closed") pnl.signed() + "$" else ""}",
        Modifier.clickable { expand = !expand }) {
        if (t.s("status") == "closed") KV("نتیجه", "${t.d("r_multiple").signed()}R", pnlColor(pnl))
        KV("ورود", "${t.d("entry_price")} • ${t.s("entry_time_tehran")}")
        if (t.s("exit_time_tehran").isNotEmpty()) KV("خروج", "${t.d("exit_price")} • ${t.s("exit_time_tehran")}")
        KV("استراتژی‌ها", t.a("strategies_fa").strings().joinToString("، "))
        KV("وضعیت بازار / سشن", "${REGIME_FA[t.s("regime")] ?: "-"} / ${SESSION_FA[t.s("session")] ?: "-"}")
        if (!t.isNull("ml_prob")) KV("احتمال مدل", "${(t.d("ml_prob") * 100).f(0)}٪")
        if (!t.isNull("slippage_points")) KV("اسلیپیج", "${t.d("slippage_points").f(1)} پوینت")
        if (expand) {
            Spacer(Modifier.height(6.dp))
            Text("چرا باز شد", color = C.blue, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            Body(t.s("reason_open"))
            if (t.s("reason_close").isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text("چرا بسته شد", color = C.blue, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                Body(t.s("reason_close"))
            }
        } else Muted("برای دیدن دلیل ورود و خروج بزنید")
    }
}
