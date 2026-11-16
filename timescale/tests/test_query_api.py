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


@pytest.mark.django_db
class TestGapfillFunctions:
    def _rows(self, expression):
        # Day 1 has value 10, day 2 is empty, day 3 has value 30.
        MetricFactory(time=DAY + timedelta(hours=1), temperature=10.0)
        MetricFactory(time=DAY + timedelta(days=2, hours=1), temperature=30.0)
        end = DAY + timedelta(days=3)
        rows = (
            Metric.timescale.filter(time__range=(DAY, end))
            .time_bucket_gapfill('time', '1 day', DAY, end)
            .annotate(avg=Avg('temperature'), filled=expression)
            .order_by('bucket')
        )
        return [(row['avg'], row['filled']) for row in rows]

    def test_locf_carries_the_last_value_forward(self):
        from timescale.db.models.expressions import Locf
        assert self._rows(Locf(Avg('temperature'))) == [(10.0, 10.0), (None, 10.0), (30.0, 30.0)]

    def test_interpolate_fills_the_gap_linearly(self):
        from timescale.db.models.expressions import Interpolate
        assert self._rows(Interpolate(Avg('temperature'))) == [(10.0, 10.0), (None, 20.0), (30.0, 30.0)]


class TestPackageExports:
    def test_all_names_are_importable(self):
        import timescale.db.models as tsdb
        for name in tsdb.__all__:
            assert getattr(tsdb, name) is not None

    def test_same_objects_as_the_long_paths(self):
        import timescale.db.models as tsdb
        from timescale.db.models.fields import TimescaleDateTimeField
        from timescale.db.models.models import TimescaleModel
        assert tsdb.TimescaleDateTimeField is TimescaleDateTimeField
        assert tsdb.TimescaleModel is TimescaleModel

    def test_unknown_name_raises_attribute_error(self):
        import timescale.db.models as tsdb
        with pytest.raises(AttributeError):
            tsdb.DoesNotExist

    def test_backend_imports_before_the_app_registry_is_ready(self):
        """
        Django imports the database backend while it loads settings. If the
        package defined a model class at import time, this would raise
        AppRegistryNotReady. A subprocess is needed: this process is set up.
        """
        code = (
            "import os; os.environ['DJANGO_SETTINGS_MODULE'] = 'timescale.tests.settings'; "
            "import timescale.db.backends.postgresql.base, timescale.db.models; print('ok')"
        )
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        assert result.stdout.strip() == 'ok', result.stderr
