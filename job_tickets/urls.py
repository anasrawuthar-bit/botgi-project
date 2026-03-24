# job_tickets/urls.py
from django.urls import path
from . import views
from . import whatsapp_views

urlpatterns = [
    # Public-facing views
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    path('unauthorized/', views.unauthorized, name='unauthorized'),
    path('client-login/', views.client_login, name='client_login'),
    path('client-status/<str:job_code>/', views.client_status, name='client_status'),
    path('client-bill/<str:job_code>/', views.client_bill_view, name='client_bill_view'),
    path('qr/<str:job_code>/', views.qr_access, name='qr_access'),
    path('client-receipt/<str:job_code>/', views.job_creation_receipt_public_view, name='job_creation_receipt_public'),

    # Staff-facing views
    path('staff-dashboard/', views.staff_dashboard, name='staff_dashboard'),
    path('staff/clients/', views.client_dashboard, name='client_dashboard'),
    path('staff/products/', views.product_dashboard, name='product_dashboard'),
    path('staff/inventory/products/', views.product_dashboard, name='inventory_product_dashboard'),
    path('staff/inventory/', views.inventory_dashboard, name='inventory_dashboard'),
    path('staff/inventory/parties/', views.inventory_party_dashboard, name='inventory_party_dashboard'),
    path('staff/inventory/parties/quick-add/', views.inventory_quick_add_party, name='inventory_quick_add_party'),
    path('staff/inventory/invoice-preview/', views.inventory_invoice_preview, name='inventory_invoice_preview'),
    path('staff/inventory/purchase/', views.inventory_purchase_dashboard, name='inventory_purchase_dashboard'),
    path('staff/inventory/purchase-return/', views.inventory_purchase_return_dashboard, name='inventory_purchase_return_dashboard'),
    path('staff/inventory/sales/', views.inventory_sales_dashboard, name='inventory_sales_dashboard'),
    path('staff/inventory/sales/print/bill/<int:bill_id>/', views.inventory_sales_print_bill_view, name='inventory_sales_print_bill_view'),
    path('staff/inventory/sales/print/<str:invoice_number>/', views.inventory_sales_print_view, name='inventory_sales_print_view'),
    path('staff/inventory/sales-return/', views.inventory_sales_return_dashboard, name='inventory_sales_return_dashboard'),
    path('staff/inventory/products/quick-add/', views.inventory_quick_add_product, name='inventory_quick_add_product'),
    path('staff/vendors/', views.vendor_dashboard, name='vendor_dashboard'),
    path('staff/vendors/<int:vendor_id>/edit/', views.edit_vendor, name='edit_vendor'),
    path('staff/vendors/<int:vendor_id>/delete/', views.delete_vendor, name='delete_vendor'),
    path('job-created/<str:job_code>/', views.job_creation_success, name='job_creation_success'),
    path('staff/billing/<str:job_code>/', views.job_billing_staff, name='job_billing_staff'),
    path('staff/reports/', views.reports_dashboard, name='reports_dashboard'), 
    path('staff/reports/chart-data/', views.reports_chart_data, name='reports_chart_data'),
    path('staff/feedback-analytics/', views.feedback_analytics, name='feedback_analytics'),
    path('staff/company-profile/', views.company_profile_settings, name='company_profile_settings'),
    path('staff/reports/daily/<str:date_str>/<str:filter_type>/', views.daily_jobs_report, name='daily_jobs_report'),
    path('staff/reports/vendor/<int:vendor_id>/', views.vendor_report_detail, name='vendor_report_detail'), # <--- ADD THIS LINE
    path('staff/job/ready-for-pickup/<str:job_code>/', views.mark_ready_for_pickup, name='mark_ready_for_pickup'),
    path('staff/receipt/print/<str:job_code>/', views.job_creation_receipt_print_view, name='job_creation_receipt_print'),
    path('staff/reports/pending/print/', views.print_pending_jobs_report, name='print_pending_jobs_report'),
    path('staff/reports/monthly/print/', views.print_monthly_summary_report, name='print_monthly_summary_report'),
    path('staff/reports/monthly/export/csv/', views.export_monthly_summary_csv, name='export_monthly_summary_csv'),
    path('staff/reports/monthly/print/pdf-layout/', views.print_monthly_summary_pdf, name='print_monthly_summary_pdf'),

    # Technician-facing views
    path('technician-dashboard/', views.technician_dashboard, name='technician_dashboard'),
    path('technician-dashboard/<str:job_code>/', views.job_detail_technician, name='job_detail_technician'),
    path('technician/job/<str:job_code>/acknowledge/', views.technician_acknowledge_assignment, name='technician_acknowledge_assignment'),
    path('technician/job/<str:job_code>/return-to-staff/', views.technician_return_to_staff, name='technician_return_to_staff'),
    path('technician/service-log/<int:log_id>/delete/', views.technician_delete_service_log, name='technician_delete_service_log'),
    path('job/<str:job_code>/request-specialized-service/', views.request_specialized_service, name='request_specialized_service'), # <
    path('specialized-service/<int:service_id>/mark-returned/', views.mark_service_returned, name='mark_service_returned'), # <--- ADD THIS LINE
    path('staff/job/close/<str:job_code>/', views.close_job, name='close_job'),
    path('api/job-status/', views.get_job_status_data, name='get_job_status_data'),
    path('api/client-phone-lookup/', views.client_phone_lookup, name='client_phone_lookup'),
    path('api/mobile/login/', views.mobile_api_login, name='mobile_api_login'),
    path('api/mobile/me/', views.mobile_api_me, name='mobile_api_me'),
    path('api/mobile/jobs/', views.mobile_api_jobs, name='mobile_api_jobs'),
    path('api/mobile/jobs/<str:job_code>/', views.mobile_api_job_detail, name='mobile_api_job_detail'),
    path('api/mobile/jobs/<str:job_code>/action/', views.mobile_api_job_action, name='mobile_api_job_action'),
    path('api/mobile/jobs/<str:job_code>/notes/', views.mobile_api_job_notes, name='mobile_api_job_notes'),
    path('api/mobile/jobs/<str:job_code>/service-lines/', views.mobile_api_service_line_create, name='mobile_api_service_line_create'),
    path(
        'api/mobile/jobs/<str:job_code>/service-lines/<int:line_id>/update/',
        views.mobile_api_service_line_update,
        name='mobile_api_service_line_update',
    ),
    path(
        'api/mobile/jobs/<str:job_code>/service-lines/<int:line_id>/delete/',
        views.mobile_api_service_line_delete,
        name='mobile_api_service_line_delete',
    ),
    path('api/mobile/products/', views.mobile_api_products, name='mobile_api_products'),
    path('api/mobile/products/<int:product_id>/update/', views.mobile_api_product_update, name='mobile_api_product_update'),
    path('api/mobile/clients/', views.mobile_api_clients, name='mobile_api_clients'),
    path('api/mobile/clients/<int:client_id>/update/', views.mobile_api_client_update, name='mobile_api_client_update'),
    path('api/mobile/approvals/pending/', views.mobile_api_pending_approvals, name='mobile_api_pending_approvals'),
    path(
        'api/mobile/approvals/pending/<int:assignment_id>/action/',
        views.mobile_api_pending_approval_action,
        name='mobile_api_pending_approval_action',
    ),
    path('api/mobile/reports/summary/', views.mobile_api_reports_summary, name='mobile_api_reports_summary'),
    path('api/whatsapp/bridge/status/', whatsapp_views.whatsapp_bridge_status_api, name='whatsapp_bridge_status_api'),
    path('api/whatsapp/bridge/logout/', whatsapp_views.whatsapp_bridge_logout_api, name='whatsapp_bridge_logout_api'),
    path('api/whatsapp/bridge/test-send/', whatsapp_views.whatsapp_bridge_test_send_api, name='whatsapp_bridge_test_send_api'),

    # from chatgpt
    path("assignment/<int:pk>/respond/", views.assignment_respond, name="assignment_respond"),
    path("job/<str:job_code>/start/", views.job_mark_started, name="job_mark_started"),
    path("job/<str:job_code>/complete/", views.job_mark_completed, name="job_mark_completed"),
    path('staff/billing/print/<str:job_code>/', views.job_billing_print_view, name='job_billing_print_view'),
    path('reports/technician/<int:tech_id>/print/', views.technician_report_print, name='technician_report_print'),
    path('staff/technician-reports/', views.staff_technician_reports, name='staff_technician_reports'),

    # gemini
    path('staff/job/<str:job_code>/', views.staff_job_detail, name='staff_job_detail'),
    path('staff/job/<str:job_code>/photos/<int:photo_id>/file/', views.staff_job_photo_file, name='staff_job_photo_file'),
    path('staff/job/<str:job_code>/photos/<int:photo_id>/delete/', views.staff_delete_job_photo, name='staff_delete_job_photo'),
    path('staff/job/<str:job_code>/unlock-vendor-details/', views.unlock_vendor_details, name='unlock_vendor_details'),
    path('staff/job/<str:job_code>/lock-vendor-details/', views.lock_vendor_details, name='lock_vendor_details'),
    path('api/all-jobs/', views.api_all_jobs, name='api_all_jobs'),
    path('staff/reports/active-workload/print/', views.print_active_workload_report, name='print_active_workload_report'),
    path('staff/job/<str:job_code>/reassign/', views.job_reassign_staff, name='job_reassign_staff'),
    path('staff/job-archive/', views.staff_job_archive_view, name='staff_job_archive_view'),
    path('staff/job-archive/<str:status_code>/', views.staff_job_filtered_archive_view, name='staff_job_filtered_archive_view'),
    path('staff/technicians/', views.staff_technicians, name='staff_technicians'),
    path('staff/technicians/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('staff/technicians/<int:user_id>/change-password/', views.change_user_password, name='change_user_password'),
    path('staff/technicians/<int:user_id>/delete/', views.delete_user, name='delete_user'),

]
