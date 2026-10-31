package com.neurotrader.pro

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.neurotrader.pro.ui.C
import com.neurotrader.pro.ui.ConnectScreen
import com.neurotrader.pro.ui.LoginScreen
import com.neurotrader.pro.ui.MainScreen
import com.neurotrader.pro.ui.NTColors
import com.neurotrader.pro.ui.SetupScreen
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val vm: AppVM by viewModels()

    private val notifPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifs.init(this)
        if (Build.VERSION.SDK_INT >= 33) notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)

        // هر بار که اپ به جلو می‌آید، آخرین وضعیت کامل از سرور گرفته می‌شود و اتصال زنده برقرار می‌شود
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                if (vm.screen == Screen.Main) {
                    vm.refreshState()
                    vm.startLive()
                }
            }
        }

        setContent {
            CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                MaterialTheme(colorScheme = NTColors) {
                    val snackbar = remember { SnackbarHostState() }
                    LaunchedEffect(vm.message) {
                        vm.message?.let {
                            snackbar.showSnackbar(it)
                            vm.message = null
                        }
                    }
                    Box(Modifier.fillMaxSize().background(C.bg).systemBarsPadding()) {
                        when (vm.screen) {
                            Screen.Connect, Screen.Setup, Screen.Login -> Scaffold(
                                containerColor = C.bg, snackbarHost = { SnackbarHost(snackbar) }
                            ) { pad ->
                                Box(Modifier.fillMaxSize().background(C.bg).padding(pad)) {
                                    when (vm.screen) {
                                        Screen.Connect -> ConnectScreen(vm)
                                        Screen.Setup -> SetupScreen(vm)
                                        else -> LoginScreen(vm)
                                    }
                                }
                            }
                            Screen.Main -> MainScreen(vm, snackbar)
                        }
                    }
                }
            }
        }
    }

    override fun onStop() {
        super.onStop()
        // در پس‌زمینه اتصال زنده بسته می‌شود؛ هشدارها با WorkManager (هر ۱۵ دقیقه) و ایمیل سرور می‌رسند
        vm.stopLive()
    }
}
