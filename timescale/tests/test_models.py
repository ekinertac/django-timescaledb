import pytest
from datetime import datetime, timezone as tz, timedelta

from django.db import models
from django.db.models import Avg

from timescale.db.models.managers import TimescaleManager
from timescale.db.models.models import TimescaleModel
from timescale.db.models.querysets import TimescaleQuerySet
from timescale.tests.factories import MetricFactory
from timescale.tests.models import AnotherMetric, Metric

pytestmark = pytest.mark.django_db


# ── Manager / model structure ────────────────────────────────────────────────

class TestTimescaleModelStructure:
    def test_metric_has_timescale_manager(self):
        assert isinstance(Metric.timescale, TimescaleManager)

    def test_metric_has_objects_manager(self):
        assert isinstance(Metric.objects, models.Manager)

    def test_timescale_manager_returns_timescale_queryset(self):
        qs = Metric.timescale.all()
        assert isinstance(qs, TimescaleQuerySet)

    def test_another_metric_subclasses_timescale_model(self):
        assert issubclass(AnotherMetric, TimescaleModel)

    def test_another_metric_has_timescale_manager(self):
        assert isinstance(AnotherMetric.timescale, TimescaleManager)


# ── time_bucket ──────────────────────────────────────────────────────────────

class TestTimeBucket:
    # Use fixed UTC timestamps to avoid flaky day-boundary issues.
    T1 = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)   # day A
    T2 = datetime(2024, 6, 15, 11, 0, 0, tzinfo=tz.utc)   # day A
    T3 = datetime(2024, 6, 13, 10, 0, 0, tzinfo=tz.utc)   # day B (2 days earlier)

    def test_time_bucket_groups_by_day(self):
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)
        MetricFactory(time=self.T3, temperature=30.0)

        results = Metric.timescale.time_bucket('time', '1 day').to_list()
        assert len(results) == 2
        assert 'bucket' in results[0]

    def test_time_bucket_with_annotation(self):
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)

        results = (
            Metric.timescale
            .time_bucket('time', '1 day', {'temperature__avg': Avg('temperature')})
            .to_list()
        )
        assert len(results) == 1
        assert abs(results[0]['temperature__avg'] - 15.0) < 0.001

    def test_to_list_normalise_datetimes_returns_iso_strings(self):
        MetricFactory(time=self.T1, temperature=10.0)

        results = Metric.timescale.time_bucket('time', '1 day').to_list(normalise_datetimes=True)
        assert len(results) == 1
        assert isinstance(results[0]['bucket'], str)


# ── time_bucket_ng ───────────────────────────────────────────────────────────

class TestTimeBucketNg:
    @pytest.mark.skip(reason="timescaledb_experimental.time_bucket_ng not available in this TimescaleDB version")
    def test_monthly_buckets_with_avg(self):
        from dateutil.relativedelta import relativedelta
        from django.utils import timezone

        timestamp = timezone.now().replace(day=1, hour=12, minute=0, second=0, microsecond=0)

        # current month
        MetricFactory(time=timestamp - relativedelta(days=15), temperature=8.0)
        MetricFactory(time=timestamp - relativedelta(days=10), temperature=10.0)
        # previous month
        MetricFactory(time=timestamp - relativedelta(months=1, days=15), temperature=14.0)
        MetricFactory(time=timestamp - relativedelta(months=1, days=10), temperature=12.0)

        results = Metric.timescale.time_bucket_ng('time', '1 month').annotate(Avg('temperature'))

        assert results[0]['temperature__avg'] == 9.0
        assert results[1]['temperature__avg'] == 13.0


# ── time_bucket_gapfill ──────────────────────────────────────────────────────

class TestTimeBucketGapFill:
    def test_gapfill_produces_none_for_missing_intervals(self):
        START = datetime(2024, 6, 15, 8, 0, 0, tzinfo=tz.utc)
        END   = datetime(2024, 6, 15, 13, 0, 0, tzinfo=tz.utc)

        # data at hours 9 and 12 — hours 8, 10, 11 will be gaps
        MetricFactory(time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=tz.utc), temperature=10.0)
        MetricFactory(time=datetime(2024, 6, 15, 12, 0, 0, tzinfo=tz.utc), temperature=20.0)

        results = (
            Metric.timescale
            .time_bucket_gapfill('time', '1 hour', START, END)
            .annotate(Avg('temperature'))
            .to_list()
        )

        assert len(results) == 5
        none_count = sum(1 for r in results if r['temperature__avg'] is None)
        assert none_count == 3


# ── histogram ────────────────────────────────────────────────────────────────

class TestHistogram:
    def test_histogram_returns_list(self):
        base = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)
        for i, temp in enumerate([10.0, 25.0, 50.0, 75.0, 90.0]):
            MetricFactory(time=base + timedelta(minutes=i), temperature=temp)

        results = Metric.timescale.histogram('temperature', 0.0, 100.0, 5).to_list()
        assert len(results) == 1
        assert 'histogram' in results[0]
        assert isinstance(results[0]['histogram'], list)
        assert sum(results[0]['histogram']) == 5


# ── TimeBucket with origin/offset ────────────────────────────────────────────

class TestTimeBucketOriginOffset:
    T1 = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)
    T2 = datetime(2024, 6, 15, 14, 0, 0, tzinfo=tz.utc)
    T3 = datetime(2024, 6, 16, 10, 0, 0, tzinfo=tz.utc)

    def test_time_bucket_with_origin(self):
        from timescale.db.models.expressions import TimeBucket
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)
        MetricFactory(time=self.T3, temperature=30.0)

        origin = datetime(2024, 6, 15, 0, 0, 0, tzinfo=tz.utc)
        results = (
            Metric.timescale
            .values(bucket=TimeBucket('time', '1 day', origin=origin))
            .order_by('-bucket')
            .distinct()
        )
        results = list(results)
        assert len(results) == 2
        assert 'bucket' in results[0]

    def test_time_bucket_with_offset(self):
        from timescale.db.models.expressions import TimeBucket
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)

        results = (
            Metric.timescale
            .values(bucket=TimeBucket('time', '1 day', offset='1 hour'))
            .order_by('-bucket')
            .distinct()
        )
        results = list(results)
        assert len(results) >= 1
        assert 'bucket' in results[0]


class TestTimeBucketOriginOffsetConflict:
    def test_raises_when_both_origin_and_offset_given(self):
        from timescale.db.models.expressions import TimeBucket
        origin = datetime(2024, 1, 1, tzinfo=tz.utc)
        with pytest.raises(ValueError, match="Cannot specify both origin and offset"):
            TimeBucket('time', '1 day', origin=origin, offset='1 hour')


# ── TimeBucketGapFill with datapoints ────────────────────────────────────────

class TestTimeBucketGapFillDatapoints:
    def test_gapfill_with_datapoints_divides_interval(self):
        START = datetime(2024, 6, 15, 8, 0, 0, tzinfo=tz.utc)
        END   = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)

        MetricFactory(time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=tz.utc), temperature=10.0)

        # datapoints=4 over a 2-hour window → 30-minute buckets → 4 buckets
        results = (
            Metric.timescale
            .time_bucket_gapfill('time', '2 hours', START, END, datapoints=4)
            .annotate(Avg('temperature'))
            .to_list()
        )
        assert len(results) == 4


# ── First / Last aggregates ───────────────────────────────────────────────────

class TestFirstLastAggregates:
    T1 = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)
    T2 = datetime(2024, 6, 15, 11, 0, 0, tzinfo=tz.utc)
    T3 = datetime(2024, 6, 15, 12, 0, 0, tzinfo=tz.utc)

    def test_first_aggregate(self):
        from timescale.db.models.aggregates import First
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)
        MetricFactory(time=self.T3, temperature=30.0)

        result = Metric.objects.aggregate(first_temp=First('temperature', 'time'))
        assert result['first_temp'] == 10.0

    def test_last_aggregate(self):
        from timescale.db.models.aggregates import Last
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)
        MetricFactory(time=self.T3, temperature=30.0)

        result = Metric.objects.aggregate(last_temp=Last('temperature', 'time'))
        assert result['last_temp'] == 30.0


# ── LTTB ─────────────────────────────────────────────────────────────────────

class TestLTTB:
    @pytest.mark.skip(reason="TimescaleDB Toolkit (lttb) not available")
    def test_lttb_returns_downsampled_results(self):
        base = datetime(2024, 6, 15, 0, 0, 0, tzinfo=tz.utc)
        for i in range(20):
            MetricFactory(time=base + timedelta(hours=i), temperature=float(i))

        results = Metric.timescale.lttb('time', 'temperature', num_of_counts=5).to_list()
        # LTTB should downsample 20 points to ~5
        assert len(results) == 5


# ── TimescaleExtension ────────────────────────────────────────────────────────

class TestTimescaleExtension:
    def test_extension_name_is_timescaledb(self):
        from timescale.db.operations import TimescaleExtension
        ext = TimescaleExtension()
        assert ext.name == 'timescaledb'
