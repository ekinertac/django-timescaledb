"""
Edge cases for the SQL that the schema editor builds, and for the backend
base class lookup.

The schema editor formats table names, column names and the chunk interval
into SQL text. These values come from model definitions, not from requests,
but a name with a quote or a % sign must still give correct SQL and must
never run as a second statement.
Covers `timescale/db/backends/postgresql/schema.py` and `base_impl.py`.
Related: `test_primary_key.py` (key handling), `test_schema.py`.
"""
from contextlib import contextmanager

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection, models
from django.test.utils import isolate_apps, override_settings

from timescale.db.backends.postgresql import base_impl
from timescale.db.models.fields import TimescaleDateTimeField

pytestmark = pytest.mark.django_db(transaction=True)

APP = 'timescale_tests'


def _fetch(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _primary_key(table):
    rows = _fetch(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relname = %s AND t.relnamespace = 'public'::regnamespace AND c.contype = 'p'",
        [table],
    )
    return rows[0][0] if rows else None


def _is_hypertable(table, schema='public'):
    return bool(_fetch(
        "SELECT 1 FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = %s AND hypertable_schema = %s", [table, schema]))


def _drop(name):
    with connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS %s CASCADE' % connection.ops.quote_name(name))


def _model(table, interval='1 day'):
    """A hypertable model with the given table name. Call inside isolate_apps."""
    meta = type('Meta', (), {'app_label': APP, 'db_table': table})
    return type('EdgeCase', (models.Model,), {
        '__module__': __name__,
        'time': TimescaleDateTimeField(interval=interval),
        'Meta': meta,
    })


@contextmanager
def _created(model):
    name = model._meta.db_table
    _drop(name)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(model)
        yield
    finally:
        _drop(name)


class TestSpecialCharactersInTableName:
    # A double quote in the name is not in the list: Django's own quote_name
    # does not escape it, so Django cannot create such a table on any backend.
    @pytest.mark.parametrize('name', [
        'edge_50%_load',
        'edge_100%%',
        "edge_o'clock",
        'edge_semi; DROP TABLE edge_canary; --',
        'edge space',
    ])
    def test_table_becomes_hypertable_with_key(self, name):
        with isolate_apps('timescale.tests'):
            model = _model(name)
            with _created(model):
                assert _is_hypertable(name)
                assert _primary_key(name) == 'PRIMARY KEY (id, "time")'

    def test_interval_can_be_changed_on_such_a_table(self):
        name = "edge_o'clock_50%"
        with isolate_apps('timescale.tests'):
            model = _model(name)
            with _created(model):
                new_field = TimescaleDateTimeField(interval='2 days')
                new_field.set_attributes_from_name('time')
                new_field.model = model
                with connection.schema_editor() as editor:
                    editor.alter_field(model, model._meta.get_field('time'), new_field)
                assert _is_hypertable(name)


class TestIntervalValue:
    def test_interval_with_sql_in_it_does_not_run(self):
        """The interval is a string literal. Text after a quote must stay inside it."""
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS edge_canary')
            cursor.execute('CREATE TABLE edge_canary (id int)')
        try:
            with isolate_apps('timescale.tests'):
                model = _model('edge_interval', interval="1 day'); DROP TABLE edge_canary; --")
                with pytest.raises(DatabaseError, match='invalid input syntax for type interval'):
                    with _created(model):
                        pass
            assert _fetch("SELECT 1 FROM pg_class WHERE relname = 'edge_canary'")
        finally:
            _drop('edge_canary')


class TestSameTableNameInAnotherSchema:
    def test_hypertable_in_other_schema_does_not_block_create(self):
        """
        A hypertable `other.edge_twin` exists. Creating `public.edge_twin`
        must work: the "is it a hypertable already" guard has to look at the
        table itself, not at every table with that name.
        """
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA IF EXISTS edge_other CASCADE')
            cursor.execute('CREATE SCHEMA edge_other')
            cursor.execute('CREATE TABLE edge_other.edge_twin ("time" timestamptz NOT NULL)')
            cursor.execute("SELECT create_hypertable('edge_other.edge_twin', 'time')")
        try:
            with isolate_apps('timescale.tests'):
                model = _model('edge_twin')
                with _created(model):
                    assert _is_hypertable('edge_twin', schema='public')
                    assert _is_hypertable('edge_twin', schema='edge_other')

                    # The "must be a hypertable" guard has the same lookup.
                    new_field = TimescaleDateTimeField(interval='2 days')
                    new_field.set_attributes_from_name('time')
                    new_field.model = model
                    with connection.schema_editor() as editor:
                        editor.alter_field(model, model._meta.get_field('time'), new_field)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP SCHEMA IF EXISTS edge_other CASCADE')

    def test_plain_table_with_hypertable_twin_is_not_seen_as_hypertable(self):
        """Changing the interval on a table that is not a hypertable must still fail."""
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA IF EXISTS edge_other CASCADE')
            cursor.execute('CREATE SCHEMA edge_other')
            cursor.execute('CREATE TABLE edge_other.edge_twin2 ("time" timestamptz NOT NULL)')
            cursor.execute("SELECT create_hypertable('edge_other.edge_twin2', 'time')")
            cursor.execute('DROP TABLE IF EXISTS edge_twin2')
            cursor.execute('CREATE TABLE edge_twin2 (id bigint PRIMARY KEY, "time" timestamptz NOT NULL)')
        try:
            with isolate_apps('timescale.tests'):
                model = _model('edge_twin2')
                with pytest.raises(DatabaseError, match='should be a hyper table'):
                    with connection.schema_editor() as editor:
                        editor._set_chunk_time_interval(model, model._meta.get_field('time'))
        finally:
            _drop('edge_twin2')
            with connection.cursor() as cursor:
                cursor.execute('DROP SCHEMA IF EXISTS edge_other CASCADE')


class TestBackendBaseSetting:
    """`TIMESCALE_DB_BACKEND_BASE` lets a project put this backend on top of another one."""

    pytestmark = []  # no database needed

    def test_default_is_the_postgresql_backend(self):
        from django.db.backends.postgresql.base import DatabaseWrapper
        assert base_impl.backend() is DatabaseWrapper

    def test_subclass_of_the_postgresql_backend_is_accepted(self):
        with override_settings(TIMESCALE_DB_BACKEND_BASE='timescale.tests.backend_subclass'):
            assert base_impl.backend().__module__ == 'timescale.tests.backend_subclass.base'

    def test_module_without_database_wrapper_is_rejected(self):
        with override_settings(TIMESCALE_DB_BACKEND_BASE='timescale.tests.backend_without_wrapper'):
            with pytest.raises(ImproperlyConfigured, match='does not define a DatabaseWrapper'):
                base_impl.backend()

    def test_backend_of_another_database_is_rejected(self):
        with override_settings(TIMESCALE_DB_BACKEND_BASE='django.db.backends.sqlite3'):
            with pytest.raises(ImproperlyConfigured, match='does not inherit from the PostgreSQL back-end'):
                base_impl.backend()
