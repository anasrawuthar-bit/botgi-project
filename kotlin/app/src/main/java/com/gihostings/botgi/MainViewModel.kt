package com.gihostings.botgi

import android.app.Application
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val repository = BotgiRepository(application)
    private val notifier = BotgiNotifier(application)
    private var loadedJobsOnce = false
    private var knownVisibleJobCodes: Set<String> = emptySet()

    private val _jobs = mutableStateOf<List<JobSummary>>(emptyList())
    val jobs: State<List<JobSummary>> = _jobs

    private val _isLoading = mutableStateOf(false)
    val isLoading: State<Boolean> = _isLoading

    private val _error = mutableStateOf<String?>(null)
    val error: State<String?> = _error

    private val _isLoggedIn = mutableStateOf(repository.isLoggedIn())
    val isLoggedIn: State<Boolean> = _isLoggedIn

    val username: String
        get() = repository.getUsername()

    val technicianId: String
        get() = repository.getTechnicianId()

    val authToken: String
        get() = repository.getToken()

    init {
        if (_isLoggedIn.value) {
            refreshJobs()
        }
    }

    fun login(baseUrl: String, user: String, pass: String) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.login(baseUrl, user, pass)
                .onSuccess {
                    _isLoggedIn.value = true
                    refreshJobs()
                }
                .onFailure {
                    _error.value = it.message ?: "Login failed"
                }
            _isLoading.value = false
        }
    }

    fun logout() {
        repository.logout()
        _isLoggedIn.value = false
        _jobs.value = emptyList()
        knownVisibleJobCodes = emptySet()
        loadedJobsOnce = false
        notifier.clearAssignmentMarks()
    }

    fun refreshJobs() {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.getJobs()
                .onSuccess { applyJobs(it, notifyNewAssignments = true) }
                .onFailure { _error.value = it.message }
            _isLoading.value = false
        }
    }

    fun getJobDetail(jobCode: String, onResult: (JobDetail?) -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.getJobDetail(jobCode)
                .onSuccess { onResult(it) }
                .onFailure { _error.value = it.message; onResult(null) }
            _isLoading.value = false
        }
    }

    fun runAction(jobCode: String, action: String, onDone: () -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.runAction(jobCode, action)
                .onSuccess { onDone() }
                .onFailure { _error.value = it.message }
            _isLoading.value = false
        }
    }

    fun syncJobs() {
        if (!_isLoggedIn.value) return
        viewModelScope.launch {
            repository.getJobs()
                .onSuccess { applyJobs(it, notifyNewAssignments = true) }
                .onFailure {
                    if (_jobs.value.isEmpty()) {
                        _error.value = it.message
                    }
                }
        }
    }

    private fun applyJobs(jobs: List<JobSummary>, notifyNewAssignments: Boolean) {
        val newAssignments = if (notifyNewAssignments && loadedJobsOnce) {
            jobs.filter { it.shouldNotifyForNewAssignment() && it.jobCode !in knownVisibleJobCodes }
        } else {
            emptyList()
        }

        _jobs.value = jobs
        knownVisibleJobCodes = jobs.map { it.jobCode }.toSet()
        loadedJobsOnce = true
        newAssignments.forEach { notifier.notifyNewAssignment(it) }
    }

    private fun JobSummary.shouldNotifyForNewAssignment(): Boolean {
        return isNewAssignment &&
            status !in setOf("Completed", "Closed", "Ready for Pickup", "Ready for pickup", "Ready", "Returned")
    }

    fun updateTechnicianJob(jobCode: String, status: String, notes: String, answers: Map<String, String>, onDone: () -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.updateTechnicianJob(jobCode, status, notes, answers)
                .onSuccess { onDone() }
                .onFailure { _error.value = it.message }
            _isLoading.value = false
        }
    }

    fun addServiceLine(jobCode: String, description: String, partCost: String, serviceCharge: String, onDone: () -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.addServiceLine(jobCode, description, partCost, serviceCharge)
                .onSuccess { onDone() }
                .onFailure { _error.value = it.message }
            _isLoading.value = false
        }
    }

    fun updateServiceLine(jobCode: String, lineId: Int, description: String, partCost: String, serviceCharge: String, onDone: () -> Unit) {
        viewModelScope.launch {
            _isLoading.value = true
            _error.value = null
            repository.updateServiceLine(jobCode, lineId, description, partCost, serviceCharge)
                .onSuccess { onDone() }
                .onFailure { _error.value = it.message }
            _isLoading.value = false
        }
    }
}
