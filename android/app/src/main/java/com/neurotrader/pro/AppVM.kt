package com.neurotrader.pro

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.neurotrader.pro.data.Api
import com.neurotrader.pro.data.ApiException
import com.neurotrader.pro.data.Net
import com.neurotrader.pro.data.Store
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject

enum class Screen { Connect, Setup, Login, Main }

class AppVM(app: Application) : AndroidViewModel(app) {
    val store = Store(app)
    val api = Api(store)

    var screen by mutableStateOf(Screen.Connect)
    var busy by mutableStateOf(false)
    var message by mutableStateOf<String?>(null)
    var pendingFingerprint by mutableStateOf<String?>(null)
    var totpSecret by mutableStateOf<JSONObject?>(null)
    var setupUser by mutableStateOf("")

    var state by mutableStateOf<JSONObject?>(null)
    var wsConnected by mutableStateOf(false)
    var lastUpdate by mutableStateOf(0L)
    val logs = mutableStateListOf<JSONObject>()
    val data = mutableStateMapOf<String, Any?>()

    private var ws: WebSocket? = null
    private var liveJob: Job? = null
    private var lastLogId = 0L

    init {
        viewModelScope.launch { boot() }
    }

    private suspend fun boot() {
        if (store.server.isEmpty() || store.pin.isEmpty()) {
            screen = Screen.Connect; return
        }
        if (store.refreshToken.isNotEmpty() && api.refresh()) {
            enterMain(); return
        }
        try {
            val p = api.ping()
            screen = if (p.optBoolean("setup_required")) Screen.Setup else Screen.Login
        } catch (e: Exception) {
            screen = Screen.Login
            message = e.message
        }
    }

    private fun launchBusy(block: suspend () -> Unit) = viewModelScope.launch {
        busy = true
        try {
            block()
        } catch (e: ApiException) {
            message = e.message
        } catch (e: Exception) {
            message = e.message ?: e.toString()
        } finally {
            busy = false
        }
    }

    // ---------- اتصال و ورود ----------
    fun connect(address: String) = launchBusy {
        var url = address.trim().trimEnd('/')
        if (!url.startsWith("https://")) url = "https://" + url.removePrefix("http://")
        if (!Regex(":\\d+$").containsMatchIn(url.substringAfter("://"))) url += ":8810"
        store.server = url
        val fp = withContext(Dispatchers.IO) { Net.fetchFingerprint(url) }.getOrThrow()
        pendingFingerprint = fp
    }

    fun acceptFingerprint() = launchBusy {
        store.pin = pendingFingerprint ?: return@launchBusy
        pendingFingerprint = null
        api.rebuild()
        val p = api.ping()
        screen = if (p.optBoolean("setup_required")) Screen.Setup else Screen.Login
    }

    fun resetServer() {
        stopLive()
        store.clearAll()
        api.rebuild()
        state = null
        screen = Screen.Connect
    }

    fun setup(code: String, user: String, pass: String) = launchBusy {
        totpSecret = api.setup(code, user, pass)
        setupUser = user
    }

    fun confirmSetup(code: String) = launchBusy {
        api.confirm(setupUser, code)
        totpSecret = null
        enterMain()
    }

    fun login(user: String, pass: String, code: String) = launchBusy {
        api.login(user, pass, code)
        enterMain()
    }

    fun logout(all: Boolean) = launchBusy {
        if (all) runCatching { api.post("/api/auth/logout_all") }
        stopLive()
        store.clearSession()
        screen = Screen.Login
    }

    private suspend fun enterMain() {
        screen = Screen.Main
        refreshState()
        // جلوگیری از سیل نوتیفیکیشن‌های قدیمی بعد از ورود
        runCatching {
            val a = api.arr("/api/alerts?after=0")
            if (a.length() > 0 && store.lastAlertId == 0L) store.lastAlertId = a.getJSONObject(0).optLong("id")
        }
        AlertWorker.schedule(getApplication())
        startLive()
    }

    // ---------- داده‌ی زنده ----------
    fun refreshState() = viewModelScope.launch {
        try {
            state = api.obj("/api/state")
            lastUpdate = System.currentTimeMillis()
        } catch (e: ApiException) {
            if (e.code == 401) screen = Screen.Login else message = e.message
        }
    }

    fun startLive() {
        if (liveJob?.isActive == true) return
        liveJob = viewModelScope.launch {
            var backoff = 2000L
            while (screen == Screen.Main) {
                if (!wsConnected) {
                    api.refresh()
                    ws?.cancel()
                    ws = api.websocket(listener, lastLogId)
                }
                delay(backoff)
                backoff = if (wsConnected) 2000L else (backoff * 2).coerceAtMost(30000L)
                if (!wsConnected) refreshState()     // اگر WebSocket قطع است، با درخواست معمولی به‌روز کن
            }
        }
    }

    fun stopLive() {
        liveJob?.cancel()
        ws?.close(1000, null)
        ws = null
        wsConnected = false
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            wsConnected = true
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val m = runCatching { JSONObject(text) }.getOrNull() ?: return
            viewModelScope.launch(Dispatchers.Main) {
                when (m.optString("type")) {
                    "state" -> {
                        state = m.optJSONObject("data"); lastUpdate = System.currentTimeMillis()
                    }
                    "log" -> {
                        val arr = m.optJSONArray("data") ?: JSONArray()
                        for (i in 0 until arr.length()) {
                            val l = arr.getJSONObject(i)
                            logs.add(l); lastLogId = l.optLong("id")
                        }
                        while (logs.size > 600) logs.removeAt(0)
                    }
                    "alerts" -> {
                        val arr = m.optJSONArray("data") ?: JSONArray()
                        for (i in 0 until arr.length()) {
                            val a = arr.getJSONObject(i)
                            if (a.optLong("id") > store.lastAlertId) {
                                store.lastAlertId = a.optLong("id")
                                if (Notifs.shouldNotify(a)) Notifs.show(getApplication(), a)
                            }
                        }
                    }
                }
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            wsConnected = false
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            wsConnected = false
        }
    }

    // ---------- بارگذاری بخش‌ها ----------
    fun load(key: String, path: String) = viewModelScope.launch {
        try {
            val r: Any = if (path.startsWith("[")) api.arr(path.removePrefix("[")) else api.obj(path)
            data[key] = r
        } catch (e: ApiException) {
            message = e.message
        }
    }

    // ---------- دستورها ----------
    fun action(path: String, body: JSONObject? = null, ok: String = "انجام شد", after: (() -> Unit)? = null) = launchBusy {
        api.post(path, body)
        message = ok
        refreshState()
        after?.invoke()
    }

    fun setBot(on: Boolean) = action("/api/bot", JSONObject().put("enabled", on), if (on) "ربات روشن شد" else "ربات خاموش شد")

    fun kill(active: Boolean) = action("/api/kill", JSONObject().put("active", active).put("reason", "از اپ"),
        if (active) "Kill Switch فعال شد" else "Kill Switch غیرفعال شد")

    fun closePosition(id: Long) = action("/api/positions/$id/close", ok = "دستور بستن ارسال شد")

    fun updateConfig(patch: JSONObject, reason: String) = launchBusy {
        val r = api.put("/api/config", JSONObject().put("patch", patch).put("reason", reason))
        val n = r.optJSONArray("changes")?.length() ?: 0
        message = if (n > 0) "$n تغییر ذخیره شد" else "تغییری نبود"
        load("config", "/api/config")
    }

    fun sendMt5(login: String, password: String, server: String, path: String, shared: Boolean) = launchBusy {
        api.post("/api/mt5/credentials", JSONObject().put("login", login.toLongOrNull() ?: 0L).put("password", password)
            .put("server", server).put("path", path).put("shared", shared))
        message = if (shared) "ذخیره شد؛ موتور به همان متاتریدرِ باز روی سرور وصل می‌شود"
        else "اطلاعات حساب رمزنگاری‌شده روی سرور ذخیره شد؛ اتصال دوباره برقرار می‌شود"
    }
}
