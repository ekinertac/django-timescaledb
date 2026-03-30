import pytest
from django.db import connection

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
