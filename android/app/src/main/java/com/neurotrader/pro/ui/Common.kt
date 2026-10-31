package com.neurotrader.pro.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

object C {
    val bg = Color(0xFF0B1220)
    val card = Color(0xFF131C2E)
    val card2 = Color(0xFF1A2540)
    val text = Color(0xFFE5E9F0)
    val muted = Color(0xFF8A96AD)
    val green = Color(0xFF34D399)
    val red = Color(0xFFF87171)
    val blue = Color(0xFF60A5FA)
    val amber = Color(0xFFFBBF24)
}

val NTColors: ColorScheme = darkColorScheme(
    primary = C.blue, secondary = C.green, background = C.bg, surface = C.card, onSurface = C.text,
    onBackground = C.text, error = C.red, surfaceVariant = C.card2, onSurfaceVariant = C.muted,
)

@Composable
fun Section(title: String, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = C.card), shape = RoundedCornerShape(14.dp)
    ) {
        Column(Modifier.padding(14.dp)) {
            if (title.isNotEmpty()) {
                Text(title, color = C.text, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                Spacer(Modifier.size(8.dp))
            }
            content()
        }
    }
}

@Composable
fun KV(k: String, v: String, color: Color = C.text) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(k, color = C.muted, fontSize = 13.sp)
        Text(v, color = color, fontSize = 13.sp, fontWeight = FontWeight.Medium, textAlign = TextAlign.End)
    }
}

@Composable
fun Stat(label: String, value: String, color: Color = C.text, modifier: Modifier = Modifier) {
    Column(modifier.padding(4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, color = color, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text(label, color = C.muted, fontSize = 11.sp)
    }
}

@Composable
fun Dot(ok: Boolean) {
    Spacer(Modifier.size(10.dp).clip(CircleShape).background(if (ok) C.green else C.red))
}

@Composable
fun StatusRow(label: String, ok: Boolean, detail: String = "") {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Dot(ok)
        Spacer(Modifier.width(8.dp))
        Text(label, color = C.text, fontSize = 13.sp, modifier = Modifier.weight(1f))
        Text(detail, color = C.muted, fontSize = 12.sp)
    }
}

@Composable
fun Muted(text: String) = Text(text, color = C.muted, fontSize = 12.sp)

@Composable
fun Body(text: String, color: Color = C.text) = Text(text, color = color, fontSize = 13.sp, lineHeight = 20.sp)

fun pnlColor(v: Double): Color = when {
    v > 0 -> C.green
    v < 0 -> C.red
    else -> C.text
}

fun Double.f(d: Int = 2): String = String.format(Locale.US, "%.${d}f", this)
fun Double.signed(d: Int = 2): String = (if (this > 0) "+" else "") + this.f(d)

fun JSONObject.d(key: String, def: Double = 0.0): Double = if (isNull(key)) def else optDouble(key, def).let { if (it.isNaN()) def else it }
fun JSONObject.s(key: String, def: String = ""): String = if (isNull(key)) def else optString(key, def)
fun JSONObject.o(key: String): JSONObject = optJSONObject(key) ?: JSONObject()
fun JSONObject.a(key: String): JSONArray = optJSONArray(key) ?: JSONArray()

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONArray.strings(): List<String> = (0 until length()).map { optString(it) }

fun dirFa(d: Int) = if (d > 0) "خرید" else "فروش"

val REGIME_FA = mapOf("trending" to "روندی", "ranging" to "رنج", "volatile" to "پرنوسان", "quiet" to "کم‌نوسان")
val SESSION_FA = mapOf("asia" to "آسیا", "london" to "لندن", "newyork" to "نیویورک", "overlap" to "هم‌پوشانی", "off" to "خارج از سشن")
val MODE_FA = mapOf("demo" to "دمو", "paper" to "شبیه‌سازی", "live" to "واقعی")
