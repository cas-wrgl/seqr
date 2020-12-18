# Generated by Django 3.1.3 on 2020-11-23 21:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matchmaker', '0002_matchmakerresult_originating_submission'),
    ]

    operations = [
        migrations.AlterField(
            model_name='matchmakerresult',
            name='result_data',
            field=models.JSONField(),
        ),
        migrations.AlterField(
            model_name='matchmakersubmission',
            name='features',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='matchmakersubmission',
            name='genomic_features',
            field=models.JSONField(null=True),
        ),
    ]