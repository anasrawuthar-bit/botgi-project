package com.gihostings.botgi

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class BotgiRepository(private val context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("botgi_prefs", Context.MODE_PRIVATE)
    private var api: BotgiApi? = null

    init {
        val baseUrl = prefs.getString("base_url", null)
        val token = prefs.getString("token", null)
        if (baseUrl != null) {
            api = BotgiApi(baseUrl) { prefs.getString("token", null) }
        }
    }

    fun isConfigured(): Boolean = prefs.contains("base_url")
    fun isLoggedIn(): Boolean {
        return prefs.contains("token") &&
            prefs.getString("role", "") == "technician" &&
            !prefs.getString("technician_id", "").isNullOrBlank()
    }

    fun getBaseUrl(): String = prefs.getString("base_url", "") ?: ""
    fun getUsername(): String = prefs.getString("username", "") ?: ""
    fun getTechnicianId(): String = prefs.getString("technician_id", "") ?: ""
    fun getToken(): String = prefs.getString("token", "") ?: ""

    suspend fun login(baseUrl: String, username: String, password: String): Result<UserSession> = withContext(Dispatchers.IO) {
        try {
            val loginApi = BotgiApi(baseUrl) { null }
            val session = loginApi.login(username, password)
            if (session.role != "technician" || session.technicianId.isBlank()) {
                return@withContext Result.failure(IllegalStateException("Technician login required. Use the web app for staff/admin access."))
            }
            prefs.edit()
                .putString("base_url", baseUrl)
                .putString("token", session.token)
                .putString("username", session.username)
                .putString("role", session.role)
                .putString("technician_id", session.technicianId)
                .apply()
            api = BotgiApi(baseUrl) { prefs.getString("token", null) }
            Result.success(session)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    fun logout() {
        prefs.edit()
            .remove("token")
            .remove("role")
            .remove("technician_id")
            .apply()
    }

    suspend fun getJobs(): Result<List<JobSummary>> = withContext(Dispatchers.IO) {
        try {
            Result.success(api?.jobs() ?: emptyList())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getJobDetail(jobCode: String): Result<JobDetail> = withContext(Dispatchers.IO) {
        try {
            Result.success(api!!.jobDetail(jobCode))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun saveNotes(jobCode: String, notes: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            api?.saveNotes(jobCode, notes)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun updateTechnicianJob(jobCode: String, status: String, notes: String, answers: Map<String, String>): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            api?.updateTechnicianJob(jobCode, status, notes, answers)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun addServiceLine(jobCode: String, desc: String, part: String, service: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            api?.addServiceLine(jobCode, desc, part, service)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun updateServiceLine(jobCode: String, lineId: Int, desc: String, part: String, service: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            api?.updateServiceLine(jobCode, lineId, desc, part, service)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun runAction(jobCode: String, action: String): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            api?.runAction(jobCode, action)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun uploadPhoto(jobCode: String, name: String, type: String, bytes: ByteArray): Result<List<JobPhoto>> = withContext(Dispatchers.IO) {
        try {
            Result.success(api!!.uploadPhoto(jobCode, name, type, bytes))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
