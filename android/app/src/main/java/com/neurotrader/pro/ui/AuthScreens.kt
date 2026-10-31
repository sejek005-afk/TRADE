package com.neurotrader.pro.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.neurotrader.pro.AppVM

@Composable
private fun AuthFrame(title: String, subtitle: String, content: @Composable () -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp), horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(Modifier.height(40.dp))
        Text("نوروترید پرو", color = C.green, fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Text(title, color = C.text, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Muted(subtitle)
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
fun BusyButton(text: String, busy: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = enabled && !busy, modifier = Modifier.fillMaxWidth().height(50.dp)) {
        if (busy) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text(text)
    }
}

@Composable
fun ConnectScreen(vm: AppVM) {
    var addr by remember { mutableStateOf(vm.store.server.removePrefix("https://")) }
    AuthFrame("اتصال به سرور", "آدرس IP سرور VPS (پورت پیش‌فرض 8810)") {
        OutlinedTextField(addr, { addr = it }, label = { Text("مثلاً 185.1.2.3:8810") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        BusyButton("اتصال", vm.busy, addr.isNotBlank()) { vm.connect(addr) }
        Muted("اتصال فقط با HTTPS انجام می‌شود. بار اول اثر انگشت گواهی سرور را با فایل FINGERPRINT.txt روی سرور مقایسه کنید.")
    }
    val fp = vm.pendingFingerprint
    if (fp != null) {
        AlertDialog(
            onDismissRequest = { vm.pendingFingerprint = null },
            title = { Text("تأیید اثر انگشت سرور") },
            text = {
                Column {
                    Body("این اثر انگشت باید دقیقاً با چیزی که در پنجره‌ی موتور یا فایل data\\FINGERPRINT.txt چاپ شده یکی باشد:")
                    Spacer(Modifier.height(8.dp))
                    Text(fp, color = C.amber, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            },
            confirmButton = { TextButton(onClick = { vm.acceptFingerprint() }) { Text("یکی است، اعتماد کن") } },
            dismissButton = { TextButton(onClick = { vm.pendingFingerprint = null }) { Text("انصراف") } }
        )
    }
}

@Composable
fun SetupScreen(vm: AppVM) {
    val ctx = LocalContext.current
    val secret = vm.totpSecret
    if (secret == null) {
        var code by remember { mutableStateOf("") }
        var user by remember { mutableStateOf("admin") }
        var pass by remember { mutableStateOf("") }
        var pass2 by remember { mutableStateOf("") }
        AuthFrame("راه‌اندازی اولیه", "کد راه‌اندازی در فایل data\\SETUP_CODE.txt روی سرور است") {
            OutlinedTextField(code, { code = it.uppercase() }, label = { Text("کد راه‌اندازی") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(user, { user = it }, label = { Text("نام کاربری") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pass, { pass = it }, label = { Text("رمز (حداقل ۱۰ کاراکتر)") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(pass2, { pass2 = it }, label = { Text("تکرار رمز") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            BusyButton("ادامه", vm.busy, code.isNotBlank() && user.isNotBlank() && pass.length >= 10 && pass == pass2) {
                vm.setup(code, user, pass)
            }
            TextButton(onClick = { vm.resetServer() }) { Text("تغییر سرور") }
        }
    } else {
        var otp by remember { mutableStateOf("") }
        AuthFrame("ورود دومرحله‌ای", "این کلید را در Google Authenticator یا هر اپ TOTP اضافه کنید") {
            Text(secret.s("secret"), color = C.amber, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            TextButton(onClick = {
                val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("totp", secret.s("secret")))
            }) { Text("کپی کلید") }
            TextButton(onClick = {
                runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(secret.s("uri")))) }
            }) { Text("باز کردن در اپ Authenticator") }
            OutlinedTextField(otp, { otp = it.filter(Char::isDigit).take(6) }, label = { Text("کد ۶ رقمی") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
            BusyButton("تأیید", vm.busy, otp.length == 6) { vm.confirmSetup(otp) }
        }
    }
}

@Composable
fun LoginScreen(vm: AppVM) {
    var user by remember { mutableStateOf(vm.store.username.ifEmpty { "admin" }) }
    var pass by remember { mutableStateOf("") }
    var otp by remember { mutableStateOf("") }
    AuthFrame("ورود", vm.store.server) {
        OutlinedTextField(user, { user = it }, label = { Text("نام کاربری") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(pass, { pass = it }, label = { Text("رمز") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        OutlinedTextField(otp, { otp = it.filter(Char::isDigit).take(6) }, label = { Text("کد دومرحله‌ای") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
        BusyButton("ورود", vm.busy, user.isNotBlank() && pass.isNotBlank() && otp.length == 6) { vm.login(user, pass, otp) }
        TextButton(onClick = { vm.resetServer() }) { Text("تغییر سرور") }
    }
}
