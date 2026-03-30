import pytest
from django.db import connection, models as dj_models
from django.test.utils import isolate_apps

from timescale.db.models.fields import TimescaleDateTimeField
from timescale.tests.models import AnotherMetric, Metric

pytestmark = pytest.mark.django_db


def _is_hypertable(table_name: str) -> bool:
    """Return True if the table is registered as a TimescaleDB hypertable."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = %s",
            [table_name],
        )
        return cursor.fetchone() is not None


def _get_partition_column(table_name: str) -> str:
    """Return the partition column name for a hypertable."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM timescaledb_information.dimensions "
            "WHERE hypertable_name = %s",
            [table_name],
        )
        row = cursor.fetchone()
        return row[0] if row else None


class TestHypertableCreation:
    def test_metric_table_is_hypertable(self):
        """TimescaleSchemaEditor.create_model must register Metric as a hypertable."""
        assert _is_hypertable('timescale_tests_metric')

    def test_another_metric_table_is_hypertable(self):
        """TimescaleModel subclass must also become a hypertable."""
        assert _is_hypertable('timescale_tests_anothermetric')

    def test_metric_partition_column_is_time(self):
        """Hypertable partition column must be the TimescaleDateTimeField column."""
        assert _get_partition_column('timescale_tests_metric') == 'time'

    def test_another_metric_partition_column_is_time(self):
        assert _get_partition_column('timescale_tests_anothermetric') == 'time'


class TestAlterField:
    def test_alter_interval_does_not_destroy_hypertable(self):
        """
        Calling alter_field to change TimescaleDateTimeField interval must call
        set_chunk_time_interval and leave the table as a hypertable.
        """
        from timescale.db.models.fields import TimescaleDateTimeField

        old_field = Metric._meta.get_field('time')  # interval='1 day'
        new_field = TimescaleDateTimeField(interval='2 days')
        new_field.set_attributes_from_name('time')
        new_field.model = Metric

        try:
            with connection.schema_editor() as editor:
                editor.alter_field(Metric, old_field, new_field)
            # Table must still be a hypertable after the alter
            assert _is_hypertable('timescale_tests_metric')
        finally:
            # Restore original interval so subsequent tests are unaffected
            with connection.schema_editor() as editor:
                editor.alter_field(Metric, new_field, old_field)


class TestAddField:
    @pytest.mark.django_db(transaction=True)
    def test_add_timescale_field_converts_table_to_hypertable(self):
        """add_field with TimescaleDateTimeField migrates an existing plain table to a hypertable."""
        with isolate_apps('timescale.tests'):
            class TempTable(dj_models.Model):
                value = dj_models.FloatField(default=0.0)
                class Meta:
                    app_label = 'timescale_tests'
                    db_table = 'timescale_tests_temptable_addfield'

            # Create the table WITHOUT a TimescaleDateTimeField (plain table, not a hypertable)
            with connection.schema_editor() as editor:
                editor.create_model(TempTable)

            try:
                assert not _is_hypertable('timescale_tests_temptable_addfield')

                new_field = TimescaleDateTimeField(interval='1 day', null=True)
                new_field.set_attributes_from_name('ts')
                new_field.model = TempTable

                with connection.schema_editor() as editor:
                    editor.add_field(TempTable, new_field)

                assert _is_hypertable('timescale_tests_temptable_addfield')
            finally:
                with connection.schema_editor() as editor:
                    try:
                        editor.delete_model(TempTable)
                    except Exception:
                        pass


class TestAlterFieldToHypertable:
    @pytest.mark.django_db(transaction=True)
    def test_alter_datetime_to_timescale_converts_to_hypertable(self):
        """alter_field from DateTimeField to TimescaleDateTimeField migrates table to hypertable."""
        with isolate_apps('timescale.tests'):
            class TempTable2(dj_models.Model):
                ts = dj_models.DateTimeField(null=True)
                value = dj_models.FloatField(default=0.0)
                class Meta:
                    app_label = 'timescale_tests'
                    db_table = 'timescale_tests_temptable_alterfield'

            with connection.schema_editor() as editor:
                editor.create_model(TempTable2)

            try:
                assert not _is_hypertable('timescale_tests_temptable_alterfield')

                old_field = TempTable2._meta.get_field('ts')
                new_field = TimescaleDateTimeField(interval='1 day', null=True)
                new_field.set_attributes_from_name('ts')
                new_field.model = TempTable2

                with connection.schema_editor() as editor:
                    editor.alter_field(TempTable2, old_field, new_field)

                assert _is_hypertable('timescale_tests_temptable_alterfield')
            finally:
                with connection.schema_editor() as editor:
                    try:
                        editor.delete_model(TempTable2)
                    except Exception:
                        pass


class TestGetExtraCondition:
    def test_attribute_error_is_silenced(self):
        """Without django-tenants, schema_name doesn't exist — AttributeError must be silently ignored."""
        from unittest.mock import MagicMock
        from timescale.db.backends.postgresql.schema import TimescaleSchemaEditor

        editor = TimescaleSchemaEditor.__new__(TimescaleSchemaEditor)
        # spec=[] means the mock has NO attributes — accessing .schema_name raises AttributeError
        editor.connection = MagicMock(spec=[])

        result = editor._get_extra_condition()
        assert result == ''

    def test_non_attribute_errors_propagate(self):
        """Any exception OTHER than AttributeError must not be swallowed."""
        from unittest.mock import MagicMock, PropertyMock
        from timescale.db.backends.postgresql.schema import TimescaleSchemaEditor

        editor = TimescaleSchemaEditor.__new__(TimescaleSchemaEditor)
        mock_conn = MagicMock()
        type(mock_conn).schema_name = PropertyMock(side_effect=RuntimeError("unexpected error"))
        editor.connection = mock_conn

        with pytest.raises(RuntimeError, match="unexpected error"):
            editor._get_extra_condition()
