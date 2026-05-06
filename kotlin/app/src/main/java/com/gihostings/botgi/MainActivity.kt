package com.gihostings.botgi

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.gihostings.botgi.ui.DashboardScreen
import com.gihostings.botgi.ui.JobDetailScreen
import com.gihostings.botgi.ui.LoginScreen
import com.gihostings.botgi.ui.theme.BotgiTheme
import kotlinx.coroutines.delay

private const val ASSIGNMENT_SYNC_INTERVAL_MS = 5000L

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()
    private var pendingNotificationJobCode by mutableStateOf<String?>(null)
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BotgiNotifier.ensureChannels(this)
        pendingNotificationJobCode = intent.getStringExtra(BotgiNotifier.EXTRA_JOB_CODE)
        requestNotificationPermissionIfNeeded()
        setContent {
            BotgiTheme {
                BotgiApp(
                    viewModel = viewModel,
                    notificationJobCode = pendingNotificationJobCode,
                    onNotificationJobOpened = { pendingNotificationJobCode = null }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pendingNotificationJobCode = intent.getStringExtra(BotgiNotifier.EXTRA_JOB_CODE)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}

@Composable
fun BotgiApp(
    viewModel: MainViewModel,
    notificationJobCode: String?,
    onNotificationJobOpened: () -> Unit
) {
    val navController = rememberNavController()
    val isLoggedIn = viewModel.isLoggedIn.value
    val context = LocalContext.current

    LaunchedEffect(isLoggedIn) {
        BotgiAssignmentSyncService.setRunning(context, isLoggedIn)
        while (isLoggedIn) {
            delay(ASSIGNMENT_SYNC_INTERVAL_MS)
            viewModel.syncJobs()
        }
    }

    LaunchedEffect(isLoggedIn, notificationJobCode) {
        if (isLoggedIn && !notificationJobCode.isNullOrBlank()) {
            navController.navigate("jobDetail/$notificationJobCode") {
                launchSingleTop = true
            }
            onNotificationJobOpened()
        }
    }

    NavHost(
        navController = navController,
        startDestination = if (isLoggedIn) "dashboard" else "login"
    ) {
        composable("login") {
            LoginScreen(viewModel)
        }
        composable("dashboard") {
            DashboardScreen(viewModel, onJobClick = { jobCode ->
                navController.navigate("jobDetail/$jobCode")
            })
        }
        composable("jobDetail/{jobCode}") { backStackEntry ->
            val jobCode = backStackEntry.arguments?.getString("jobCode") ?: ""
            JobDetailScreen(jobCode, viewModel, onBack = {
                navController.popBackStack()
            })
        }
    }
}
