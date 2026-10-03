from decimal import Decimal
from django.db import migrations


def seed_default_accounts(apps, schema_editor):
    CompanyWorkspace = apps.get_model('job_tickets', 'CompanyWorkspace')
    FinancialAccount = apps.get_model('job_tickets', 'FinancialAccount')
    CompanyProfile = apps.get_model('job_tickets', 'CompanyProfile')

    for workspace in CompanyWorkspace.objects.all():
        # Cash account
        if not FinancialAccount.objects.filter(workspace=workspace, account_type='cash').exists():
            FinancialAccount.objects.create(
                workspace=workspace,
                name="Cash in Hand",
                account_type='cash',
                opening_balance=Decimal('0.00'),
                current_balance=Decimal('0.00'),
                is_default_cash=True,
                is_active=True,
            )

        # Bank account
        if not FinancialAccount.objects.filter(workspace=workspace, account_type__in=['bank', 'upi_wallet']).exists():
            profile = CompanyProfile.objects.filter(workspace=workspace).first()
            bank_name = (profile.bank_name if profile and profile.bank_name else "Federal Bank").strip()
            FinancialAccount.objects.create(
                workspace=workspace,
                name=f"{bank_name} - Pattambi" if bank_name == "Federal Bank" else bank_name,
                account_type='bank',
                bank_name=bank_name,
                account_number=profile.account_number if profile and profile.account_number else "99980108152444",
                ifsc_code=profile.ifsc_code if profile and profile.ifsc_code else "FDRL0001412",
                branch=profile.branch if profile and profile.branch else "Pattambi",
                upi_id=profile.upi_id if profile and profile.upi_id else "anasrawuthar@okaxis",
                opening_balance=Decimal('0.00'),
                current_balance=Decimal('0.00'),
                is_default_bank=True,
                is_active=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0091_financialaccount_accounttransaction_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_default_accounts, migrations.RunPython.noop),
    ]

