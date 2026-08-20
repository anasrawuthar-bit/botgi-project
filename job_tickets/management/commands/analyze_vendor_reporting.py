from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from job_tickets.models import JobTicket, SpecializedService
from job_tickets.views import get_jobs_for_report_period

class Command(BaseCommand):
    help = 'Analyze vendor reporting concept implementation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=str,
            help='Month to analyze (YYYY-MM format, e.g., 2025-12)',
        )
        parser.add_argument(
            '--show-details',
            action='store_true',
            help='Show detailed job information',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== Vendor Reporting Concept Analysis ===\n'))
        
        # Determine period
        if options['month']:
            try:
                year, month = map(int, options['month'].split('-'))
                start_date = timezone.make_aware(datetime(year, month, 1))
                if month == 12:
                    end_date = timezone.make_aware(datetime(year + 1, 1, 1))
                else:
                    end_date = timezone.make_aware(datetime(year, month + 1, 1))
                period_name = f"{start_date.strftime('%B %Y')}"
            except ValueError:
                self.stdout.write(self.style.ERROR('Invalid month format. Use YYYY-MM'))
                return
        else:
            # Current month
            today = timezone.localdate()
            start_date = timezone.make_aware(datetime(today.year, today.month, 1))
            if today.month == 12:
                end_date = timezone.make_aware(datetime(today.year + 1, 1, 1))
            else:
                end_date = timezone.make_aware(datetime(today.year, today.month + 1, 1))
            period_name = f"{start_date.strftime('%B %Y')} (Current Month)"

        self.stdout.write(f"Analysis Period: {period_name}")
        self.stdout.write(f"Date Range: {start_date.date()} to {end_date.date()}\n")

        # Get all jobs in the period using vendor concept
        reportable_jobs = get_jobs_for_report_period(start_date, end_date)
        
        # Categorize jobs
        regular_jobs = [job for job in reportable_jobs if not job.is_vendor_job()]
        vendor_jobs = [job for job in reportable_jobs if job.is_vendor_job()]
        
        self.stdout.write(f"Total Reportable Jobs: {len(reportable_jobs)}")
        self.stdout.write(f"  - Regular Jobs: {len(regular_jobs)}")
        self.stdout.write(f"  - Vendor Jobs: {len(vendor_jobs)}\n")

        # Show vendor jobs that are still with vendors (not reportable)
        pending_vendor_jobs = JobTicket.objects.filter(
            specialized_service__status='Sent to Vendor'
        ).select_related('specialized_service', 'specialized_service__vendor')
        
        if pending_vendor_jobs.exists():
            self.stdout.write(self.style.WARNING(f"Jobs Still With Vendors (Not Reportable): {pending_vendor_jobs.count()}"))
            for job in pending_vendor_jobs:
                vendor_name = job.specialized_service.vendor.company_name if job.specialized_service.vendor else "Unassigned"
                sent_date = job.specialized_service.sent_date.date() if job.specialized_service.sent_date else "Unknown"
                self.stdout.write(f"  - {job.job_code}: With {vendor_name} since {sent_date}")
            self.stdout.write("")

        if options['show_details']:
            self.stdout.write(self.style.SUCCESS("=== Detailed Job Information ===\n"))
            
            if regular_jobs:
                self.stdout.write("Regular Jobs (Reported by Completion Date):")
                for job in regular_jobs:
                    report_date = job.get_report_date()
                    self.stdout.write(f"  {job.job_code}: {job.status} on {report_date.date()}")
                self.stdout.write("")
            
            if vendor_jobs:
                self.stdout.write("Vendor Jobs (Reported by Return Date):")
                for job in vendor_jobs:
                    report_date = job.get_report_date()
                    vendor_service = job.specialized_service
                    vendor_name = vendor_service.vendor.company_name if vendor_service.vendor else "Unknown"
                    sent_date = vendor_service.sent_date.date() if vendor_service.sent_date else "Unknown"
                    returned_date = vendor_service.returned_date.date() if vendor_service.returned_date else "Unknown"
                    
                    self.stdout.write(f"  {job.job_code}: {vendor_name}")
                    self.stdout.write(f"    Sent: {sent_date}, Returned: {returned_date}")
                    self.stdout.write(f"    Reported: {report_date.date()}")
                self.stdout.write("")

        # Summary
        self.stdout.write(self.style.SUCCESS("=== Summary ==="))
        self.stdout.write("The vendor concept ensures that:")
        self.stdout.write("1. Regular jobs are reported when completed/closed")
        self.stdout.write("2. Vendor jobs are ONLY reported when returned from vendor")
        self.stdout.write("3. Jobs still with vendors don't appear in reports")
        self.stdout.write("4. This gives accurate monthly performance metrics")