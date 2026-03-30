from django.db import models
from django.utils import timezone

from timescale.db.models.fields import TimescaleDateTimeField
from timescale.db.models.managers import TimescaleManager
from timescale.db.models.models import TimescaleModel


class Metric(models.Model):
    """
    Test model using TimescaleDateTimeField directly (mirrors production usage pattern).
    Table name: timescale_tests_metric
    """
    time = TimescaleDateTimeField(interval='1 day', default=timezone.now)
    temperature = models.FloatField(default=0.0)
    device = models.CharField(max_length=50, default='test-device')

    objects = models.Manager()
    timescale = TimescaleManager()

    class Meta:
        app_label = 'timescale_tests'
        ordering = ['-time']


class AnotherMetric(TimescaleModel):
    """
    Test model using TimescaleModel abstract base class.
    Table name: timescale_tests_anothermetric
    """
    time = TimescaleDateTimeField(interval='1 day', default=timezone.now)
    value = models.FloatField(default=0.0)

    class Meta:
        app_label = 'timescale_tests'
        ordering = ['-time']
