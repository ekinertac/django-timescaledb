"""
Tests for what the schema editor does with the primary key and the table name
when it creates a hypertable.

Covers `TimescaleSchemaEditor._fix_primary_key`, `_drop_primary_key` and the
regclass quoting in `timescale/db/backends/postgresql/schema.py`.
Related: `test_schema.py` holds the general hypertable tests.

Each test creates its own tables through the schema editor and drops them, so
it needs `transaction=True`: a failed DDL statement aborts the transaction.
Regression source: upstream jamessewell/django-timescaledb issues #58, #22,
#51, #50, #47, #27 and PR #57.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as tz

import django
import pytest
from django.db import DatabaseError, IntegrityError, connection, models
from django.test.utils import CaptureQueriesContext, isolate_apps

from timescale.db.models.fields import TimescaleDateTimeField

pytestmark = pytest.mark.django_db(transaction=True)

APP = 'timescale_tests'
T0 = datetime(2024, 1, 1, tzinfo=tz.utc)


def _fetch(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _primary_key(table):
    """Return the primary key definition of the table, or None."""
    rows = _fetch(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = %s::regclass AND contype = 'p'",
        [connection.ops.quote_name(table)],
    )
    return rows[0][0] if rows else None


def _is_hypertable(table):
    return bool(_fetch(
        "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = %s", [table]))


@contextmanager
def _tables(*model_classes):
    """Create the models' tables, and drop them at the end even after a failure."""
    names = [m._meta.db_table for m in model_classes]

    def drop():
        with connection.cursor() as cursor:
            for name in reversed(names):
                cursor.execute('DROP TABLE IF EXISTS %s CASCADE' % connection.ops.quote_name(name))

    drop()
    try:
        with connection.schema_editor() as editor:
            for model in model_classes:
                editor.create_model(model)
        yield
    finally:
        drop()


class TestDefaultPrimaryKey:
    def test_default_id_key_becomes_id_and_time(self):
        with isolate_apps('timescale.tests'):
            class DefaultKey(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = 'pk_default'

            with _tables(DefaultKey):
                assert _is_hypertable('pk_default')
                assert _primary_key('pk_default') == 'PRIMARY KEY (id, "time")'

    def test_duplicate_id_and_time_is_rejected(self):
        with isolate_apps('timescale.tests'):
            class DefaultKey2(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = 'pk_default2'

            with _tables(DefaultKey2):
                DefaultKey2.objects.create(id=1, time=T0)
                with pytest.raises(IntegrityError):
                    DefaultKey2.objects.bulk_create([DefaultKey2(id=1, time=T0)])

    def test_compression_works_with_the_new_key(self):
        """The key column `id` is not a segmentby column. TimescaleDB must still accept it."""
        with isolate_apps('timescale.tests'):
            class Compressed(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = 'pk_compressed'

            with _tables(Compressed):
                Compressed.objects.bulk_create([Compressed(time=T0 + timedelta(minutes=i)) for i in range(10)])
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE pk_compressed SET (timescaledb.compress)')
                    cursor.execute("SELECT compress_chunk(c) FROM show_chunks('pk_compressed') c")
                # An insert into a compressed chunk must test the key against compressed rows.
                Compressed.objects.create(time=T0 + timedelta(minutes=30))
                assert Compressed.objects.count() == 11


class TestKeyThatIncludesTime:
    def test_time_as_primary_key_is_kept(self):
        with isolate_apps('timescale.tests'):
            class TimeKey(models.Model):
                time = TimescaleDateTimeField(interval='1 day', primary_key=True)
                value = models.FloatField(default=0)

                class Meta:
                    app_label = APP
                    db_table = 'pk_time'

            with _tables(TimeKey):
                assert _is_hypertable('pk_time')
                assert _primary_key('pk_time') == 'PRIMARY KEY ("time")'
                TimeKey.objects.create(time=T0)
                with pytest.raises(IntegrityError):
                    TimeKey.objects.bulk_create([TimeKey(time=T0)])

    def test_delete_through_join_keeps_other_rows(self):
        """
        Upstream #51: with `time` as the key, Django deletes with
        `WHERE time IN (SELECT time ...)`. That is only correct when the
        database keeps `time` unique, which the kept key now does.
        """
        with isolate_apps('timescale.tests'):
            class Controller(models.Model):
                class Meta:
                    app_label = APP
                    db_table = 'pk_join_controller'

            class Peripheral(models.Model):
                controller = models.ForeignKey(Controller, on_delete=models.CASCADE)

                class Meta:
                    app_label = APP
                    db_table = 'pk_join_peripheral'

            class DataPoint(models.Model):
                time = TimescaleDateTimeField(interval='1 day', primary_key=True)
                peripheral = models.ForeignKey(Peripheral, on_delete=models.CASCADE)

                class Meta:
                    app_label = APP
                    db_table = 'pk_join_datapoint'

            with _tables(Controller, Peripheral, DataPoint):
                first, second = Controller.objects.create(), Controller.objects.create()
                on_first = Peripheral.objects.create(controller=first)
                on_second = Peripheral.objects.create(controller=second)
                DataPoint.objects.create(time=T0, peripheral=on_first)
                DataPoint.objects.create(time=T0 + timedelta(minutes=1), peripheral=on_second)

                # Two hops, so Django cannot drop the join and must use the subquery.
                with CaptureQueriesContext(connection) as queries:
                    DataPoint.objects.filter(peripheral__controller=first).delete()

                delete_sql = [q['sql'] for q in queries if q['sql'].startswith('DELETE')][0]
                assert '"time" IN (SELECT' in delete_sql
                assert DataPoint.objects.filter(peripheral=on_second).count() == 1
                # The subquery is only safe because the same time cannot exist twice.
                with pytest.raises(IntegrityError):
                    DataPoint.objects.bulk_create([DataPoint(time=T0 + timedelta(minutes=1), peripheral=on_first)])

    @pytest.mark.skipif(django.VERSION < (5, 2), reason='CompositePrimaryKey needs Django 5.2')
    def test_composite_primary_key_is_kept(self):
        with isolate_apps('timescale.tests'):
            class Composite(models.Model):
                pk = models.CompositePrimaryKey('device_id', 'time')
                device_id = models.IntegerField()
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = 'pk_composite'

            with _tables(Composite):
                assert _is_hypertable('pk_composite')
                assert _primary_key('pk_composite') == 'PRIMARY KEY (device_id, "time")'


class TestTableNames:
    def test_multibyte_table_name(self):
        """PostgreSQL truncates the key name at 63 bytes, not 63 characters."""
        name = 'ölçüm_' + 'ç' * 30
        with isolate_apps('timescale.tests'):
            class MultiByte(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = name

            with _tables(MultiByte):
                assert _is_hypertable(name)
                assert _primary_key(name) == 'PRIMARY KEY (id, "time")'

    def test_long_ascii_table_name(self):
        name = 'a' * 63
        with isolate_apps('timescale.tests'):
            class LongName(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = name

            with _tables(LongName):
                assert _is_hypertable(name)
                assert _primary_key(name) == 'PRIMARY KEY (id, "time")'

    def test_upper_case_table_name(self):
        with isolate_apps('timescale.tests'):
            class UpperCase(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = 'PK_UpperCase'

            with _tables(UpperCase):
                assert _is_hypertable('PK_UpperCase')

                old_field = UpperCase._meta.get_field('time')
                new_field = TimescaleDateTimeField(interval='2 days')
                new_field.set_attributes_from_name('time')
                new_field.model = UpperCase
                with connection.schema_editor() as editor:
                    editor.alter_field(UpperCase, old_field, new_field)

                interval = _fetch(
                    "SELECT time_interval FROM timescaledb_information.dimensions "
                    "WHERE hypertable_name = 'PK_UpperCase'")[0][0]
                assert interval == timedelta(days=2)


class TestExistingTables:
    def test_nullable_time_field_gets_the_key_too(self):
        """create_hypertable makes the column NOT NULL in any case, so the key is possible."""
        with isolate_apps('timescale.tests'):
            class Plain(models.Model):
                value = models.FloatField(default=0)

                class Meta:
                    app_label = APP
                    db_table = 'pk_plain'

            with _tables(Plain):
                field = TimescaleDateTimeField(interval='1 day', null=True)
                field.set_attributes_from_name('ts')
                field.model = Plain
                with connection.schema_editor() as editor:
                    editor.add_field(Plain, field)

                assert _is_hypertable('pk_plain')
                assert _primary_key('pk_plain') == 'PRIMARY KEY (id, ts)'

    def test_existing_rows_with_null_time_stop_the_conversion(self):
        with isolate_apps('timescale.tests'):
            class PlainRows(models.Model):
                value = models.FloatField(default=0)

                class Meta:
                    app_label = APP
                    db_table = 'pk_plain_rows'

            with _tables(PlainRows):
                PlainRows.objects.create()
                field = TimescaleDateTimeField(interval='1 day', null=True)
                field.set_attributes_from_name('ts')
                field.model = PlainRows

                with pytest.raises(DatabaseError, match='contains null values'):
                    with connection.schema_editor() as editor:
                        editor.add_field(PlainRows, field)

                assert not _is_hypertable('pk_plain_rows')
                assert _primary_key('pk_plain_rows') == 'PRIMARY KEY (id)'

    def test_table_referenced_by_foreign_key_gives_clear_error(self):
        """Upstream #27: the key cannot be dropped while a foreign key depends on it."""
        with isolate_apps('timescale.tests'):
            class Order(models.Model):
                created = models.DateTimeField(default=T0)

                class Meta:
                    app_label = APP
                    db_table = 'pk_order'

            class Item(models.Model):
                order = models.ForeignKey(Order, on_delete=models.CASCADE)

                class Meta:
                    app_label = APP
                    db_table = 'pk_item'

            with _tables(Order, Item):
                old_field = Order._meta.get_field('created')
                new_field = TimescaleDateTimeField(interval='1 day', default=T0)
                new_field.set_attributes_from_name('created')
                new_field.model = Order

                # psycopg2 maps RAISE EXCEPTION to InternalError, psycopg 3 to ProgrammingError.
                with pytest.raises(DatabaseError, match='cannot convert pk_order to a hypertable'):
                    with connection.schema_editor() as editor:
                        editor.alter_field(Order, old_field, new_field)

                assert _primary_key('pk_order') == 'PRIMARY KEY (id)'


class TestCollectSql:
    def test_sqlmigrate_output_needs_no_existing_table(self):
        """`sqlmigrate` runs the editor with collect_sql=True and never creates the table."""
        with isolate_apps('timescale.tests'):
            class NeverCreated(models.Model):
                time = TimescaleDateTimeField(interval='1 day')

                class Meta:
                    app_label = APP
                    db_table = 'pk_never_created'

            with connection.schema_editor(collect_sql=True) as editor:
                editor.create_model(NeverCreated)
            sql = '\n'.join(editor.collected_sql)

            assert 'ALTER TABLE "pk_never_created" ADD PRIMARY KEY ("id", "time")' in sql
            assert """create_hypertable('"pk_never_created"', 'time'""" in sql
            assert not _fetch("SELECT 1 FROM pg_class WHERE relname = 'pk_never_created'")
