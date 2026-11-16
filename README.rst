Django timescaledb
==================

A database backend and tooling for Timescaledb.

This is a maintained fork of
`django-timescaledb <https://github.com/jamessewell/django-timescaledb>`__,
released on PyPI as ``django-timescaledb-ng``. The original has had no PyPI
release since 0.2.13 (February 2023). This fork is tested on Django 4.2 to 6.0
and Python 3.9 to 3.13. The import name is still ``timescale``, so it replaces
the original and the two cannot be installed together.

Based on
`gist <https://gist.github.com/dedsm/fc74f04eb70d78459ff0847ef16f2e7a>`__
from WeRiot.

Quick start
-----------

1. Install via pip

.. code:: bash

    pip install django-timescaledb-ng

2. Use as DATABASE engine in settings.py:

Standard PostgreSQL

.. code:: python

    DATABASES = {
        'default': {
            'ENGINE': 'timescale.db.backends.postgresql',
            ...
        },
    }

PostGIS

.. code:: python

    DATABASES = {
        'default': {
            'ENGINE': 'timescale.db.backends.postgis',
            ...
        },
    }

If you already make use of a custom PostgreSQL db backend you can set
the path in settings.py.

.. code:: python

    TIMESCALE_DB_BACKEND_BASE = "django.contrib.gis.db.backends.postgis"

3. Inherit from the TimescaleModel. A
   `hypertable <https://docs.timescale.com/latest/using-timescaledb/hypertables#react-docs>`__
   will automatically be created.

.. code:: python


      class TimescaleModel(models.Model):
        """
        A helper class for using Timescale within Django, has the TimescaleManager and 
        TimescaleDateTimeField already present. This is an abstract class it should 
        be inheritted by another class for use.
        """
        time = TimescaleDateTimeField(interval="1 day")

        objects = TimescaleManager()

        class Meta:
            abstract = True

Implementation would look like this

.. code:: python

    from timescale.db.models.models import TimescaleModel

    class Metric(TimescaleModel):
       temperature = models.FloatField()
       

If you already have a table, you can either add `time`
field of type `TimescaleDateTimeField` to your model or
rename (if not already named `time`) and change type of
existing `DateTimeField` (rename first then run
`makemigrations` and then change the type, so that
`makemigrations` considers it as change in same field
instead of removing and adding new field). This also
triggers the creation of a hypertable.

.. code:: python

    from timescale.db.models.fields import TimescaleDateTimeField
    from timescale.db.models.managers import TimescaleManager

    class Metric(models.Model):
      time = TimescaleDateTimeField(interval="1 day")

      objects = models.Manager()
      timescale = TimescaleManager()

The name of the field is important as Timescale specific feratures
require this as a property of their functions.

All public classes can also be imported from the package: ``import timescale.db.models as tsdb``, then ``tsdb.TimescaleDateTimeField``, ``tsdb.TimescaleManager``, ``tsdb.TimeBucket`` and so on.

Primary keys, unique fields and foreign keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

TimescaleDB only accepts a unique index that includes the time column. This shapes what a hypertable model can have.

- **Primary key.** Django's default key on ``id`` becomes ``PRIMARY KEY (id, time)`` in the database. Django still uses ``id`` as the key. If the key already includes the time field (``primary_key=True`` on the time field, or a ``CompositePrimaryKey`` that lists it), it is kept as it is. Before 0.4.0 the key was always dropped, so tables created by older versions have no primary key and no index on ``id``. They are not changed.
- **Unique fields.** ``unique=True`` on another field cannot work. Use a ``UniqueConstraint`` that includes the time field.
- **Foreign keys to a hypertable.** Other models cannot have a ``ForeignKey`` or ``ManyToManyField`` to a hypertable model, unless it has ``db_constraint=False``. A hypertable can have foreign keys to normal tables. One exception: when the time field is the primary key, TimescaleDB 2.32 accepts a foreign key to it and 2.13 does not, so the check leaves that case to the database.
- **Existing tables.** A table that other tables reference by foreign key cannot be converted to a hypertable. TimescaleDB makes the time column ``NOT NULL``, also for a field with ``null=True``, so rows with no time value must be filled before the conversion.

``manage.py check`` and ``makemigrations`` report the unique and foreign key cases as ``timescale.E001`` and ``timescale.E002``. To turn a check off, add its id to ``SILENCED_SYSTEM_CHECKS``.

Tests with compression on TimescaleDB 2.13
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On TimescaleDB 2.13.1, the table flush at the end of a ``TransactionTestCase`` fails when a compressed hypertable has a foreign key to another table: ``cannot truncate a table referenced in a foreign key constraint``, with ``_compressed_hypertable_N`` in the detail line. TimescaleDB 2.32.0 does not have the problem; versions in between were not tested. On an affected version, set ``available_apps`` on the test case so that Django truncates with ``CASCADE``, or use ``TestCase``.

Reading Data
~~~~~~~~~~~~

"TimescaleDB hypertables are designed to behave in the same manner as
PostgreSQL database tables for reading data, using standard SQL
commands."

As such the use of the Django's ORM is perfectally suited to this type
of data. By leveraging a custom model manager and queryset we can extend
the queryset methods to include Timescale functions.

Time Bucket `More Info <https://docs.timescale.com/latest/using-timescaledb/reading-data#time-bucket>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: python

      Metric.timescale.filter(time__range=date_range).time_bucket('time', '1 hour')

      # expected output

      <TimescaleQuerySet [{'bucket': datetime.datetime(2020, 12, 22, 11, 0, tzinfo=<UTC>)}, ... ]>

Buckets start at midnight UTC. To move the boundary, pass ``offset`` (an interval string or a ``timedelta``) or ``origin`` (a datetime), not both:

.. code:: python

      # daily buckets that start at 06:00 UTC
      Metric.timescale.time_bucket('time', '1 day', offset='6 hours')

Time Bucket Gap Fill `More Info <https://docs.timescale.com/latest/using-timescaledb/reading-data#gap-filling>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: python

      from metrics.models import *
      from django.db.models import Count, Avg
      from django.utils import timezone
      from datetime import timedelta

      ranges = (timezone.now() - timedelta(days=2), timezone.now())

      (Metric.timescale
        .filter(time__range=ranges)
        .time_bucket_gapfill('time', '1 day', ranges[0], ranges[1], datapoints=240)
        .annotate(Avg('temperature')))

      # expected output

      <TimescaleQuerySet [{'bucket': datetime.datetime(2020, 12, 21, 21, 24, tzinfo=<UTC>), 'temperature__avg': None}, ...]>

Empty buckets are ``None``. ``Locf`` fills them with the last value before the gap, ``Interpolate`` with a straight line between the neighbours. Both go around an aggregate:

.. code:: python

      from timescale.db.models import Locf, Interpolate

      (Metric.timescale
        .filter(time__range=ranges)
        .time_bucket_gapfill('time', '1 day', ranges[0], ranges[1])
        .annotate(carried=Locf(Avg('temperature')), line=Interpolate(Avg('temperature'))))

The ``prev`` and ``next`` arguments of the SQL ``interpolate`` function are not supported, so an empty first or last bucket stays ``None``.

Histogram `More Info <https://docs.timescale.com/latest/using-timescaledb/reading-data#histogram>`__
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: python

      from metrics.models import *
      from django.db.models import Count
      from django.utils import timezone
      from datetime import timedelta

      ranges = (timezone.now() - timedelta(days=3), timezone.now())

      (Metric.timescale
        .filter(time__range=ranges)
        .values('device')
        .histogram(field='temperature', min_value=50.0, max_value=55.0, num_of_buckets=10)
        .annotate(Count('device')))
        
      # expected output

      <TimescaleQuerySet [{'histogram': [0, 0, 0, 87, 93, 125, 99, 59, 0, 0, 0, 0], 'device__count': 463}]>

