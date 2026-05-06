package com.gihostings.botgi

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kotlin.math.absoluteValue

class BotgiNotifier(private val context: Context) {
    private val prefs = context.getSharedPreferences("botgi_notifications", Context.MODE_PRIVATE)

    init {
        ensureChannels(context)
    }

    fun notifyNewAssignment(job: JobSummary) {
        if (!canPostNotifications()) return
        val mark = job.assignmentNotificationMark()
        val notifiedMarks = prefs.getStringSet(PREF_NOTIFIED_ASSIGNMENTS, emptySet()).orEmpty()
        if (mark in notifiedMarks) return

        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_JOB_CODE, job.jobCode)
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            job.jobCode.stableNotificationId(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
        val title = "New job assigned"
        val message = "${job.jobCode} - ${job.customerName} - ${job.device}"

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setSound(soundUri)
            .setDefaults(Notification.DEFAULT_SOUND or Notification.DEFAULT_VIBRATE)
            .build()

        runCatching {
            NotificationManagerCompat.from(context)
                .notify(job.jobCode.stableNotificationId(), notification)
            prefs.edit()
                .putStringSet(PREF_NOTIFIED_ASSIGNMENTS, (notifiedMarks + mark).toList().takeLast(200).toSet())
                .apply()
        }
    }

    fun clearAssignmentMarks() {
        prefs.edit().remove(PREF_NOTIFIED_ASSIGNMENTS).apply()
    }

    fun buildSyncNotification(): Notification {
        val intent = Intent(context, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            context,
            SYNC_NOTIFICATION_ID,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(context, SYNC_CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("BotGI technician sync")
            .setContentText("Watching for assigned jobs")
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun canPostNotifications(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
    }

    companion object {
        const val EXTRA_JOB_CODE = "extra_job_code"
        const val SYNC_NOTIFICATION_ID = 7001
        private const val CHANNEL_ID = "technician_assignments_v1"
        private const val SYNC_CHANNEL_ID = "technician_sync_v1"
        private const val PREF_NOTIFIED_ASSIGNMENTS = "notified_assignments"

        fun ensureChannels(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

            val soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
            val audioAttributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Technician Assignments",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Alerts technicians when a new job is assigned."
                enableVibration(true)
                setSound(soundUri, audioAttributes)
            }
            val manager = context.getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
            val syncChannel = NotificationChannel(
                SYNC_CHANNEL_ID,
                "Technician Sync",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Keeps technician assignment alerts active in the background."
                setSound(null, null)
                enableVibration(false)
            }
            manager?.createNotificationChannel(syncChannel)
        }
    }
}

private fun String.stableNotificationId(): Int =
    hashCode().takeUnless { it == Int.MIN_VALUE }?.absoluteValue ?: 1

private fun JobSummary.assignmentNotificationMark(): String =
    "$jobCode|$updatedAt|$isNewAssignment"
