package com.gihostings.botgi

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.UUID

class BotgiApi(
    private val baseUrl: String,
    private val tokenProvider: () -> String?
) {
    fun login(username: String, password: String): UserSession {
        val payload = JSONObject()
            .put("username", username)
            .put("password", password)
        val response = jsonRequest("POST", "/api/mobile/login/", payload, withAuth = false)
        val user = response.getJSONObject("user")
        return UserSession(
            baseUrl = baseUrl.trim().trimEnd('/'),
            token = response.getString("access_token"),
            username = user.optString("username"),
            role = user.optString("role"),
            technicianId = user.optString("technician_id")
        )
    }

    fun jobs(): List<JobSummary> {
        val response = jsonRequest("GET", "/api/mobile/jobs/")
        return response.optJSONArray("jobs").mapObjects { item ->
            JobSummary(
                jobCode = item.optString("job_code"),
                customerName = item.optString("customer_name"),
                customerPhone = item.optString("customer_phone"),
                device = item.optString("device"),
                status = item.optString("status"),
                updatedAt = item.optString("updated_at"),
                total = item.optString("total"),
                partTotal = item.optString("part_total"),
                serviceTotal = item.optString("service_total"),
                isNewAssignment = item.optBoolean("is_new_assignment"),
                returnedFromVendor = item.optBoolean("returned_from_vendor")
            )
        }
    }

    fun jobDetail(jobCode: String): JobDetail {
        val response = jsonRequest("GET", "/api/mobile/jobs/${jobCode.urlPart()}/")
        val job = response.getJSONObject("job")
        val financials = response.getJSONObject("financials")
        val permissions = response.optJSONObject("permissions") ?: JSONObject()
        val specializedService = response.optJSONObject("specialized_service") ?: JSONObject()
        return JobDetail(
            jobCode = job.optString("job_code"),
            status = job.optString("status"),
            statusDisplay = job.optString("status_display"),
            customerName = job.optString("customer_name"),
            customerPhone = job.optString("customer_phone"),
            deviceType = job.optString("device_type"),
            deviceBrand = job.optString("device_brand"),
            deviceModel = job.optString("device_model"),
            deviceSerial = job.optString("device_serial"),
            reportedIssue = job.optString("reported_issue"),
            additionalItems = job.optString("additional_items"),
            technicianNotes = job.optString("technician_notes"),
            financials = Financials(
                partTotal = financials.optString("part_total"),
                serviceTotal = financials.optString("service_total"),
                subtotal = financials.optString("subtotal"),
                discountAmount = financials.optString("discount_amount"),
                grandTotal = financials.optString("grand_total")
            ),
            serviceLines = response.optJSONArray("service_logs").mapObjects { item ->
                ServiceLine(
                    id = item.optInt("id"),
                    description = item.optString("description"),
                    partCost = item.optString("part_cost"),
                    serviceCharge = item.optString("service_charge"),
                    createdAt = item.optString("created_at"),
                    isProductSale = item.optBoolean("is_product_sale")
                )
            },
            timeline = response.optJSONArray("timeline").mapObjects { item ->
                TimelineEntry(
                    label = item.optString("label"),
                    details = item.optString("details"),
                    timestamp = item.optString("timestamp"),
                    user = item.optString("user")
                )
            },
            actions = response.optJSONArray("available_actions").mapObjects { item ->
                JobAction(
                    key = item.optString("key"),
                    label = item.optString("label")
                )
            },
            permissions = JobPermissions(
                canEditNotes = permissions.optBoolean("can_edit_notes"),
                canManageServiceLogs = permissions.optBoolean("can_manage_service_logs"),
                canChangeStatus = permissions.optBoolean("can_change_status"),
                canRequestSpecializedService = permissions.optBoolean("can_request_specialized_service")
            ),
            statusChoices = response.optJSONArray("status_choices").mapObjects { item ->
                StatusChoice(
                    value = item.optString("value"),
                    label = item.optString("label")
                )
            },
            canChangeStatus = response.optBoolean("can_change_status"),
            checklistRequiredForCompletion = response.optBoolean("checklist_required_for_completion"),
            specializedService = SpecializedServiceInfo(
                exists = specializedService.optBoolean("exists"),
                status = specializedService.optString("status"),
                statusDisplay = specializedService.optString("status_display"),
                vendorName = specializedService.optString("vendor_name"),
                notes = specializedService.optString("notes")
            ),
            checklistTitle = response.optString("technician_checklist_title"),
            checklistNotes = response.optString("technician_checklist_notes"),
            checklistFields = response.optJSONArray("technician_checklist_schema").mapObjects { item ->
                ChecklistField(
                    key = item.optString("key"),
                    label = item.optString("label"),
                    type = item.optString("type"),
                    required = item.optBoolean("required"),
                    placeholder = item.optString("placeholder"),
                    helpText = item.optString("help_text"),
                    options = item.optJSONArray("options").mapStrings(),
                    value = item.optString("value")
                )
            },
            photos = response.optJSONArray("photos").mapObjects { item ->
                JobPhoto(
                    id = item.optInt("id"),
                    name = item.optString("name"),
                    contentType = item.optString("content_type"),
                    uploadedAt = item.optString("uploaded_at"),
                    url = item.optString("url")
                )
            }
        )
    }

    fun updateTechnicianJob(jobCode: String, status: String, notes: String, answers: Map<String, String>) {
        val answerJson = JSONObject()
        answers.forEach { (key, value) -> answerJson.put(key, value) }
        jsonRequest(
            "POST",
            "/api/mobile/jobs/${jobCode.urlPart()}/technician-update/",
            JSONObject()
                .put("status", status)
                .put("technician_notes", notes)
                .put("answers", answerJson)
        )
    }

    fun saveNotes(jobCode: String, notes: String) {
        jsonRequest(
            "POST",
            "/api/mobile/jobs/${jobCode.urlPart()}/notes/",
            JSONObject().put("technician_notes", notes)
        )
    }

    fun saveChecklist(jobCode: String, answers: Map<String, String>) {
        val answerJson = JSONObject()
        answers.forEach { (key, value) -> answerJson.put(key, value) }
        jsonRequest(
            "POST",
            "/api/mobile/jobs/${jobCode.urlPart()}/checklist/",
            JSONObject().put("answers", answerJson)
        )
    }

    fun runAction(jobCode: String, action: String) {
        jsonRequest(
            "POST",
            "/api/mobile/jobs/${jobCode.urlPart()}/action/",
            JSONObject().put("action", action)
        )
    }

    fun addServiceLine(jobCode: String, description: String, partCost: String, serviceCharge: String) {
        jsonRequest(
            "POST",
            "/api/mobile/jobs/${jobCode.urlPart()}/service-lines/",
            JSONObject()
                .put("description", description)
                .put("part_cost", partCost.ifBlank { "0" })
                .put("service_charge", serviceCharge.ifBlank { "0" })
        )
    }

    fun updateServiceLine(jobCode: String, lineId: Int, description: String, partCost: String, serviceCharge: String) {
        jsonRequest(
            "POST",
            "/api/mobile/jobs/${jobCode.urlPart()}/service-lines/$lineId/update/",
            JSONObject()
                .put("description", description)
                .put("part_cost", partCost.ifBlank { "0" })
                .put("service_charge", serviceCharge.ifBlank { "0" })
        )
    }

    fun uploadPhoto(jobCode: String, fileName: String, contentType: String, bytes: ByteArray): List<JobPhoto> {
        val boundary = "Botgi-${UUID.randomUUID()}"
        val connection = openConnection("/api/mobile/jobs/${jobCode.urlPart()}/photos/", "POST")
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        connection.doOutput = true

        connection.outputStream.use { output ->
            output.write("--$boundary\r\n".toByteArray())
            output.write("Content-Disposition: form-data; name=\"photos\"; filename=\"$fileName\"\r\n".toByteArray())
            output.write("Content-Type: $contentType\r\n\r\n".toByteArray())
            output.write(bytes)
            output.write("\r\n--$boundary--\r\n".toByteArray())
        }

        val response = readJsonResponse(connection)
        return response.optJSONArray("photos").mapObjects { item ->
            JobPhoto(
                id = item.optInt("id"),
                name = item.optString("name"),
                contentType = item.optString("content_type"),
                uploadedAt = item.optString("uploaded_at"),
                url = item.optString("url")
            )
        }
    }

    private fun jsonRequest(
        method: String,
        path: String,
        body: JSONObject? = null,
        withAuth: Boolean = true
    ): JSONObject {
        val connection = openConnection(path, method, withAuth)
        connection.setRequestProperty("Accept", "application/json")
        if (body != null) {
            val rawBody = body.toString().toByteArray(StandardCharsets.UTF_8)
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.outputStream.use { it.write(rawBody) }
        }
        return readJsonResponse(connection)
    }

    private fun openConnection(path: String, method: String, withAuth: Boolean = true): HttpURLConnection {
        val root = baseUrl.trim().trimEnd('/')
        val connection = URL("$root$path").openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 15000
        connection.readTimeout = 20000
        if (withAuth) {
            val token = tokenProvider().orEmpty()
            if (token.isNotBlank()) {
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
        }
        return connection
    }

    private fun readJsonResponse(connection: HttpURLConnection): JSONObject {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.use { BufferedInputStream(it).readAllText() }.orEmpty()
        val json = if (text.isNotBlank()) JSONObject(text) else JSONObject()
        if (code !in 200..299) {
            throw BotgiApiException(json.optString("message", "Request failed with HTTP $code"))
        }
        return json
    }
}

class BotgiApiException(message: String) : Exception(message)

private fun JSONArray?.mapStrings(): List<String> {
    if (this == null) return emptyList()
    return List(length()) { index -> optString(index) }
}

private fun <T> JSONArray?.mapObjects(transform: (JSONObject) -> T): List<T> {
    if (this == null) return emptyList()
    return List(length()) { index -> transform(optJSONObject(index) ?: JSONObject()) }
}

private fun BufferedInputStream.readAllText(): String {
    val buffer = ByteArrayOutputStream()
    val bytes = ByteArray(8192)
    while (true) {
        val count = read(bytes)
        if (count <= 0) break
        buffer.write(bytes, 0, count)
    }
    return buffer.toString(StandardCharsets.UTF_8.name())
}

private fun String.urlPart(): String = URLEncoder.encode(this, StandardCharsets.UTF_8.name())
