from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.db.models.functions import Cast
from django.db.models.functions.mixins import (
    FixDurationInputMixin,
    NumericOutputFieldMixin,
)
from django.utils import timezone
from datetime import timedelta
from timescale.db.models.fields import TimescaleDateTimeField


class Interval(models.Func):
    """
    A helper class to format the interval used by the time_bucket_gapfill function to generate correct timestamps.
    Accepts an interval e.g '1 day', '5 days', '1 hour'
    """

    function = "INTERVAL"
    template = "%(function)s %(expressions)s"

    def __init__(self, interval, *args, **kwargs):
        if not isinstance(interval, models.Value):
            interval = models.Value(interval)
        super().__init__(interval, *args, **kwargs)


class TimeBucket(models.Func):
    """
    Implementation of the time_bucket function from Timescale.

    Read more about it here - https://docs.timescale.com/latest/using-timescaledb/reading-data#time-bucket

    Response:

    [
        {'bucket': '2020-12-22T10:00:00+00:00', 'devices': 12},
        {'bucket': '2020-12-22T09:00:00+00:00', 'devices': 12},
        {'bucket': '2020-12-22T08:00:00+00:00', 'devices': 12},
        {'bucket': '2020-12-22T07:00:00+00:00', 'devices': 12},
    ]

    """

    function = "time_bucket"
    name = "time_bucket"


    def __init__(self, expression, interval, offset=None, origin=None, *args, **kwargs):
        if origin is not None and offset is not None:
            raise ValueError("Cannot specify both origin and offset")
        if not isinstance(interval, models.Value):
            interval = models.Value(interval)
        args = [interval, expression]
        if origin is not None:
            args.append(origin)
        elif offset is not None:
            # The offset must reach PostgreSQL typed as an interval. An untyped
            # string matches the overload time_bucket(width, ts, timezone)
            # instead, and '6 hours' is then read as a time zone name.
            if isinstance(offset, models.Value) and isinstance(offset.value, str):
                offset = offset.value
            if isinstance(offset, str):
                offset = Cast(models.Value(offset), models.DurationField())
            elif not hasattr(offset, 'resolve_expression'):
                offset = models.Value(offset)
            args.append(offset)
        output_field = TimescaleDateTimeField(interval=interval)
        super().__init__(*args, output_field=output_field)


class TimeBucketNG(models.Func):
    """
    Implementation of the time_bucket_ng function from Timescale.

    Read more about it here - https://docs.timescale.com/api/latest/hyperfunctions/time_bucket_ng/#timescaledb-experimental-time-bucket-ng

    Response:

    [
        {'bucket': '2020-12-01T00:00:00+00:00', 'devices': 12},
        {'bucket': '2020-11-01T00:00:00+00:00', 'devices': 12},
        {'bucket': '2020-10-01T00:00:00+00:00', 'devices': 12},
        {'bucket': '2020-09-01T00:00:00+00:00', 'devices': 12},
    ]

    """

    function = "timescaledb_experimental.time_bucket_ng"
    name = "timescaledb_experimental.time_bucket_ng"

    def __init__(self, expression, interval, *args, **kwargs):
        if not isinstance(interval, models.Value):
            interval = models.Value(interval)
        output_field = TimescaleDateTimeField(interval=interval)
        super().__init__(interval, expression, output_field=output_field)


class TimeBucketGapFill(models.Func):
    """
    IMplementation of the time_bucket_gapfill function from Timescale

    Read more about it here - https://docs.timescale.com/latest/using-timescaledb/reading-data#gap-filling

    Response:

    [
        ...
        {'bucket': '2020-12-22T11:36:00+00:00', 'temperature__avg': 52.7127405105567},
        {'bucket': '2020-12-22T11:42:00+00:00', 'temperature__avg': None},
        ...
    ]
    """

    function = "time_bucket_gapfill"
    name = "time_bucket_gapfill"

    def __init__(
        self, expression, interval, start, end, datapoints=None, *args, **kwargs
    ):
        if not isinstance(interval, models.Value):
            interval = Interval(interval)
            if datapoints:
                interval = interval / datapoints
        output_field = TimescaleDateTimeField(interval=interval)
        super().__init__(interval, expression, start, end, output_field=output_field)


class Locf(models.Func):
    """
    Last observation carried forward: fills an empty time_bucket_gapfill
    bucket with the value of the bucket before it.

    Only valid in a query that uses time_bucket_gapfill, around an aggregate:

        Metric.timescale.time_bucket_gapfill('time', '1 day', start, end)
            .annotate(temperature=Locf(Avg('temperature')))

    https://docs.timescale.com/api/latest/hyperfunctions/gapfilling/locf/
    """

    function = "locf"
    name = "locf"
    arity = 1


class Interpolate(models.Func):
    """
    Linear interpolation: fills an empty time_bucket_gapfill bucket from the
    buckets before and after it. Use it like `Locf`.

    The optional `prev` and `next` arguments of the SQL function (values
    outside the queried range) are not supported; the first and last bucket
    stay NULL when they are empty.

    https://docs.timescale.com/api/latest/hyperfunctions/gapfilling/interpolate/
    """

    function = "interpolate"
    name = "interpolate"
    arity = 1
