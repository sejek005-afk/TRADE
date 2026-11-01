package com.neurotrader.pro.ui

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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
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
    var code by remember { mutableStateOf("") }
    AuthFrame("اتصال به سرور", "فقط یک بار. بعد از آن اپ همیشه مستقیم باز می‌شود و رمز نمی‌خواهد.") {
        OutlinedTextField(addr, { addr = it }, label = { Text("آدرس سرور، مثلاً 185.1.2.3:8810") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        OutlinedTextField(code, { code = it.uppercase().filter(Char::isLetterOrDigit).take(8) }, label = { Text("کد اتصال (۸ حرف)") },
            singleLine = true, modifier = Modifier.fillMaxWidth())
        BusyButton("اتصال", vm.busy, addr.isNotBlank() && code.length >= 6) { vm.connect(addr, code) }
        Muted("کد اتصال روی سرور در فایل C:\\NeuroTraderPro\\engine\\data\\SETUP_CODE.txt است.")
        if (vm.store.server.isNotEmpty()) TextButton(onClick = { vm.resetServer() }) { Text("پاک کردن سرور قبلی") }
    }
}
