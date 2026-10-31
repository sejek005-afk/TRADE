package com.neurotrader.pro.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener

class ApiException(val code: Int, message: String) : Exception(message)

class Api(private val store: Store) {
    private val json = "application/json; charset=utf-8".toMediaType()
    private val refreshLock = Mutex()
    private var http: OkHttpClient = Net.client(store.pin).first
    private var wsHttp: OkHttpClient = Net.client(store.pin, 0).first

    fun rebuild() {
        http = Net.client(store.pin).first
        wsHttp = Net.client(store.pin, 0).first
    }

    private val base get() = store.server.trimEnd('/')

    private fun parseError(code: Int, body: String): ApiException {
        val msg = runCatching { JSONObject(body).optString("detail") }.getOrNull()
        return ApiException(code, if (msg.isNullOrBlank()) "خطای سرور ($code)" else msg)
    }

    private fun raw(method: String, path: String, body: JSONObject?, auth: Boolean): Any {
        val b = Request.Builder().url(base + path)
        if (auth && store.accessToken.isNotEmpty()) b.header("Authorization", "Bearer ${store.accessToken}")
        val rb = (body ?: JSONObject()).toString().toRequestBody(json)
        when (method) {
            "GET" -> b.get()
            "POST" -> b.post(rb)
            "PUT" -> b.put(rb)
        }
        http.newCall(b.build()).execute().use { r ->
            val text = r.body?.string() ?: ""
            if (!r.isSuccessful) throw parseError(r.code, text)
            if (text.isBlank()) return JSONObject()
            return JSONTokener(text).nextValue()
        }
    }

    private suspend fun call(method: String, path: String, body: JSONObject? = null, auth: Boolean = true): Any =
        withContext(Dispatchers.IO) {
            try {
                raw(method, path, body, auth)
            } catch (e: ApiException) {
                if (e.code == 401 && auth && refresh()) raw(method, path, body, auth) else throw e
            } catch (e: java.io.IOException) {
                throw ApiException(0, "اتصال به سرور برقرار نشد: ${e.message ?: ""}")
            }
        }

    suspend fun refresh(): Boolean {
        refreshLock.withLock {
            if (store.refreshToken.isEmpty()) return false
            return withContext(Dispatchers.IO) {
                try {
                    val r = raw("POST", "/api/auth/refresh", JSONObject().put("refresh_token", store.refreshToken), false) as JSONObject
                    saveTokens(r)
                    true
                } catch (e: Exception) {
                    if (e is ApiException && e.code == 401) store.clearSession()
                    false
                }
            }
        }
    }

    fun saveTokens(r: JSONObject) {
        store.accessToken = r.optString("access_token")
        store.refreshToken = r.optString("refresh_token")
    }

    suspend fun obj(path: String): JSONObject = call("GET", path) as JSONObject
    suspend fun arr(path: String): JSONArray = call("GET", path) as JSONArray
    suspend fun post(path: String, body: JSONObject? = null): JSONObject = call("POST", path, body) as JSONObject
    suspend fun put(path: String, body: JSONObject): JSONObject = call("PUT", path, body) as JSONObject

    // ---------- احراز هویت ----------
    suspend fun ping(): JSONObject = call("GET", "/api/ping", auth = false) as JSONObject

    suspend fun setup(code: String, user: String, pass: String): JSONObject =
        call("POST", "/api/auth/setup", JSONObject().put("setup_code", code).put("username", user).put("password", pass), false) as JSONObject

    suspend fun confirm(user: String, code: String) {
        val r = call("POST", "/api/auth/setup/confirm", JSONObject().put("username", user).put("code", code), false) as JSONObject
        saveTokens(r)
        store.username = user
    }

    suspend fun login(user: String, pass: String, code: String) {
        val r = call("POST", "/api/auth/login", JSONObject().put("username", user).put("password", pass).put("code", code), false) as JSONObject
        saveTokens(r)
        store.username = user
    }

    fun websocket(listener: WebSocketListener, logAfter: Long): WebSocket {
        val url = base.replaceFirst("https://", "wss://") + "/ws?token=${store.accessToken}&log_after=$logAfter"
        return wsHttp.newWebSocket(Request.Builder().url(url).build(), listener)
    }
}
