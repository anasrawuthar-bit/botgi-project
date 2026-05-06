package com.gihostings.botgi

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private const val ASSIGNMENT_BACKGROUND_SYNC_INTERVAL_MS = 5000L

class BotgiAssignmentSyncService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var repository: BotgiRepository
    private lateinit var notifier: BotgiNotifier
    private var syncJob: Job? = null
    private var loadedJobsOnce = false
    private var knownVisibleJobCodes: Set<String> = emptySet()

    override fun onCreate() {
        super.onCreate()
        repository = BotgiRepository(this)
        notifier = BotgiNotifier(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!repository.isLoggedIn()) {
            stopSelf()
            return START_NOT_STICKY
        }

        startForeground(BotgiNotifier.SYNC_NOTIFICATION_ID, notifier.buildSyncNotification())
        if (syncJob?.isActive != true) {
            syncJob = scope.launch { runSyncLoop() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        syncJob?.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private suspend fun runSyncLoop() {
        while (currentCoroutineContext().isActive) {
            if (!repository.isLoggedIn()) {
                stopSelf()
                break
            }
            repository.getJobs().onSuccess { jobs ->
                val newAssignments = if (loadedJobsOnce) {
                    jobs.filter { it.shouldNotifyForNewAssignment() && it.jobCode !in knownVisibleJobCodes }
                } else {
                    emptyList()
                }
                knownVisibleJobCodes = jobs.map { it.jobCode }.toSet()
                loadedJobsOnce = true
                newAssignments.forEach { notifier.notifyNewAssignment(it) }
            }
            delay(ASSIGNMENT_BACKGROUND_SYNC_INTERVAL_MS)
        }
    }

    companion object {
        fun setRunning(context: Context, shouldRun: Boolean) {
            val intent = Intent(context, BotgiAssignmentSyncService::class.java)
            if (shouldRun) {
                ContextCompat.startForegroundService(context, intent)
            } else {
                context.stopService(intent)
            }
        }
    }
}

private fun JobSummary.shouldNotifyForNewAssignment(): Boolean {
    return isNewAssignment &&
        status !in setOf("Completed", "Closed", "Ready for Pickup", "Ready for pickup", "Ready", "Returned")
}
