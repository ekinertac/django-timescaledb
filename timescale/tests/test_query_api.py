"""
Tests for the query-side additions: `offset` / `origin` on
`TimescaleManager.time_bucket`, the `Locf` and `Interpolate` expressions, and
the package-level exports of `timescale.db.models`.

Related: `test_models.py` holds the older manager and expression tests.
Regression source: upstream jamessewell/django-timescaledb issues #24, #7,
#39 and PR #9.
"""
import subprocess
import sys
from datetime import datetime, timedelta, timezone as tz

import pytest
from django.db.models import Avg, Count

from timescale.tests.factories import MetricFactory
from timescale.tests.models import Metric

DAY = datetime(2024, 6, 15, tzinfo=tz.utc)


@pytest.mark.django_db
class TestTimeBucketOffsetOrigin:
    def _two_rows(self):
        # 03:00 and 09:00 are in one calendar day, and on two sides of 06:00.
        MetricFactory(time=DAY + timedelta(hours=3))
        MetricFactory(time=DAY + timedelta(hours=9))

    def test_without_offset_both_rows_share_a_bucket(self):
        self._two_rows()
        assert len(Metric.timescale.time_bucket('time', '1 day')) == 1

    def test_offset_moves_the_bucket_boundary(self):
        self._two_rows()
        buckets = [row['bucket'] for row in Metric.timescale.time_bucket('time', '1 day', offset='6 hours')]
        assert buckets == [DAY + timedelta(hours=6), DAY - timedelta(hours=18)]

    def test_offset_accepts_a_timedelta(self):
        self._two_rows()
        rows = Metric.timescale.time_bucket('time', '1 day', offset=timedelta(hours=6))
        assert [row['bucket'] for row in rows] == [DAY + timedelta(hours=6), DAY - timedelta(hours=18)]

    def test_offset_accepts_a_string_value_expression(self):
        from django.db.models import Value
        from timescale.db.models.expressions import TimeBucket
        self._two_rows()
        rows = Metric.objects.values(bucket=TimeBucket('time', '1 day', offset=Value('6 hours'))).distinct()
        assert sorted(row['bucket'] for row in rows) == [DAY - timedelta(hours=18), DAY + timedelta(hours=6)]

    def test_origin_moves_the_bucket_boundary(self):
        self._two_rows()
        origin = DAY + timedelta(hours=6)
        buckets = [row['bucket'] for row in Metric.timescale.time_bucket('time', '1 day', origin=origin)]
        assert buckets == [DAY + timedelta(hours=6), DAY - timedelta(hours=18)]

    def test_offset_with_annotations(self):
        self._two_rows()
        rows = Metric.timescale.time_bucket('time', '1 day', {'n': Count('id')}, offset='6 hours')
        assert [row['n'] for row in rows] == [1, 1]

    def test_queryset_method_accepts_offset(self):
        self._two_rows()
        assert len(Metric.timescale.all().time_bucket('time', '1 day', offset='6 hours')) == 2

    def test_offset_and_origin_together_raise(self):
        with pytest.raises(ValueError):
            Metric.timescale.time_bucket('time', '1 day', offset='6 hours', origin=DAY)
