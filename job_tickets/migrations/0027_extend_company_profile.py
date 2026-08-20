# Generated migration for extended company profile

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_tickets', '0026_companyprofile_logo_companyprofile_tagline_and_more'),
    ]

    operations = [
        # Update existing fields
        migrations.AlterField(
            model_name='companyprofile',
            name='company_name',
            field=models.CharField(default='GI Service Billing', max_length=200),
        ),
        migrations.AlterField(
            model_name='companyprofile',
            name='address',
            field=models.TextField(default='Your Business Address'),
        ),
        migrations.AlterField(
            model_name='companyprofile',
            name='phone1',
            field=models.CharField(default='+91 0000000000', max_length=20),
        ),
        migrations.AlterField(
            model_name='companyprofile',
            name='phone2',
            field=models.CharField(blank=True, max_length=20),
        ),
        
        # Add new address fields
        migrations.AddField(
            model_name='companyprofile',
            name='city',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='state',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='pincode',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='website',
            field=models.URLField(blank=True),
        ),
        
        # Add legal/tax fields
        migrations.AddField(
            model_name='companyprofile',
            name='gstin',
            field=models.CharField(blank=True, help_text='GST Identification Number', max_length=15),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='pan',
            field=models.CharField(blank=True, help_text='PAN Number', max_length=10),
        ),
        
        # Add bank details
        migrations.AddField(
            model_name='companyprofile',
            name='bank_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='account_number',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='ifsc_code',
            field=models.CharField(blank=True, max_length=11),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='branch',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='upi_id',
            field=models.CharField(blank=True, help_text='UPI ID for payments', max_length=100),
        ),
        
        # Add job ticket settings
        migrations.AddField(
            model_name='companyprofile',
            name='job_code_prefix',
            field=models.CharField(default='GI', help_text='Prefix for job codes (e.g., GI, SERV)', max_length=10),
        ),
        
        # Add GST settings
        migrations.AddField(
            model_name='companyprofile',
            name='enable_gst',
            field=models.BooleanField(default=False, help_text='Enable GST on invoices'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='gst_rate',
            field=models.DecimalField(decimal_places=2, default=18.00, help_text='GST rate in percentage', max_digits=5),
        ),
        
        # Add terms and policies
        migrations.AddField(
            model_name='companyprofile',
            name='terms_conditions',
            field=models.TextField(blank=True, default='1. All repairs carry 30 days warranty.\\n2. No warranty on physical/liquid damage.\\n3. Payment due on delivery.'),
        ),
        migrations.AddField(
            model_name='companyprofile',
            name='warranty_policy',
            field=models.TextField(blank=True, default='30 days warranty on all repairs. Does not cover physical or liquid damage.'),
        ),
    ]
