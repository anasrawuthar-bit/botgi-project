from django.db import transaction
from decimal import Decimal


def generate_next_sales_invoice_number():
    """Generate next shared sales invoice number."""
    from .models import CompanyProfile
    
    profile = CompanyProfile.get_profile()
    with transaction.atomic():
        profile = CompanyProfile.objects.select_for_update().get(pk=profile.pk)
        next_num = profile.sales_invoice_next_number
        invoice_number = f"{next_num:04d}"
        profile.sales_invoice_next_number = next_num + 1
        profile.save(update_fields=['sales_invoice_next_number'])
    return invoice_number
