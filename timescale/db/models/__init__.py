"""
Public names of the package, so that `import timescale.db.models as tsdb`
works like `django.db.models`.

Constraint: the database backend imports `timescale.db.models.fields`, which
runs this file. A backend module can be imported before `django.setup()` has
filled the app registry, and defining a model class then raises
AppRegistryNotReady. So importing this package must not define a model class.
`TimescaleModel` is loaded on first access through `__getattr__`; everything
else is safe to import here.
"""
from timescale.db.models.aggregates import First, Histogram, Last, LTTB
from timescale.db.models.expressions import (
    Interpolate,
    Interval,
    Locf,
    TimeBucket,
    TimeBucketGapFill,
    TimeBucketNG,
)
from timescale.db.models.fields import TimescaleDateTimeField
from timescale.db.models.managers import TimescaleManager
from timescale.db.models.querysets import TimescaleQuerySet

__all__ = [
    'First',
    'Histogram',
    'Interpolate',
    'Interval',
    'LTTB',
    'Last',
    'Locf',
    'TimeBucket',
    'TimeBucketGapFill',
    'TimeBucketNG',
    'TimescaleDateTimeField',
    'TimescaleManager',
    'TimescaleModel',
    'TimescaleQuerySet',
]


def __getattr__(name):
    if name == 'TimescaleModel':
        from timescale.db.models.models import TimescaleModel
        return TimescaleModel
    raise AttributeError('module %r has no attribute %r' % (__name__, name))
