# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2019-03-19 15:18
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reference_data', '0009_auto_20180917_2015'),
    ]

    operations = [
        migrations.AddField(
            model_name='omim',
            name='phenotypic_series_number',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='omim',
            name='phenotype_map_method',
            field=models.CharField(blank=True, choices=[(b'1', b'the disorder is placed on the map based on its association with a gene, but the underlying defect is not known.'), (b'2', b'the disorder has been placed on the map by linkage; no mutation has been found.'), (b'3', b'the molecular basis for the disorder is known; a mutation has been found in the gene.'), (b'4', b'a contiguous gene deletion or duplication syndrome, multiple genes are deleted or duplicated causing the phenotype.')], max_length=1, null=True),
        ),
    ]
