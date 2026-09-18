from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.http import HttpResponse, Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    CompanyWorkspace, JobTicket, JobTicketLog, ServiceLog,
    SpecializedService, TechnicianProfile, Vendor,
)
from .views import report_views
from .views import staff_views
from .access_control import apply_staff_access
from .views.helpers import get_jobs_for_report_period, get_report_period, report_date_bounds
from .views.vendor_views import _build_vendor_report_context


class ReportConsistencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('report-review-admin', is_staff=True, is_superuser=True)
        cls.workspace = CompanyWorkspace.objects.create(name='Report workspace', owner=cls.admin)
        cls.other_workspace = CompanyWorkspace.objects.create(name='Other workspace', owner=cls.admin)
        tech_user = User.objects.create_user('report-review-tech')
        tech_user.groups.add(Group.objects.get_or_create(name='Technicians')[0])
        cls.technician = TechnicianProfile.objects.create(
            workspace=cls.workspace, user=tech_user, unique_id='RPT001',
        )

    def setUp(self):
        self.today = timezone.localdate()
        self.start, self.end = report_date_bounds(self.today, self.today)
        self.factory = RequestFactory()

    def request(self, **params):
        request = self.factory.get('/staff/reports/', params)
        request.user = self.admin
        request.current_workspace = self.workspace
        return request

    def job(self, code, status='Completed', workspace=None, **kwargs):
        return JobTicket.objects.create(
            job_code=code, workspace=workspace or self.workspace,
            customer_name='Report customer', customer_phone='9876543210',
            device_type='Laptop', reported_issue='Repair', status=status,
            assigned_to=self.technician, **kwargs,
        )

    def transition(self, job, status, timestamp):
        log = JobTicketLog.objects.create(
            job_ticket=job, action='CLOSED' if status == 'Closed' else 'STATUS',
            details=f"Status changed from 'Repairing' to '{status}'.",
        )
        JobTicketLog.objects.filter(pk=log.pk).update(timestamp=timestamp)

    def context(self, view, request=None, *args):
        with patch('job_tickets.views.report_views.render', return_value=HttpResponse('ok')) as render:
            response = view(request or self.request(), *args)
        self.assertEqual(response.status_code, 200)
        return render.call_args.args[2]

    def test_old_job_closed_today_is_in_card_and_detail(self):
        job = self.job('REPORT-OLD-CLOSED', status='Closed', discount_amount=Decimal('20'))
        JobTicket.objects.filter(pk=job.pk).update(created_at=self.start - timedelta(days=20))
        self.transition(job, 'Closed', self.start + timedelta(hours=10))
        ServiceLog.objects.create(job_ticket=job, description='Repair', part_cost=100, service_charge=50)
        dashboard = self.context(report_views.reports_dashboard)
        detail = self.context(report_views.daily_jobs_report, self.request(), self.today.isoformat(), 'out')
        self.assertEqual(dashboard['todays_jobs_out'], 1)
        self.assertEqual([row.pk for row in detail['jobs']], [job.pk])
        self.assertEqual(dashboard['todays_closed_total'], detail['jobs'][0].net_total)
        self.assertEqual(dashboard['todays_closed_total'], Decimal('130'))

    def test_completion_survives_pickup_and_close_and_is_not_duplicated(self):
        job = self.job('REPORT-COMPLETE-CLOSED', status='Closed')
        self.transition(job, 'Completed', self.start + timedelta(hours=9))
        self.transition(job, 'Completed', self.start + timedelta(hours=10))
        self.transition(job, 'Closed', self.start + timedelta(hours=11))
        dashboard = self.context(report_views.reports_dashboard)
        detail = self.context(report_views.daily_jobs_report, self.request(), self.today.isoformat(), 'completed')
        self.assertEqual(dashboard['todays_jobs_completed'], 1)
        self.assertEqual([row.pk for row in detail['jobs']], [job.pk])

    def test_editing_old_completion_does_not_make_it_completed_today(self):
        job = self.job('REPORT-OLD-COMPLETED')
        self.transition(job, 'Completed', self.start - timedelta(days=10))
        JobTicket.objects.filter(pk=job.pk).update(updated_at=self.start + timedelta(hours=10))
        dashboard = self.context(report_views.reports_dashboard)
        detail = self.context(report_views.daily_jobs_report, self.request(), self.today.isoformat(), 'completed')
        self.assertEqual(dashboard['todays_jobs_completed'], 0)
        self.assertEqual(detail['jobs'], [])
        self.assertEqual(get_jobs_for_report_period(self.start, self.end, workspace=self.workspace), [])
        previous = get_jobs_for_report_period(self.start - timedelta(days=10), self.start - timedelta(days=9), workspace=self.workspace)
        self.assertEqual([row.pk for row in previous], [job.pk])

    def test_daily_details_and_returned_count_are_workspace_scoped(self):
        foreign = self.job('REPORT-FOREIGN', 'Closed', workspace=self.other_workspace)
        log = JobTicketLog.objects.create(job_ticket=foreign, action='CLOSED', details="Status changed from 'Returned' to 'Closed'.")
        JobTicketLog.objects.filter(pk=log.pk).update(timestamp=self.start + timedelta(hours=10))
        self.transition(foreign, 'Completed', self.start + timedelta(hours=9))
        for kind in ('in', 'out', 'completed'):
            detail = self.context(report_views.daily_jobs_report, self.request(), self.today.isoformat(), kind)
            self.assertEqual(detail['jobs'], [])
        self.assertEqual(self.context(report_views.reports_dashboard)['returned_count'], 0)

    def test_ready_for_pickup_badge_adds_both_statuses(self):
        self.job('REPORT-COMPLETED')
        self.job('REPORT-READY', 'Ready for Pickup')
        self.assertEqual(self.context(report_views.reports_dashboard)['completed_awaiting_billing_count'], 2)

    def test_closed_job_keeps_audited_date_after_edit_or_backfill(self):
        job = self.job('REPORT-CLOSED-DATE', 'Closed', closed_at=self.start)
        event_time = self.start - timedelta(days=10)
        self.transition(job, 'Closed', event_time)
        self.assertEqual(get_jobs_for_report_period(self.start, self.end, workspace=self.workspace), [])
        rows = get_jobs_for_report_period(event_time, event_time + timedelta(days=1), workspace=self.workspace)
        self.assertEqual([row.pk for row in rows], [job.pk])
        self.assertEqual(rows[0].report_date, event_time)

    def test_technician_dashboard_print_and_csv_share_vendor_return_date(self):
        job = self.job('REPORT-TECH-VENDOR')
        vendor = Vendor.objects.create(workspace=self.workspace, name='Vendor', company_name='Vendor report')
        SpecializedService.objects.create(
            job_ticket=job, vendor=vendor, status='Returned',
            returned_date=self.start + timedelta(hours=12),
        )
        JobTicket.objects.filter(pk=job.pk).update(updated_at=self.start - timedelta(days=20))
        ServiceLog.objects.create(job_ticket=job, description='Repair', part_cost=100, service_charge=50)
        params = {'start_date': self.today.isoformat(), 'end_date': self.today.isoformat()}
        dashboard = self.context(report_views.reports_dashboard, self.request(**params))
        detail = report_views._build_technician_report_context(self.request(**params), self.technician.pk)
        row = dashboard['monthly_tech_performance'][0]
        self.assertEqual(row.jobs_done, detail['jobs_count'])
        self.assertEqual(row.jobs_done, 1)
        self.assertEqual(row.monthly_parts_sales, detail['total_parts'])
        self.assertEqual(row.monthly_service_sales, detail['total_services'])
        response = report_views.technician_report_export_csv(self.request(**params), self.technician.pk)
        self.assertIn(job.job_code, response.content.decode())

    def test_foreign_technician_report_returns_404(self):
        user = User.objects.create_user('foreign-report-tech')
        tech = TechnicianProfile.objects.create(user=user, workspace=self.other_workspace, unique_id='RPT002')
        with self.assertRaises(Http404):
            report_views._build_technician_report_context(self.request(), tech.pk)

    def test_vendor_dashboard_and_detail_include_returned_unclosed_jobs(self):
        vendor = Vendor.objects.create(workspace=self.workspace, name='Vendor', company_name='Returned vendor')
        job = self.job('REPORT-VENDOR-READY', 'Ready for Pickup')
        SpecializedService.objects.create(
            job_ticket=job, vendor=vendor, status='Returned',
            returned_date=self.end - timedelta(microseconds=1), vendor_cost=100, client_charge=150,
        )
        params = {'start_date': self.today.isoformat(), 'end_date': self.today.isoformat()}
        dashboard = self.context(report_views.reports_dashboard, self.request(**params))
        detail = _build_vendor_report_context(self.request(**params), vendor.pk)
        row = list(dashboard['vendor_performance'])[0]
        self.assertEqual(row.total_jobs_given, 1)
        self.assertEqual(row.total_jobs_given, detail['total_jobs'])
        self.assertEqual(row.total_vendor_cost, detail['total_vendor_cost'])
        self.assertEqual(row.total_client_charge, detail['total_client_charge'])

    def test_period_includes_last_fractional_second_but_not_next_day(self):
        first = self.job('REPORT-LAST-SECOND')
        second = self.job('REPORT-NEXT-DAY')
        self.transition(first, 'Completed', self.end - timedelta(microseconds=1))
        self.transition(second, 'Completed', self.end)
        period = get_report_period(self.request(start_date=self.today.isoformat(), end_date=self.today.isoformat()))
        jobs = get_jobs_for_report_period(period['start'], period['end'], workspace=self.workspace)
        self.assertEqual([job.pk for job in jobs], [first.pk])

    def test_reversed_period_is_normalized(self):
        earlier = self.today - timedelta(days=3)
        period = get_report_period(self.request(start_date=self.today.isoformat(), end_date=earlier.isoformat()))
        self.assertEqual(period['start_date_str'], earlier.isoformat())
        self.assertEqual(period['end_date_str'], self.today.isoformat())

    def test_chart_buckets_do_not_include_jobs_outside_selected_days(self):
        inside = self.job('REPORT-CHART-IN')
        outside = self.job('REPORT-CHART-OUT')
        self.transition(inside, 'Completed', self.start + timedelta(hours=10))
        self.transition(outside, 'Completed', self.end + timedelta(hours=10))
        response = report_views.reports_chart_data(self.request(start_date=self.today.isoformat(), end_date=self.today.isoformat()))
        import json
        payload = json.loads(response.content)
        self.assertEqual(payload['monthly'][0]['jobs_finished'], 1)
        self.assertEqual(payload['yearly'][0]['jobs_finished'], 1)

    def test_dashboard_tabs_render_with_shared_period_and_financial_exports(self):
        self.client.force_login(self.admin)
        for tab, heading in [('overview', "Today's activity"), ('financial', 'Financial summary'),
                             ('technician', 'Technician performance'), ('vendor', 'Vendor performance')]:
            response = self.client.get(reverse('reports_dashboard'), {
                'tab': tab, 'start_date': self.today.isoformat(), 'end_date': self.today.isoformat(),
            })
            self.assertContains(response, heading)
            self.assertContains(response, f'name="tab" value="{tab}"')
        self.assertNotContains(response, 'chart.js')

    def test_financial_tab_matches_printed_summary_after_old_job_edit(self):
        job = self.job('REPORT-FINANCIAL', 'Closed', closed_at=self.start - timedelta(days=10))
        self.transition(job, 'Closed', self.start + timedelta(hours=10))
        ServiceLog.objects.create(job_ticket=job, description='Repair', part_cost=100, service_charge=50)
        request = self.request(tab='financial', start_date=self.today.isoformat(), end_date=self.today.isoformat())
        dashboard = self.context(report_views.reports_dashboard, request)
        printed = self.context(report_views.print_monthly_summary_report, request)
        for key in ('overall_revenue', 'overall_expense', 'overall_profit', 'jobs_closed_count'):
            self.assertEqual(dashboard['financial_summary'][key], printed[key])
        self.assertEqual(printed['jobs_closed_count'], 1)
        self.assertEqual(printed['overall_revenue'], Decimal('150'))

    def test_archive_drilldowns_are_workspace_scoped(self):
        local = self.job('REPORT-ARCHIVE-LOCAL', 'Ready for Pickup')
        self.job('REPORT-ARCHIVE-FOREIGN', 'Ready for Pickup', workspace=self.other_workspace)
        for view, args in [(staff_views.staff_job_archive_view, ()),
                           (staff_views.staff_job_filtered_archive_view, ('CompletedReady',))]:
            response = view(self.request(), *args)
            self.assertContains(response, local.job_code)
            self.assertNotContains(response, 'REPORT-ARCHIVE-FOREIGN')

    def test_financial_tab_is_hidden_without_financial_section_access(self):
        user = User.objects.create_user('reports-overview-only', is_staff=True)
        apply_staff_access(user, {'reports_dashboard'})
        request = self.request(tab='financial')
        request.user = user
        response = report_views.reports_dashboard(request)
        self.assertContains(response, "Today's activity")
        self.assertNotContains(response, 'Revenue after discounts')
        self.assertNotContains(response, 'Export CSV')
