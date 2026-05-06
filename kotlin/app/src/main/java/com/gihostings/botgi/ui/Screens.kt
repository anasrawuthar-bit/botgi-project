package com.gihostings.botgi.ui

import android.content.Intent
import android.content.Context
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.gihostings.botgi.R
import com.gihostings.botgi.*
import java.time.LocalDateTime
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun LoginScreen(viewModel: MainViewModel) {
    var baseUrl by remember { mutableStateOf("http://192.168.1.4:8000") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.White)
            .padding(22.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Image(
                painter = painterResource(id = R.drawable.app_logo_icon),
                contentDescription = "BotGI",
                modifier = Modifier
                    .width(168.dp)
                    .height(92.dp),
                contentScale = ContentScale.Fit
            )
            Spacer(Modifier.height(14.dp))
            Text("BotGI Technician", color = Color(0xFF0F172A), fontWeight = FontWeight.Bold, fontSize = 28.sp)
            Text("Assigned job workspace", color = Color(0xFF64748B), fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(24.dp))

            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White),
                border = BorderStroke(1.dp, Color(0xFFE2E8F0))
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Technician Login", fontWeight = FontWeight.Bold, fontSize = 20.sp)
                    OutlinedTextField(
                        value = baseUrl,
                        onValueChange = { baseUrl = it },
                        label = { Text("Server URL") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp)
                    )
                    OutlinedTextField(
                        value = username,
                        onValueChange = { username = it },
                        label = { Text("Username") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp)
                    )
                    OutlinedTextField(
                        value = password,
                        onValueChange = { password = it },
                        label = { Text("Password") },
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp)
                    )
                    Button(
                        onClick = { viewModel.login(baseUrl, username, password) },
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                        shape = RoundedCornerShape(10.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE6A100))
                    ) {
                        if (viewModel.isLoading.value) {
                            CircularProgressIndicator(color = Color.White, modifier = Modifier.size(22.dp))
                        } else {
                            Text("Login")
                        }
                    }
                }
            }

            viewModel.error.value?.let {
                Spacer(Modifier.height(14.dp))
                ErrorBanner(it)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(viewModel: MainViewModel, onJobClick: (String) -> Unit) {
    var searchQuery by remember { mutableStateOf("") }
    var showHistory by remember { mutableStateOf(false) }
    var selectedHistoryMonth by remember { mutableStateOf<YearMonth?>(null) }

    val jobs = viewModel.jobs.value
    val activeJobs = jobs.filter { it.isActiveForTechnician() }
    val historyJobs = jobs.filter { it.isFinishedForTechnician() }
    val searchResults = if (searchQuery.isBlank()) emptyList() else jobs.filter { it.matchesTechnicianSearch(searchQuery) }
    val historyMonths = remember(historyJobs) { historyJobs.availableHistoryMonths() }
    val visibleHistory = if (showHistory) historyJobs.filterHistoryMonth(selectedHistoryMonth) else emptyList()

    LaunchedEffect(historyMonths) {
        val selectedMonth = selectedHistoryMonth
        selectedHistoryMonth = when {
            historyMonths.isEmpty() -> null
            selectedMonth == null -> historyMonths.first()
            historyMonths.none { it == selectedMonth } -> historyMonths.first()
            else -> selectedMonth
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Technician Dashboard", fontWeight = FontWeight.Bold)
                        Text(
                            "Welcome, ${viewModel.username.ifBlank { "Technician" }}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.refreshJobs() }) {
                        Icon(Icons.Default.Refresh, "Refresh")
                    }
                    IconButton(onClick = { viewModel.logout() }) {
                        Icon(Icons.Default.ExitToApp, "Logout")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .background(Color.White)
        ) {
            if (viewModel.isLoading.value) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }

            LazyColumn(
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    SearchPanel(
                        value = searchQuery,
                        onValueChange = { searchQuery = it },
                        onClear = { searchQuery = "" }
                    )
                }

                if (searchQuery.isNotBlank()) {
                    item {
                        InfoBanner("Found ${searchResults.size} job(s) matching \"$searchQuery\"")
                    }
                    item {
                        DashboardSectionHeader("Search Results", searchResults.size)
                    }
                    if (searchResults.isEmpty()) {
                        item { EmptyStateCard("No jobs matched this search.") }
                    } else {
                        items(searchResults, key = { "search-${it.jobCode}" }) { job ->
                            TechnicianDashboardJobCard(
                                job = job,
                                onOpen = { onJobClick(job.jobCode) },
                                onAction = { action ->
                                    viewModel.runAction(job.jobCode, action) { viewModel.refreshJobs() }
                                }
                            )
                        }
                    }
                }

                item {
                    DashboardSectionHeader("My Active Jobs", activeJobs.size)
                }
                if (activeJobs.isEmpty()) {
                    item { EmptyStateCard("No active jobs currently assigned to you.") }
                } else {
                    items(activeJobs, key = { "active-${it.jobCode}" }) { job ->
                        TechnicianDashboardJobCard(
                            job = job,
                            onOpen = { onJobClick(job.jobCode) },
                            onAction = { action ->
                                viewModel.runAction(job.jobCode, action) { viewModel.refreshJobs() }
                            }
                        )
                    }
                }

                item {
                    HistoryPanelHeader(
                        count = historyJobs.size,
                        expanded = showHistory,
                        onToggle = { showHistory = !showHistory }
                    )
                }
                if (showHistory) {
                    item {
                        HistoryMonthFilter(
                            months = historyMonths,
                            selected = selectedHistoryMonth,
                            onSelected = { selectedHistoryMonth = it }
                        )
                    }
                    item {
                        DashboardSectionHeader(
                            selectedHistoryMonth?.historyLabel() ?: "History Jobs",
                            visibleHistory.size
                        )
                    }
                    if (visibleHistory.isEmpty()) {
                        item { EmptyStateCard("No completed/closed jobs in this month.") }
                    } else {
                        items(visibleHistory, key = { "history-${it.jobCode}" }) { job ->
                            TechnicianDashboardJobCard(
                                job = job,
                                onOpen = { },
                                onAction = { },
                                readOnly = true
                            )
                        }
                    }
                    item { HistoryTotalsCard(visibleHistory) }
                }

                viewModel.error.value?.let { error ->
                    item { ErrorBanner(error) }
                }
            }
        }
    }
}

@Composable
fun TechnicianSummaryCard(activeCount: Int, newCount: Int, historyCount: Int, technicianId: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF082F49))
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("Technician View", color = Color(0xFFBAE6FD), fontWeight = FontWeight.Bold)
            Text(
                if (technicianId.isBlank()) "Assigned jobs only" else "ID $technicianId",
                color = Color.White,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SummaryMetric("Active", activeCount.toString(), Color(0xFF38BDF8), Modifier.weight(1f))
                SummaryMetric("New", newCount.toString(), Color(0xFFFBBF24), Modifier.weight(1f))
                SummaryMetric("History", historyCount.toString(), Color(0xFF2DD4BF), Modifier.weight(1f))
            }
        }
    }
}

@Composable
fun SummaryMetric(label: String, value: String, accent: Color, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        color = Color(0xFF0C4A6E),
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, Color(0xFF0E7490))
    ) {
        Column(
            modifier = Modifier.padding(vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(value, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text(label, color = accent, fontWeight = FontWeight.Bold, fontSize = 11.sp)
        }
    }
}

@Composable
fun SearchPanel(value: String, onValueChange: (String) -> Unit, onClear: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Column(Modifier.padding(14.dp)) {
            Text("Search Jobs", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("Job code, customer, phone, or device") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                trailingIcon = {
                    if (value.isNotBlank()) {
                        IconButton(onClick = onClear) {
                            Icon(Icons.Default.Close, "Clear")
                        }
                    }
                },
                singleLine = true,
                shape = RoundedCornerShape(10.dp)
            )
        }
    }
}

@Composable
fun DashboardSectionHeader(title: String, count: Int) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(title, fontWeight = FontWeight.Bold, fontSize = 21.sp, modifier = Modifier.weight(1f))
        CountBadge(count.toString())
    }
}

@Composable
fun TechnicianDashboardJobCard(
    job: JobSummary,
    onOpen: () -> Unit,
    onAction: (String) -> Unit,
    readOnly: Boolean = false
) {
    val context = LocalContext.current
    var confirmReturn by remember { mutableStateOf(false) }
    val accent = statusColor(job.status)

    if (confirmReturn) {
        AlertDialog(
            onDismissRequest = { confirmReturn = false },
            title = { Text("Return to Staff") },
            text = { Text("Return ${job.jobCode} to staff for reassignment?") },
            confirmButton = {
                TextButton(onClick = {
                    confirmReturn = false
                    onAction("return_to_staff")
                }) { Text("Return") }
            },
            dismissButton = {
                TextButton(onClick = { confirmReturn = false }) { Text("Cancel") }
            }
        )
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Column {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .background(accent)
            )
            Column(modifier = Modifier.padding(14.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text("JOB CODE", color = Color(0xFF64748B), fontWeight = FontWeight.Bold, fontSize = 10.sp)
                        Text(job.jobCode, color = Color(0xFF0B3A63), fontWeight = FontWeight.Bold, fontSize = 17.sp)
                    }
                    StatusBadge(job.status)
                }

                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    SmallPill("Updated ${job.updatedAt}")
                    if (job.isNewAssignment) SmallPill("NEW", Color(0xFFDC2626))
                }

                Spacer(Modifier.height(12.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CustomerAvatar(job.customerName)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            job.customerName.ifBlank { "-" },
                            fontWeight = FontWeight.Bold,
                            fontSize = 19.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        Text(
                            job.customerPhone.ifBlank { "Phone not set" },
                            color = Color(0xFF475569),
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }

                Spacer(Modifier.height(10.dp))
                InfoPanel(
                    label = "Device",
                    value = job.device.ifBlank { "-" },
                    badge = if (job.returnedFromVendor) "Returned from Vendor" else ""
                )

                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    AmountTile("Parts", job.partTotal, Modifier.weight(1f))
                    AmountTile("Service", job.serviceTotal, Modifier.weight(1f))
                    AmountTile("Total", job.total, Modifier.weight(1f), strong = true)
                }

                if (readOnly) {
                    Spacer(Modifier.height(10.dp))
                    InfoBanner("History job. Open Job option is disabled here.")
                } else {
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = {
                                if (job.customerPhone.isNotBlank()) {
                                    context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${job.customerPhone}")))
                                }
                            },
                            modifier = Modifier.weight(1f).height(44.dp),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            Icon(Icons.Default.Call, null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("Call")
                        }
                        Button(
                            onClick = onOpen,
                            modifier = Modifier.weight(1f).height(44.dp),
                            shape = RoundedCornerShape(10.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE6A100))
                        ) {
                            Text("Open Job")
                        }
                    }

                    if (job.isNewAssignment) {
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(
                                onClick = { onAction("acknowledge") },
                                modifier = Modifier.weight(1f).height(44.dp),
                                shape = RoundedCornerShape(10.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF166534))
                            ) {
                                Text("Acknowledge")
                            }
                            Button(
                                onClick = { confirmReturn = true },
                                modifier = Modifier.weight(1f).height(44.dp),
                                shape = RoundedCornerShape(10.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB91C1C))
                            ) {
                                Text("Return")
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun HistoryPanelHeader(count: Int, expanded: Boolean, onToggle: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("History (Completed & Closed)", fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.weight(1f))
            CountBadge(count.toString())
            Spacer(Modifier.width(8.dp))
            OutlinedButton(onClick = onToggle, shape = RoundedCornerShape(10.dp)) {
                Text(if (expanded) "Hide" else "Expand")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryMonthFilter(months: List<YearMonth>, selected: YearMonth?, onSelected: (YearMonth) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val selectedLabel = selected?.historyLabel() ?: if (months.isEmpty()) "No months yet" else "Select month"

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Column(Modifier.padding(14.dp)) {
            Text("Filter History by Month", color = Color(0xFF64748B), fontWeight = FontWeight.Bold, fontSize = 12.sp)
            Spacer(Modifier.height(8.dp))
            ExposedDropdownMenuBox(
                expanded = expanded,
                onExpandedChange = { if (months.isNotEmpty()) expanded = !expanded }
            ) {
                OutlinedTextField(
                    value = selectedLabel,
                    onValueChange = {},
                    readOnly = true,
                    enabled = months.isNotEmpty(),
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                    modifier = Modifier.menuAnchor().fillMaxWidth(),
                    shape = RoundedCornerShape(10.dp)
                )
                ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    months.forEach { month ->
                        DropdownMenuItem(
                            text = { Text(month.historyLabel()) },
                            onClick = {
                                onSelected(month)
                                expanded = false
                            }
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun FilterChipButton(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    if (selected) {
        Button(onClick = onClick, modifier = modifier.height(42.dp), shape = RoundedCornerShape(10.dp)) { Text(label, fontSize = 12.sp) }
    } else {
        OutlinedButton(onClick = onClick, modifier = modifier.height(42.dp), shape = RoundedCornerShape(10.dp)) { Text(label, fontSize = 12.sp) }
    }
}

@Composable
fun HistoryTotalsCard(jobs: List<JobSummary>) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Column(Modifier.padding(14.dp)) {
            Text("History Totals", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AmountTile("Parts", formatTotal(jobs.map { it.partTotal }), Modifier.weight(1f), raw = true)
                AmountTile("Service", formatTotal(jobs.map { it.serviceTotal }), Modifier.weight(1f), raw = true)
                AmountTile("Total", formatTotal(jobs.map { it.total }), Modifier.weight(1f), strong = true, raw = true)
            }
        }
    }
}

@Composable
fun EmptyStateCard(message: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White)
    ) {
        Text(
            message,
            modifier = Modifier.padding(22.dp).fillMaxWidth(),
            color = Color(0xFF64748B),
            fontWeight = FontWeight.Medium
        )
    }
}

@Composable
fun InfoBanner(message: String) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFEFF6FF),
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFBFDBFE))
    ) {
        Text(message, modifier = Modifier.padding(12.dp), color = Color(0xFF1E40AF), fontWeight = FontWeight.Bold)
    }
}

@Composable
fun ErrorBanner(message: String) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFFEF2F2),
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFFECACA))
    ) {
        Text(message, modifier = Modifier.padding(12.dp), color = Color(0xFF991B1B), fontWeight = FontWeight.Bold)
    }
}

@Composable
fun CountBadge(value: String) {
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = Color(0xFFF1F5F9),
        border = BorderStroke(1.dp, Color(0xFFCBD5E1))
    ) {
        Text(value, modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp), fontWeight = FontWeight.Bold, fontSize = 12.sp)
    }
}

@Composable
fun CustomerAvatar(name: String) {
    Box(
        modifier = Modifier.size(48.dp).background(Color(0xFF0B3A63), RoundedCornerShape(12.dp)),
        contentAlignment = Alignment.Center
    ) {
        Text(name.trim().firstOrNull()?.uppercaseChar()?.toString() ?: "?", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp)
    }
}

@Composable
fun SmallPill(value: String, color: Color = Color(0xFF475569)) {
    Surface(
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(999.dp),
        border = BorderStroke(1.dp, if (color == Color(0xFF475569)) Color(0xFFE2E8F0) else color)
    ) {
        Text(value, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp), color = color, fontWeight = FontWeight.Bold, fontSize = 11.sp)
    }
}

@Composable
fun InfoPanel(label: String, value: String, badge: String = "") {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0))
    ) {
        Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(label, color = Color(0xFF64748B), fontWeight = FontWeight.Bold, fontSize = 11.sp)
                Text(value, color = Color(0xFF0F172A), fontWeight = FontWeight.Bold, fontSize = 15.sp)
            }
            if (badge.isNotBlank()) SmallPill(badge, Color(0xFF16A34A))
        }
    }
}

@Composable
fun AmountTile(label: String, value: String, modifier: Modifier = Modifier, strong: Boolean = false, raw: Boolean = false) {
    Surface(
        modifier = modifier,
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0))
    ) {
        Column(modifier = Modifier.padding(vertical = 9.dp, horizontal = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, color = Color(0xFF64748B), fontWeight = FontWeight.Bold, fontSize = 11.sp)
            Text(
                if (raw) value else money(value),
                color = if (strong) Color(0xFF0F766E) else Color(0xFF0F172A),
                fontWeight = if (strong) FontWeight.Bold else FontWeight.Medium,
                fontSize = 13.sp,
                maxLines = 1
            )
        }
    }
}

@Composable
fun StatusBadge(status: String) {
    val color = statusColor(status)
    Surface(
        color = color.copy(alpha = 0.1f),
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, color)
    ) {
        Text(
            status,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
            style = MaterialTheme.typography.bodySmall,
            color = color,
            fontWeight = FontWeight.Bold
        )
    }
}

private fun JobSummary.isActiveForTechnician(): Boolean {
    return status !in setOf("Completed", "Closed", "Ready for Pickup", "Ready for pickup", "Ready", "Returned")
}

private fun JobSummary.isFinishedForTechnician(): Boolean {
    return status in setOf("Completed", "Closed", "Ready for Pickup", "Ready for pickup", "Ready")
}

private fun JobSummary.matchesTechnicianSearch(query: String): Boolean {
    val normalized = query.lowercase(Locale.US)
    return listOf(jobCode, customerName, customerPhone, device, status).any {
        it.lowercase(Locale.US).contains(normalized)
    }
}

private fun List<JobSummary>.availableHistoryMonths(): List<YearMonth> =
    mapNotNull { it.updatedYearMonth() }.distinct().sortedDescending()

private fun List<JobSummary>.filterHistoryMonth(month: YearMonth?): List<JobSummary> =
    if (month == null) this else filter { it.updatedYearMonth() == month }

private fun YearMonth.historyLabel(): String =
    format(DateTimeFormatter.ofPattern("MMMM yyyy", Locale.US))

private fun JobSummary.updatedYearMonth(): YearMonth? {
    return try {
        YearMonth.from(LocalDateTime.parse(updatedAt, DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")))
    } catch (_: Exception) {
        null
    }
}

private fun statusColor(status: String): Color {
    return when (status) {
        "Pending", "Under Inspection" -> Color(0xFFF59E0B)
        "Repairing", "Specialized Service" -> Color(0xFF14B8A6)
        "Completed", "Ready for Pickup", "Ready for pickup", "Ready" -> Color(0xFF2563EB)
        "Closed" -> Color(0xFF64748B)
        else -> Color(0xFF0B3A63)
    }
}

private fun money(value: String): String = "Rs ${value.ifBlank { "0.00" }}"

private fun formatTotal(values: List<String>): String {
    val total = values.sumOf { it.toDoubleOrNull() ?: 0.0 }
    return "Rs ${String.format(Locale.US, "%.2f", total)}"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JobDetailScreen(jobCode: String, viewModel: MainViewModel, onBack: () -> Unit) {
    var jobDetail by remember { mutableStateOf<JobDetail?>(null) }
    var confirmSpecialized by remember { mutableStateOf(false) }
    
    LaunchedEffect(jobCode) {
        viewModel.getJobDetail(jobCode) { detail ->
            jobDetail = detail
        }
    }

    fun reload() {
        viewModel.getJobDetail(jobCode) { detail ->
            jobDetail = detail
        }
    }

    if (confirmSpecialized && jobDetail != null) {
        AlertDialog(
            onDismissRequest = { confirmSpecialized = false },
            title = { Text("Request Specialized Service") },
            text = { Text("Send ${jobDetail!!.jobCode} to staff for vendor/specialized service assignment?") },
            confirmButton = {
                TextButton(onClick = {
                    confirmSpecialized = false
                    viewModel.runAction(jobDetail!!.jobCode, "request_specialized_service") {
                        reload()
                        viewModel.refreshJobs()
                    }
                }) { Text("Send") }
            },
            dismissButton = { TextButton(onClick = { confirmSpecialized = false }) { Text("Cancel") } }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Job Details", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, null)
                    }
                },
                actions = {
                    IconButton(onClick = { reload() }) {
                        Icon(Icons.Default.Refresh, "Refresh")
                    }
                }
            )
        }
    ) { padding ->
        if (jobDetail == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else {
            val job = jobDetail!!
            LazyColumn(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
                    .background(Color.White),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item { JobDetailHero(job) }
                item {
                    UpdateStatusAndInspectionCard(
                        job = job,
                        onSave = { status, notes, answers ->
                            viewModel.updateTechnicianJob(job.jobCode, status, notes, answers) { reload() }
                        }
                    )
                }
                item {
                    SpecializedServiceRequestCard(
                        job = job,
                        onRequest = { confirmSpecialized = true }
                    )
                }
                item {
                    ServiceEntryCard(
                        job = job,
                        onAddLine = { description, part, service ->
                            viewModel.addServiceLine(job.jobCode, description, part, service) { reload() }
                        }
                    )
                }
                item {
                    ServiceLogsCard(
                        job = job,
                        onUpdateLine = { line, description, part, service ->
                            viewModel.updateServiceLine(job.jobCode, line.id, description, part, service) { reload() }
                        }
                    )
                }
                item { BillingDetailCard(job) }
                item { PhotosDetailCard(job, viewModel.authToken) }
                viewModel.error.value?.let { error ->
                    item { ErrorBanner(error) }
                }
            }
        }
    }
}

@Composable
fun JobDetailHero(job: JobDetail) {
    val context = LocalContext.current
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0))
    ) {
        Column {
            Box(Modifier.fillMaxWidth().height(4.dp).background(statusColor(job.status)))
            Column(Modifier.padding(14.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text("JOB CODE", color = Color(0xFF64748B), fontWeight = FontWeight.Bold, fontSize = 10.sp)
                        Text(job.jobCode, color = Color(0xFF0B3A63), fontWeight = FontWeight.Bold, fontSize = 19.sp)
                    }
                    StatusBadge(job.statusDisplay.ifBlank { job.status })
                }
                Spacer(Modifier.height(12.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CustomerAvatar(job.customerName)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(job.customerName.ifBlank { "-" }, fontSize = 21.sp, fontWeight = FontWeight.Bold)
                        Text(job.customerPhone.ifBlank { "Phone not set" }, color = Color(0xFF475569))
                    }
                    OutlinedButton(
                        onClick = {
                            if (job.customerPhone.isNotBlank()) {
                                context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${job.customerPhone}")))
                            }
                        },
                        shape = RoundedCornerShape(10.dp)
                    ) {
                        Icon(Icons.Default.Call, null, Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Call")
                    }
                }
                Spacer(Modifier.height(12.dp))
                InfoPanel("Device", formattedDevice(job))
                if (job.deviceSerial.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    InfoPanel("Serial", job.deviceSerial)
                }
                if (job.reportedIssue.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    InfoPanel("Reported Issue", job.reportedIssue)
                }
                if (job.additionalItems.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    InfoPanel("Additional Items", job.additionalItems)
                }
            }
        }
    }
}

@Composable
fun UpdateStatusAndInspectionCard(
    job: JobDetail,
    onSave: (String, String, Map<String, String>) -> Unit
) {
    val initialStatus = remember(job.jobCode, job.status, job.statusChoices) {
        if (job.statusChoices.any { it.value == job.status }) {
            job.status
        } else {
            job.statusChoices.firstOrNull()?.value.orEmpty()
        }
    }
    var selectedStatus by remember(job.jobCode, initialStatus) { mutableStateOf(initialStatus) }
    var notes by remember(job.jobCode, job.technicianNotes) { mutableStateOf(job.technicianNotes) }
    var warningMessage by remember(job.jobCode) { mutableStateOf("") }
    val answers = remember(job.jobCode, job.checklistFields) {
        mutableStateMapOf<String, String>().apply {
            job.checklistFields.forEach { put(it.key, it.value) }
        }
    }

    DetailCard("Update Status & Inspection") {
        if (!job.permissions.canChangeStatus || !job.canChangeStatus) {
            WarningBanner("Status locked. This job is with vendor for specialized service.")
        }
        if (warningMessage.isNotBlank()) {
            WarningBanner(warningMessage)
        }
        StatusDropdown(
            label = "Change Status",
            choices = job.statusChoices,
            selected = selectedStatus,
            enabled = job.permissions.canChangeStatus && job.canChangeStatus,
            onSelected = {
                selectedStatus = it
                warningMessage = ""
            }
        )
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = notes,
            onValueChange = { notes = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Technician Notes") },
            minLines = 3,
            shape = RoundedCornerShape(10.dp)
        )

        if (job.checklistFields.isNotEmpty()) {
            Spacer(Modifier.height(14.dp))
            Text(job.checklistTitle.ifBlank { "Device Checklist" }, fontWeight = FontWeight.Bold, fontSize = 17.sp)
            if (job.checklistNotes.isNotBlank()) {
                Text(job.checklistNotes, color = Color(0xFF64748B), style = MaterialTheme.typography.bodySmall)
            }
            Text(
                if (job.checklistRequiredForCompletion) "Required fields must be filled before Completed." else "Checklist is optional for this job.",
                color = Color(0xFF64748B),
                style = MaterialTheme.typography.bodySmall
            )
            Spacer(Modifier.height(8.dp))
            job.checklistFields.forEach { field ->
                ChecklistInput(
                    field = field,
                    value = answers[field.key].orEmpty(),
                    onChange = {
                        answers[field.key] = it
                        warningMessage = ""
                    }
                )
                Spacer(Modifier.height(8.dp))
            }
        }

        Button(
            onClick = {
                val missingRequired = if (selectedStatus == "Completed") {
                    job.checklistFields
                        .filter { it.required && answers[it.key].orEmpty().trim().isBlank() }
                        .map { it.label }
                } else {
                    emptyList()
                }
                when {
                    selectedStatus.isBlank() -> warningMessage = "Select a valid status before updating."
                    missingRequired.isNotEmpty() -> {
                        val preview = missingRequired.take(6).joinToString(", ")
                        val suffix = if (missingRequired.size > 6) "..." else ""
                        warningMessage = "Complete required checklist fields before marking completed: $preview$suffix"
                    }
                    else -> {
                        warningMessage = ""
                        onSave(selectedStatus, notes, answers.toMap())
                    }
                }
            },
            modifier = Modifier.fillMaxWidth().height(48.dp),
            shape = RoundedCornerShape(10.dp),
            enabled = job.permissions.canChangeStatus && job.canChangeStatus && selectedStatus.isNotBlank(),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF0B3A63))
        ) {
            Text("Update Job")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatusDropdown(
    label: String,
    choices: List<StatusChoice>,
    selected: String,
    enabled: Boolean,
    onSelected: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    val selectedLabel = choices.firstOrNull { it.value == selected }?.label ?: selected
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { if (enabled) expanded = !expanded }
    ) {
        OutlinedTextField(
            value = selectedLabel,
            onValueChange = {},
            readOnly = true,
            enabled = enabled,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier.menuAnchor().fillMaxWidth(),
            shape = RoundedCornerShape(10.dp)
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            choices.forEach { choice ->
                DropdownMenuItem(
                    text = { Text(choice.label) },
                    onClick = {
                        onSelected(choice.value)
                        expanded = false
                    }
                )
            }
        }
    }
}

@Composable
fun ChecklistInput(field: ChecklistField, value: String, onChange: (String) -> Unit) {
    Column {
        Text(field.label + if (field.required) " *" else "", fontWeight = FontWeight.Bold, color = Color(0xFF0F172A))
        when (field.type) {
            "checkbox" -> Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = value == "1", onCheckedChange = { onChange(if (it) "1" else "") })
                Text(field.helpText.ifBlank { "Mark as verified" })
            }
            "select" -> SimpleValueDropdown(options = field.options, selected = value, onSelected = onChange)
            "textarea" -> OutlinedTextField(
                value = value,
                onValueChange = onChange,
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(field.placeholder) },
                minLines = 2,
                shape = RoundedCornerShape(10.dp)
            )
            else -> OutlinedTextField(
                value = value,
                onValueChange = onChange,
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(field.placeholder) },
                singleLine = true,
                shape = RoundedCornerShape(10.dp)
            )
        }
        if (field.helpText.isNotBlank() && field.type != "checkbox") {
            Text(field.helpText, color = Color(0xFF64748B), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SimpleValueDropdown(options: List<String>, selected: String, onSelected: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = !expanded }) {
        OutlinedTextField(
            value = selected,
            onValueChange = {},
            readOnly = true,
            placeholder = { Text("-- Select --") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier.menuAnchor().fillMaxWidth(),
            shape = RoundedCornerShape(10.dp)
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { option ->
                DropdownMenuItem(text = { Text(option) }, onClick = {
                    onSelected(option)
                    expanded = false
                })
            }
        }
    }
}

@Composable
fun SpecializedServiceRequestCard(job: JobDetail, onRequest: () -> Unit) {
    DetailCard("Specialized Service Request") {
        Text("For chip-level repair or external vendor work, send this job to staff.", color = Color(0xFF64748B))
        if (job.specializedService.exists) {
            Spacer(Modifier.height(8.dp))
            InfoPanel(
                "Current Request",
                job.specializedService.statusDisplay.ifBlank { job.specializedService.status },
                job.specializedService.vendorName
            )
        }
        Spacer(Modifier.height(10.dp))
        Button(
            onClick = onRequest,
            enabled = job.permissions.canRequestSpecializedService,
            modifier = Modifier.fillMaxWidth().height(48.dp),
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE6A100))
        ) {
            Text("Request Specialized Service")
        }
    }
}

@Composable
fun ServiceEntryCard(job: JobDetail, onAddLine: (String, String, String) -> Unit) {
    var description by remember(job.jobCode) { mutableStateOf("") }
    var partCost by remember(job.jobCode) { mutableStateOf("0") }
    var serviceCharge by remember(job.jobCode) { mutableStateOf("0") }
    val lineTotal = (partCost.toDoubleOrNull() ?: 0.0) + (serviceCharge.toDoubleOrNull() ?: 0.0)

    DetailCard("Service Log Actions") {
        if (!job.permissions.canManageServiceLogs) {
            WarningBanner("Manual service log entry is disabled for this job status.")
            return@DetailCard
        }
        OutlinedTextField(
            value = description,
            onValueChange = { description = it },
            label = { Text("Description") },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(10.dp)
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = partCost,
                onValueChange = { partCost = it },
                label = { Text("Part Cost") },
                modifier = Modifier.weight(1f),
                singleLine = true,
                shape = RoundedCornerShape(10.dp)
            )
            OutlinedTextField(
                value = serviceCharge,
                onValueChange = { serviceCharge = it },
                label = { Text("Service Charge") },
                modifier = Modifier.weight(1f),
                singleLine = true,
                shape = RoundedCornerShape(10.dp)
            )
        }
        Spacer(Modifier.height(8.dp))
        Text("Line Total: ${formatTotal(listOf(lineTotal.toString()))}", color = Color(0xFF0B3A63), fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Button(
            onClick = { onAddLine(description, partCost, serviceCharge) },
            modifier = Modifier.fillMaxWidth().height(48.dp),
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF0B3A63))
        ) {
            Text("Add Service")
        }
    }
}

@Composable
fun ServiceLogsCard(job: JobDetail, onUpdateLine: (ServiceLine, String, String, String) -> Unit) {
    DetailCard("Service Logs") {
        if (job.serviceLines.isEmpty()) {
            EmptyStateCard("No service logs for this job yet.")
        } else {
            job.serviceLines.forEach { line ->
                ServiceLineEditableItem(
                    line = line,
                    canEdit = job.permissions.canManageServiceLogs && !line.isProductSale,
                    onSave = { description, part, service ->
                        onUpdateLine(line, description, part, service)
                    }
                )
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
fun ServiceLineEditableItem(
    line: ServiceLine,
    canEdit: Boolean,
    onSave: (String, String, String) -> Unit
) {
    var showEdit by remember(line.id) { mutableStateOf(false) }

    if (showEdit) {
        var description by remember(line.id) { mutableStateOf(line.description) }
        var partCost by remember(line.id) { mutableStateOf(line.partCost) }
        var serviceCharge by remember(line.id) { mutableStateOf(line.serviceCharge) }
        var warning by remember(line.id) { mutableStateOf("") }

        AlertDialog(
            onDismissRequest = { showEdit = false },
            title = { Text("Edit Service Log") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (warning.isNotBlank()) {
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            color = Color(0xFFFFFBEB),
                            shape = RoundedCornerShape(10.dp),
                            border = BorderStroke(1.dp, Color(0xFFFDE68A))
                        ) {
                            Text(
                                warning,
                                modifier = Modifier.padding(10.dp),
                                color = Color(0xFF92400E),
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                    OutlinedTextField(
                        value = description,
                        onValueChange = {
                            description = it
                            warning = ""
                        },
                        label = { Text("Description") },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(10.dp)
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = partCost,
                            onValueChange = { partCost = it },
                            label = { Text("Part") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp)
                        )
                        OutlinedTextField(
                            value = serviceCharge,
                            onValueChange = { serviceCharge = it },
                            label = { Text("Service") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp)
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    if (description.trim().isBlank()) {
                        warning = "Description is required."
                    } else {
                        showEdit = false
                        onSave(description.trim(), partCost, serviceCharge)
                    }
                }) {
                    Text("Save")
                }
            },
            dismissButton = {
                TextButton(onClick = { showEdit = false }) {
                    Text("Cancel")
                }
            }
        )
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0))
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        line.description.ifBlank { "Service line" },
                        color = Color(0xFF0F172A),
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp
                    )
                    Text(
                        "Part ${money(line.partCost)}  |  Service ${money(line.serviceCharge)}",
                        color = Color(0xFF475569),
                        fontSize = 13.sp
                    )
                }
                if (line.isProductSale) {
                    SmallPill("Product", Color(0xFF16A34A))
                } else if (canEdit) {
                    OutlinedButton(
                        onClick = { showEdit = true },
                        shape = RoundedCornerShape(10.dp),
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)
                    ) {
                        Icon(Icons.Default.Edit, null, modifier = Modifier.size(15.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Edit")
                    }
                }
            }
        }
    }
}

@Composable
fun BillingDetailCard(job: JobDetail) {
    DetailCard("Billing") {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            AmountTile("Parts", job.financials.partTotal, Modifier.weight(1f))
            AmountTile("Service", job.financials.serviceTotal, Modifier.weight(1f))
            AmountTile("Total", job.financials.grandTotal, Modifier.weight(1f), strong = true)
        }
    }
}

@Composable
fun PhotosDetailCard(job: JobDetail, authToken: String) {
    var selectedPhoto by remember { mutableStateOf<JobPhoto?>(null) }

    selectedPhoto?.let { photo ->
        val context = LocalContext.current
        Dialog(onDismissRequest = { selectedPhoto = null }) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(16.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White)
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text(
                        photo.name.ifBlank { "Device photo" },
                        fontWeight = FontWeight.Bold,
                        color = Color(0xFF0F172A)
                    )
                    Spacer(Modifier.height(10.dp))
                    AsyncImage(
                        model = photo.authenticatedImageRequest(context, authToken),
                        contentDescription = photo.name.ifBlank { "Device photo" },
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 260.dp, max = 560.dp)
                            .background(Color(0xFFF8FAFC), RoundedCornerShape(12.dp)),
                        contentScale = ContentScale.Fit
                    )
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                        TextButton(onClick = { selectedPhoto = null }) {
                            Text("Close")
                        }
                    }
                }
            }
        }
    }

    DetailCard("Device Photos") {
        if (job.photos.isEmpty()) {
            EmptyStateCard("No photos uploaded yet.")
        } else {
            job.photos.forEachIndexed { index, photo ->
                PhotoPreviewRow(
                    photo = photo,
                    authToken = authToken,
                    onView = { selectedPhoto = photo }
                )
                if (index != job.photos.lastIndex) {
                    Spacer(Modifier.height(10.dp))
                }
            }
        }
    }
}

@Composable
fun PhotoPreviewRow(photo: JobPhoto, authToken: String, onView: () -> Unit) {
    val context = LocalContext.current
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFF8FAFC),
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0))
    ) {
        Row(
            modifier = Modifier
                .clickable(onClick = onView)
                .padding(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            AsyncImage(
                model = photo.authenticatedImageRequest(context, authToken),
                contentDescription = photo.name.ifBlank { "Device photo" },
                modifier = Modifier
                    .size(78.dp)
                    .background(Color.White, RoundedCornerShape(10.dp)),
                contentScale = ContentScale.Crop
            )
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    photo.name.ifBlank { "Device photo" },
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFF0F172A),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                if (photo.uploadedAt.isNotBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(photo.uploadedAt, color = Color(0xFF64748B), style = MaterialTheme.typography.bodySmall)
                }
            }
            OutlinedButton(onClick = onView, shape = RoundedCornerShape(10.dp)) {
                Text("View")
            }
        }
    }
}

private fun JobPhoto.authenticatedImageRequest(context: Context, authToken: String): ImageRequest {
    return ImageRequest.Builder(context)
        .data(url)
        .crossfade(true)
        .apply {
            if (authToken.isNotBlank()) {
                addHeader("Authorization", "Bearer $authToken")
            }
        }
        .build()
}

@Composable
fun TimelineDetailCard(job: JobDetail) {
    DetailCard("Timeline") {
        job.timeline.takeLast(8).forEach { entry ->
            InfoPanel(entry.label, "${entry.timestamp} | ${entry.user}")
            if (entry.details.isNotBlank()) {
                Text(entry.details, color = Color(0xFF475569), modifier = Modifier.padding(horizontal = 6.dp, vertical = 4.dp))
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
fun DetailCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        border = BorderStroke(1.dp, Color(0xFFE2E8F0))
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(title, color = Color(0xFF0F172A), fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}

@Composable
fun WarningBanner(message: String) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFFFFBEB),
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, Color(0xFFFDE68A))
    ) {
        Text(message, modifier = Modifier.padding(12.dp), color = Color(0xFF92400E), fontWeight = FontWeight.Bold)
    }
    Spacer(Modifier.height(10.dp))
}

private fun formattedDevice(job: JobDetail): String {
    return listOf(job.deviceType, job.deviceBrand, job.deviceModel)
        .filter { it.isNotBlank() }
        .joinToString(" ")
        .ifBlank { "-" }
}

@Composable
fun DetailSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
        Card(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f))
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                content()
            }
        }
    }
}

// Temporary FlowRow for Compose until M3 FlowRow is stable/available
@Composable
fun FlowRow(
    modifier: Modifier = Modifier,
    mainAxisSpacing: androidx.compose.ui.unit.Dp = 0.dp,
    crossAxisSpacing: androidx.compose.ui.unit.Dp = 0.dp,
    content: @Composable () -> Unit
) {
    androidx.compose.ui.layout.Layout(
        content = content,
        modifier = modifier
    ) { measurables, constraints ->
        val placeables = measurables.map { it.measure(constraints) }
        val layoutWidth = constraints.maxWidth
        
        var xPosition = 0
        var yPosition = 0
        var maxHeightInRow = 0
        
        layout(layoutWidth, 1000) { // Height is hardcoded for simplicity in this replacement
            placeables.forEach { placeable ->
                if (xPosition + placeable.width > layoutWidth) {
                    xPosition = 0
                    yPosition += maxHeightInRow + crossAxisSpacing.roundToPx()
                    maxHeightInRow = 0
                }
                placeable.placeRelative(xPosition, yPosition)
                xPosition += placeable.width + mainAxisSpacing.roundToPx()
                maxHeightInRow = maxOf(maxHeightInRow, placeable.height)
            }
        }
    }
}
