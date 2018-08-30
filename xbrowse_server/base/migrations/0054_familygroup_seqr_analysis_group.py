# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2018-08-03 17:08
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('seqr', '0046_auto_20180803_1708'),
        ('base', '0053_analysedby_seqr_family_analysed_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='familygroup',
            name='seqr_analysis_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='seqr.AnalysisGroup'),
        ),
    ]